#!/usr/bin/env python3
"""MeridianFeed collector (Phase 2) — lean, stdlib only.

Fetches each enabled source once (polite, browser UA), extracts V2Ray config
URIs, parses them strictly, hard-rejects Gate-1 junk, and dedups ACROSS
sources on protocol+server+port+credential_hash.

Raw configs live in memory only. The only output is a stats summary as JSON
on stdout — no credentials, no raw URIs, ever.

Usage: python3 pipeline/collector.py [pipeline/sources.json]
"""
import base64
import hashlib
import html
import ipaddress
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
TIMEOUT = 30
PROTOCOLS = ("vless", "vmess", "trojan", "ss", "hysteria2", "tuic")
URI_RE = re.compile(
    r"(?:vless|vmess|trojan|ss|hysteria2|hy2|tuic)://[^\s<>\"'\)\]]+", re.I)
HOST_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$")

BAD_NETS = [ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
    "169.254.0.0/16", "172.16.0.0/12", "192.168.0.0/16", "240.0.0.0/4",
    "::1/128", "fe80::/10", "fc00::/7")]
BAD_HOSTS = {"localhost", "127.0.0.53"}

# Cloudflare anycast ranges + a small curated set of edge IPs used for
# presentation variants (see expand_cf_variants). The first three IPs
# are field-proven from Iran (wolf's tests, 2026-11-20); the fourth was
# observed as an edge address in our own collected pool.
CF_NETS = [ipaddress.ip_network(n) for n in (
    "104.16.0.0/13", "104.24.0.0/14", "172.64.0.0/13", "162.158.0.0/15",
    "198.41.128.0/17", "173.245.48.0/20", "188.114.96.0/20",
    "190.93.240.0/20", "197.234.240.0/22", "198.41.192.0/18")]
CF_VARIANT_IPS = ("172.64.145.93", "188.114.99.137",
                  "172.67.190.164", "104.18.42.163")
MAX_CF_VARIANTS = 3
# Cloudflare HTTPS listener ports: a CF-fronted service answers on all
# of them, so at IDENTITY level they are one service (Plan Rev.2 R3 —
# normalisation applies to identity only; the served/tested URI keeps
# its real port, and composition keeps its field-derived port policy).
CF_HTTPS_PORTS = {443, 2053, 2083, 2087, 2096, 8443}

_resolve_cache = {}


def _resolve_ips(host):
    """Resolve a hostname to IPs (cached per process); [] on failure."""
    host = (host or "").strip().lower()
    if not host:
        return []
    if host in _resolve_cache:
        return _resolve_cache[host]
    try:
        ipaddress.ip_address(host)
        ips = [host]
    except ValueError:
        import socket
        try:
            ips = sorted({info[4][0] for info in
                          socket.getaddrinfo(host, None)})
        except Exception:
            ips = []
    _resolve_cache[host] = ips
    return ips


def _in_cf(ip_text):
    try:
        addr = ipaddress.ip_address(ip_text)
    except ValueError:
        return False
    return any(addr in net for net in CF_NETS if net.version == addr.version)


def _uri_extras(uri):
    """(transport, security, sni, host_header, path) for fronting and
    service-identity decisions. Empty strings when absent."""
    if uri.lower().startswith("vmess://"):
        decoded = b64decode_loose(uri.split("://", 1)[1].split("#", 1)[0]
                                  .split("?", 1)[0])
        try:
            data = json.loads(decoded or "")
        except Exception:
            return "tcp", "", "", "", ""
        return (str(data.get("net") or "tcp").lower(),
                "tls" if str(data.get("tls") or "").lower() == "tls" else "",
                str(data.get("sni") or ""), str(data.get("host") or ""),
                str(data.get("path") or ""))
    from urllib.parse import urlparse, parse_qs
    try:
        parsed = urlparse(uri)
        query = parse_qs(parsed.query)
    except ValueError:
        return "tcp", "", "", "", ""
    first = lambda name: (query.get(name) or [""])[0]
    return ((first("type") or first("net") or "tcp").lower(),
            first("security").lower(), first("sni"), first("host"),
            first("path"))


def cf_fronted(record, uri):
    """True when the config rides the Cloudflare edge: WS+TLS whose
    address is a CF anycast IP, or whose SNI/Host (or address) domain
    resolves into CF ranges. Only then is swapping the address across
    edge IPs connection-preserving."""
    if record["protocol"] not in ("vmess", "vless", "trojan"):
        return False
    transport, security, sni, host_header, _ = _uri_extras(uri)
    if transport != "ws" or security != "tls":
        return False
    if _in_cf(record["server"]):
        return True
    for domain in (sni, host_header, record["server"]):
        if domain and not _in_cf(domain):  # a domain, not an IP literal
            if any(_in_cf(ip) for ip in _resolve_ips(domain)):
                return True
    return False


_AKAMAI_NETS = None


def _akamai_nets():
    """Akamai ranges lifted under R5.1 (data/akamai_ranges.txt) —
    loaded lazily, empty when the data file is absent (tests, old
    checkouts). A new fronting surface: disjoint from every CF range,
    so an Akamai-fronted config is a genuinely different edge."""
    global _AKAMAI_NETS
    if _AKAMAI_NETS is None:
        nets = []
        try:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "data", "akamai_ranges.txt")
            with open(path, encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        nets.append(ipaddress.ip_network(line))
        except Exception:
            nets = []
        _AKAMAI_NETS = nets
    return _AKAMAI_NETS


def akamai_fronted(record, uri):
    """True when the config's server is an Akamai edge IP (literal, or
    a domain resolving into Akamai ranges). A classification flag
    only: no ranking change ships with it — when Akamai-fronted
    candidates appear in volume, their field treatment is a separate
    decision. Crash-safe: any parse surprise yields False."""
    try:
        server = record.get("server", "") or ""
        try:
            ipaddress.ip_address(server)
            is_ip = True
        except ValueError:
            is_ip = False
        if is_ip:
            ip = ipaddress.ip_address(server)
            return any(ip in net for net in _akamai_nets())
        return any(_akamai_ip(ip) for ip in _resolve_ips(server))
    except Exception:
        return False


def _akamai_ip(ip_text):
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return False
    return any(ip in net for net in _akamai_nets())


def front_class(record, uri):
    """Survival class of a config (field-measured order, wolf's field
    tests 2026-11-20): 0 CF-anycast-IP WS+TLS, 1 domain WS+TLS
    (CDN-fronted), 2 plain Shadowsocks (no TLS layer), 3 REALITY
    with SNI, 4 REALITY without SNI, 5 everything else (bare
    direct-IP TLS, Hysteria2/UDP — the classes that died wholesale
    in the field). Lower survives better. This is the shared
    definition: the composer carries the same logic over raw URIs
    (compose.classify_uri) and the two must never drift. Crash-safe:
    any parse surprise yields class 5, never an exception."""
    try:
        protocol = record["protocol"]
        port = record["port"]
        transport, security, sni, host_header, _ = _uri_extras(uri)
        if protocol == "vmess":
            sni_eff = sni or host_header
        else:
            sni_eff = sni
        if protocol == "ss":
            from urllib.parse import urlparse, parse_qs
            plugin = (parse_qs(urlparse(uri).query).get("plugin")
                      or [""])[0].lower()
            if "tls" in plugin:  # v2ray-plugin style: not plain SS
                security = "tls"
                transport = "ws"
        server = record["server"] or ""
        try:
            ipaddress.ip_address(server)
            is_ip = True
        except ValueError:
            is_ip = False
        cf = bool(is_ip and _in_cf(server))
        if transport == "ws" and security == "tls" and cf:
            return 0
        if transport == "ws" and security == "tls" and not is_ip:
            return 1
        if protocol == "ss" and security != "tls":
            return 2
        if security == "reality" and sni_eff:
            return 3
        if security == "reality":
            return 4
        return 5
    except Exception:
        return 5


def _swap_vmess_add(uri, new_host):
    decoded = b64decode_loose(uri.split("://", 1)[1].split("#", 1)[0]
                              .split("?", 1)[0])
    data = json.loads(decoded or "")
    data["add"] = new_host
    return "vmess://" + base64.b64encode(
        json.dumps(data).encode()).decode()


def _swap_url_host(uri, new_host):
    scheme, rest = uri.split("://", 1)
    match = re.match(r"([^/?#]*)(.*)", rest, re.S)
    authority, tail = match.group(1), match.group(2)
    if "@" in authority:
        userinfo, hostport = authority.rsplit("@", 1)
        prefix = userinfo + "@"
    else:
        prefix, hostport = "", authority
    if hostport.startswith("[") and "]" in hostport:
        hostport = new_host + hostport[hostport.index("]") + 1:]
    elif ":" in hostport:
        hostport = new_host + ":" + hostport.rsplit(":", 1)[1]
    else:
        hostport = new_host
    return "%s://%s%s%s" % (scheme, prefix, hostport, tail)


def expand_cf_variants(record, uri):
    """Presentation variants of a Cloudflare-fronted config (BPB
    lesson, field-proven 2026-11-20): the SAME service presented via
    several CF anycast IPs — only the address changes; SNI, Host, path
    and credentials are untouched. Each variant parses to its own dedup
    key and must pass the verifier gates on its own merits — variants
    inherit nothing. Returns [(record, uri)] with the original first;
    just the original when the config is not CF-fronted."""
    out = [(record, uri)]
    if not cf_fronted(record, uri):
        return out
    for ip in CF_VARIANT_IPS:
        if len(out) > MAX_CF_VARIANTS:
            break
        if ip == record["server"]:
            continue
        variant_uri = (_swap_vmess_add(uri, ip)
                       if record["protocol"] == "vmess"
                       else _swap_url_host(uri, ip))
        variant = parse_uri(variant_uri, record.get("source", ""))
        if variant is None or dedup_key(variant) == dedup_key(record):
            continue
        out.append((variant, variant_uri))
    return out


def service_key(record, uri):
    """Identity of the origin service behind a config: protocol +
    credential + port + front identity (SNI/Host) + path. Presentation
    variants of one service share a service key even though their
    dedup keys differ — composition caps per service, not per IP."""
    _, _, sni, host_header, path = _uri_extras(uri)
    front = (sni or host_header or record["server"]).lower()
    return hashlib.sha256("|".join((
        record["protocol"], record["credential_hash"],
        str(record["port"]), front, path)).encode("utf-8")).hexdigest()


def service_key_from_uri(uri):
    record = parse_uri(uri, "")
    return service_key(record, uri) if record else None


def identity_key(record, uri):
    """CDN-aware collection identity (Plan Rev.2 R1 — the approach of
    Radikal core.py's dedup_key and patterniha's Node.identity(),
    reimplemented in-house): two listings are the same CANDIDATE when
    they name the same origin service, even if different sources print
    different edge addresses for it.

    For a Cloudflare-fronted config the raw address is a presentation,
    not the service: identity = protocol + credential + front identity
    (SNI/Host) + path, with the port normalised across the Cloudflare
    HTTPS listener set (R3: those ports all reach the same service).
    The deliberate presentations are regenerated afterwards by
    expand_cf_variants from the surviving representative — capped and
    independently gated — instead of being collected as accidents.
    For anything not CF-fronted, identity is exactly the dedup key,
    so behaviour there is unchanged. Distinct services sharing a
    fronting domain still differ by credential and path."""
    if cf_fronted(record, uri):
        _, _, sni, host_header, path = _uri_extras(uri)
        front = (sni or host_header or record["server"]).lower()
        port = record["port"]
        if port in CF_HTTPS_PORTS:
            port = 443
        return "svc|" + hashlib.sha256("|".join((
            record["protocol"], record["credential_hash"], str(port),
            front, path)).encode("utf-8")).hexdigest()
    return "key|" + dedup_key(record)


def _cf_addressed(record, uri):
    """True when the connect address itself rides the Cloudflare edge
    (anycast IP literal, or a domain — address, SNI or Host — that
    resolves into CF ranges), regardless of transport/security."""
    if _in_cf(record["server"]):
        return True
    _, _, sni, host_header, _ = _uri_extras(uri)
    for domain in (sni, host_header, record["server"]):
        if domain and not _in_cf(domain):  # a domain, not an IP literal
            if any(_in_cf(ip) for ip in _resolve_ips(domain)):
                return True
    return False


def cf_shape_reject(record, uri):
    """Gate-1.5 shape drops for Cloudflare-addressed nodes (Plan Rev.2
    R3, patterniha transform): returns a reason string or None.

    - plaintext on 443: the CF edge's 443 listener is TLS-only, so a
      no-TLS vless/vmess addressed at the edge on 443 can never
      handshake — it only burns Gate-2/3 budget. (Trojan is exempt:
      it is TLS by definition and often omits the security param.)
    - TLS on 8080: 8080 is the edge's plaintext-HTTP listener; a TLS
      config pointed there is the same class of misprint."""
    if record["protocol"] not in ("vless", "vmess", "trojan"):
        return None
    _, security, _, _, _ = _uri_extras(uri)
    if record["protocol"] == "trojan":
        security = "tls"  # TLS by definition; param often omitted
    if not _cf_addressed(record, uri):
        return None
    if record["port"] == 443 and security != "tls":
        return "cf_plaintext_443"
    if record["port"] == 8080 and security == "tls":
        return "cf_tls_8080"
    return None


def b64decode_loose(text):
    """Decode base64 with missing padding, standard or urlsafe alphabet."""
    text = re.sub(r"\s+", "", text)
    text += "=" * (-len(text) % 4)
    for alt in (None, "-_"):
        try:
            if alt:
                return base64.b64decode(text, altchars=b"-_").decode("utf-8", "replace")
            return base64.b64decode(text).decode("utf-8", "replace")
        except Exception:
            continue
    return None


def host_ok(host):
    """Gate-1 host check: no loopback/private/reserved/placeholder hosts."""
    if not host:
        return False
    host = host.strip().strip("[]").rstrip(".").lower()
    if host in BAD_HOSTS or host.endswith((".localhost", ".local", ".invalid")):
        return False
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_multicast or ip.is_unspecified:
            return False
        return not any(ip in net for net in BAD_NETS if net.version == ip.version)
    except ValueError:
        return bool(HOST_RE.match(host))


def cred_hash(material):
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _split_hostport(text):
    """Split 'host:port' (query already stripped). Returns (host, port|None)."""
    text = text.split("?")[0].split("/")[0]
    if text.startswith("["):
        end = text.find("]")
        if end < 0 or ":" not in text[end:]:
            return text.strip("[]"), None
        host, port = text[1:end], text[end + 2:]
    elif ":" in text:
        host, port = text.rsplit(":", 1)
    else:
        return text, None
    try:
        return host, int(port)
    except ValueError:
        return host, None


def _record(protocol, server, port, credential, transport, source):
    server = (server or "").strip().strip("[]").rstrip(".").lower()
    if not credential or not port or not (1 <= port <= 65535) or not host_ok(server):
        return None
    return {"protocol": protocol, "server": server, "port": port,
            "credential_hash": cred_hash(credential),
            "transport": transport or "tcp", "source": source}


def _parse_ss(rest, source):
    rest = rest.split("#", 1)[0]
    if "@" in rest:
        userinfo, hostport = rest.rsplit("@", 1)
        from urllib.parse import unquote
        userinfo = unquote(userinfo)
        credential = userinfo if ":" in userinfo else b64decode_loose(userinfo)
        host, port = _split_hostport(hostport)
    else:  # legacy: whole payload is base64(method:password@host:port)
        decoded = b64decode_loose(rest)
        if not decoded or "@" not in decoded:
            return None
        credential, hostport = decoded.rsplit("@", 1)
        host, port = _split_hostport(hostport)
    if not credential or ":" not in credential:
        return None
    return _record("ss", host, port, credential, "tcp", source)


def _parse_vmess(rest, source):
    decoded = b64decode_loose(rest.split("#", 1)[0].split("?")[0])
    if not decoded:
        return None
    try:
        data = json.loads(decoded)
        port = int(data.get("port") or 0)
    except Exception:
        return None
    return _record("vmess", data.get("add"), port, data.get("id"),
                   data.get("net") or "tcp", source)


def parse_uri(uri, source=""):
    """Parse one config URI into a record, or None if Gate-1 rejects it."""
    from urllib.parse import urlparse, parse_qs, unquote
    scheme, _, rest = uri.partition("://")
    scheme = scheme.lower()
    if scheme == "hy2":
        scheme = "hysteria2"
    if scheme not in PROTOCOLS or not rest:
        return None
    if scheme == "vmess":
        return _parse_vmess(rest, source)
    if scheme == "ss":
        return _parse_ss(rest, source)
    try:
        parsed = urlparse(uri)
        port = parsed.port
    except ValueError:
        return None
    host = parsed.hostname
    query = parse_qs(parsed.query)
    transport = (query.get("type") or query.get("net") or [None])[0]
    user = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    if scheme == "vless":
        return _record("vless", host, port, user, transport or "tcp", source)
    if scheme == "trojan":
        return _record("trojan", host, port, password or user,
                       transport or "tcp", source)
    if scheme == "hysteria2":
        return _record("hysteria2", host, port, password or user, "udp", source)
    if scheme == "tuic":
        credential = "%s:%s" % (user, password) if user else ""
        return _record("tuic", host, port, credential,
                       transport or "udp", source)
    return None


def dedup_key(record):
    return "%s|%s|%d|%s" % (record["protocol"], record["server"],
                            record["port"], record["credential_hash"])


def extract_candidates(text):
    text = html.unescape(text or "")
    return [m.group(0).rstrip(".,;") for m in URI_RE.finditer(text)]


def candidate_texts(raw):
    """Raw text plus, when the payload is a base64 blob, its decoding."""
    text = raw.decode("utf-8", "replace")
    texts = [text]
    compact = re.sub(r"\s+", "", text)
    if len(compact) > 80 and re.fullmatch(r"[A-Za-z0-9+/=_-]+", compact or ""):
        decoded = b64decode_loose(compact)
        if decoded and "://" in decoded:
            texts.append(decoded)
    return texts


def _snapshot_path(url):
    cache_dir = os.environ.get("COLLECTOR_CACHE_DIR")
    if not cache_dir:
        return None
    return os.path.join(cache_dir, hashlib.sha256(url.encode()).hexdigest() + ".json")


def fetch(url):
    """One polite fetch per source per cycle, spread out and conditional.

    Pacing: a jittered 0.4–1.5 s pause before every network request, and
    callers fetch sequentially in randomised source order, so sources
    never see a synchronised burst. Conditional requests: when
    COLLECTOR_CACHE_DIR is set, the last body per URL is snapshotted
    there and revalidation uses ETag / If-Modified-Since — an unchanged
    list costs a 304 with no body download instead of a full transfer.
    Set COLLECTOR_PACING=0 to disable the pause (unit tests).
    """
    if os.environ.get("COLLECTOR_PACING", "1") != "0":
        time.sleep(random.uniform(0.4, 1.5))
    headers = {"User-Agent": UA}
    snap_path = _snapshot_path(url)
    snap = None
    if snap_path and os.path.exists(snap_path):
        try:
            with open(snap_path, encoding="utf-8") as handle:
                snap = json.load(handle)
        except Exception:
            snap = None
    if snap:
        if snap.get("etag"):
            headers["If-None-Match"] = snap["etag"]
        if snap.get("last_modified"):
            headers["If-Modified-Since"] = snap["last_modified"]
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read(8 * 1024 * 1024)
            etag = response.headers.get("ETag")
            last_modified = response.headers.get("Last-Modified")
    except urllib.error.HTTPError as exc:
        if exc.code == 304 and snap:
            return base64.b64decode(snap["body_b64"])
        raise
    # A snapshot without validators can never revalidate (no 304
    # path), so storing it only wastes cache space.
    if snap_path and (etag or last_modified):
        try:
            os.makedirs(os.path.dirname(snap_path), exist_ok=True)
            with open(snap_path, "w", encoding="utf-8") as handle:
                json.dump({"etag": etag, "last_modified": last_modified,
                           "body_b64": base64.b64encode(body).decode()}, handle)
        except Exception:
            pass  # a cache write failure never fails the fetch
    return body


def source_urls(source):
    """URL list for a registry entry: a single `url`, or a `urls`
    list (R4: Au1rxx's 6 all-verified shards as one upstream — the
    collector cannot concatenate, so the registry lists the shards)."""
    urls = source.get("urls")
    if urls:
        return list(urls)
    url = source.get("url")
    return [url] if url else []


def fetch_source(source):
    """Fetch every URL of a source; returns ([(url, body)], [errors])
    for the URLs that succeeded. Raises the last error when ALL fail —
    a single dead shard never kills the whole upstream."""
    urls = source_urls(source)
    if not urls:
        raise ValueError("source %s has no url(s)" % source.get("name"))
    fetched, errors = [], []
    for url in urls:
        try:
            fetched.append((url, fetch(url)))
        except Exception as exc:  # noqa: BLE001 - per-URL, keep going
            errors.append("%s: %s: %s" % (url, type(exc).__name__, exc))
    if not fetched:
        raise RuntimeError("; ".join(errors))
    return fetched, errors


def collect_source(source, seen, seen_identity=None):
    if seen_identity is None:
        seen_identity = {}
    stats = {"name": source["name"], "facet": source.get("facet", ""),
             "type": source.get("type", ""), "url": source.get("url", ""),
             "ok": False, "error": None, "fetched_bytes": 0, "fetched": 0,
             "valid": 0, "rejected": 0, "duplicates": 0, "unique_new": 0,
             "identity_duplicates": 0, "shape_rejected": 0,
             "variants": 0, "unique_hosts": 0, "protocols": {},
             "urls_fetched": 0, "fetch_errors": [], "akamai_fronted": 0}
    try:
        fetched, errors = fetch_source(source)
    except Exception as exc:  # one polite fetch per URL; failures reported
        stats["error"] = "%s: %s" % (type(exc).__name__, exc)
        return stats
    stats["ok"] = True
    stats["urls_fetched"] = len(fetched)
    stats["fetch_errors"] = errors
    stats["fetched_bytes"] = sum(len(body) for _, body in fetched)
    candidates = []
    for _, raw in fetched:
        for text in candidate_texts(raw):
            candidates.extend(extract_candidates(text))
    stats["fetched"] = len(candidates)
    hosts = set()
    for uri in candidates:
        record = parse_uri(uri, source["name"])
        if record is None:
            stats["rejected"] += 1
            continue
        stats["valid"] += 1
        stats["protocols"][record["protocol"]] = \
            stats["protocols"].get(record["protocol"], 0) + 1
        if akamai_fronted(record, uri):
            # R5.1: new fronting surface, counted on every valid
            # record (before dedup) so a live cycle shows whether
            # Akamai-fronted candidates exist at all.
            stats["akamai_fronted"] += 1
        if cf_shape_reject(record, uri) is not None:
            stats["shape_rejected"] += 1
            continue
        key = dedup_key(record)
        if key in seen:
            stats["duplicates"] += 1
            continue
        ident = identity_key(record, uri)
        if ident in seen_identity:
            # Same origin service already collected under another
            # presentation (R1 identity dedup): not a new candidate.
            stats["identity_duplicates"] += 1
            continue
        seen_identity[ident] = key
        seen[key] = record
        stats["unique_new"] += 1
        hosts.add(record["server"])
        # CF-fronted configs multiply into presentation variants at
        # collect time; each variant is an ordinary candidate with its
        # own dedup key and must pass the gates independently.
        for vrec, _vuri in expand_cf_variants(record, uri):
            vkey = dedup_key(vrec)
            if vkey in seen:
                continue
            seen[vkey] = vrec
            stats["variants"] += 1
            hosts.add(vrec["server"])
    stats["unique_hosts"] = len(hosts)
    return stats


def main(argv):
    registry_path = argv[1] if len(argv) > 1 else "pipeline/sources.json"
    with open(registry_path, encoding="utf-8") as handle:
        registry = json.load(handle)
    # Source governance (Plan Rev.2 R1): when a governance state file
    # sits next to the registry, sources it has auto-disabled are
    # skipped here (and in the verifier), and this cycle's unique
    # yields are appended to its rolling history after the run.
    gov_state, gov_path = None, None
    try:
        import governance
        candidate = os.path.join(os.path.dirname(
            os.path.abspath(registry_path)), "governance_state.json")
        if os.path.exists(candidate):
            gov_path = candidate
            gov_state = governance.load(gov_path)
    except Exception:
        gov_state, gov_path = None, None
    gov_disabled = governance.disabled_names(gov_state) if gov_state else set()
    seen, seen_identity = {}, {}
    per_source = []
    for source in registry.get("sources", []):
        if not source.get("enabled", True):
            continue
        if source["name"] in gov_disabled:
            per_source.append({
                "name": source["name"], "facet": source.get("facet", ""),
                "type": source.get("type", ""), "url": source.get("url", ""),
                "ok": False, "error": "governance_disabled",
                "governance_disabled": True, "fetched_bytes": 0,
                "fetched": 0, "valid": 0, "rejected": 0, "duplicates": 0,
                "unique_new": 0, "identity_duplicates": 0,
                "shape_rejected": 0, "variants": 0, "unique_hosts": 0,
                "protocols": {}})
            continue
        per_source.append(collect_source(source, seen, seen_identity))
    if gov_state is not None:
        try:
            import time as _time
            governance.update(gov_state, per_source, _time.time())
            newly = governance.apply_disables(
                gov_state, registry.get("sources", []))
            governance.save(gov_path, gov_state)
            if newly:
                print("governance: auto-disabled " + ", ".join(
                    f"{n} ({r})" for n, r in newly.items()),
                    file=sys.stderr)
        except Exception as exc:  # governance never breaks a collect
            print(f"governance update failed: {exc}", file=sys.stderr)
    totals = {"sources": len(per_source),
              "sources_ok": sum(1 for s in per_source if s["ok"]),
              "fetched": sum(s["fetched"] for s in per_source),
              "valid": sum(s["valid"] for s in per_source),
              "rejected": sum(s["rejected"] for s in per_source),
              "duplicates": sum(s["duplicates"] for s in per_source),
              "identity_duplicates":
                  sum(s.get("identity_duplicates", 0) for s in per_source),
              "shape_rejected":
                  sum(s.get("shape_rejected", 0) for s in per_source),
              "variants": sum(s["variants"] for s in per_source),
              "unique_records": len(seen),
              "unique_hosts": len({r["server"] for r in seen.values()}),
              "protocols": {}}
    for record in seen.values():
        totals["protocols"][record["protocol"]] = \
            totals["protocols"].get(record["protocol"], 0) + 1
    print(json.dumps({"sources": per_source, "totals": totals}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
