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
            snap = json.load(open(snap_path, encoding="utf-8"))
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
    if snap_path:
        try:
            os.makedirs(os.path.dirname(snap_path), exist_ok=True)
            with open(snap_path, "w", encoding="utf-8") as handle:
                json.dump({"etag": etag, "last_modified": last_modified,
                           "body_b64": base64.b64encode(body).decode()}, handle)
        except Exception:
            pass  # a cache write failure never fails the fetch
    return body


def collect_source(source, seen):
    stats = {"name": source["name"], "facet": source.get("facet", ""),
             "type": source.get("type", ""), "url": source["url"],
             "ok": False, "error": None, "fetched_bytes": 0, "fetched": 0,
             "valid": 0, "rejected": 0, "duplicates": 0, "unique_new": 0,
             "unique_hosts": 0, "protocols": {}}
    try:
        raw = fetch(source["url"])
    except Exception as exc:  # one polite fetch; failures are reported, not retried
        stats["error"] = "%s: %s" % (type(exc).__name__, exc)
        return stats
    stats["ok"] = True
    stats["fetched_bytes"] = len(raw)
    candidates = []
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
        key = dedup_key(record)
        if key in seen:
            stats["duplicates"] += 1
            continue
        seen[key] = record
        stats["unique_new"] += 1
        hosts.add(record["server"])
    stats["unique_hosts"] = len(hosts)
    return stats


def main(argv):
    registry_path = argv[1] if len(argv) > 1 else "pipeline/sources.json"
    with open(registry_path, encoding="utf-8") as handle:
        registry = json.load(handle)
    seen = {}
    per_source = []
    for source in registry.get("sources", []):
        if source.get("enabled", True):
            per_source.append(collect_source(source, seen))
    totals = {"sources": len(per_source),
              "sources_ok": sum(1 for s in per_source if s["ok"]),
              "fetched": sum(s["fetched"] for s in per_source),
              "valid": sum(s["valid"] for s in per_source),
              "rejected": sum(s["rejected"] for s in per_source),
              "duplicates": sum(s["duplicates"] for s in per_source),
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
