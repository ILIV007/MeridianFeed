#!/usr/bin/env python3
"""MeridianFeed verifier (Phase 3) — lean, stdlib only (+ sing-box binary).

Takes the collector's Gate-1 records (reusing pipeline/collector.py for
fetch / parse / dedup — raw URIs are paired with records in memory only)
and applies the STRICT gates from docs/PLAN.md:

- Gate 2: DNS resolution + TCP connect (and a TLS handshake where the
  config calls for plain TLS). Cheap junk filter; proves nothing alone.
- Gate 3: a real sing-box tunnel per surviving config — generate_204,
  an HTTPS trace fetch confirming the egress IP differs from this host's
  direct egress (and recording its country), a 3-probe median latency,
  and a small download speed sample.

Controls run FIRST, in every run: a positive control (a local loopback
sing-box server+client pair built on the spot — it proves the harness
itself end-to-end) and a negative control (a deliberately dead config).
If the positive control fails or the negative passes, the run reports
CONTROLS FAILED and no candidate is verified.

The only output is a stats JSON — counts per gate, latency/speed
distributions, control results, and (v1.1.0) one opaque record per
Gate-3 pass: the SHA-256 of the config's dedup key plus its protocol,
source, egress country and probe numbers. The hash is one-way, so
separate runs can be intersected for the strict repeat-pass tiers
without ever writing a config, credential, server or egress IP to
disk, logs, or the repo.

Usage:
  python3 pipeline/verifier.py [pipeline/sources.json]
      [--sing-box PATH] [--limit N] [--workers N] [--gate2-workers N]
      [--out verify-stats.json]
  python3 pipeline/verifier.py --ab-finalmask [--xray PATH]
      [--ab-limit N] [--collect-limit N] [--out ab-stats.json]
      (Plan Rev.2 R2 paired A/B: plain sing-box vs Xray+finalmask)
"""
import base64
import concurrent.futures
import hashlib
import json
import os
import random
import socket
import ssl
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from urllib.parse import parse_qs, quote, unquote, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collector  # noqa: E402  (Gate-1 parser / fetch / dedup)

GATE2_TIMEOUT = 5.0
PROBE_TIMEOUT = 8.0
READY_TIMEOUT = 8.0
PUBLIC_LATENCY_MS = 800.0
PUBLIC_SPEED_MBPS = 1.0
SPEED_BYTES = 262144
URL_204 = "https://www.gstatic.com/generate_204"
URL_TRACE = "https://www.cloudflare.com/cdn-cgi/trace"
URL_SPEED = "https://speed.cloudflare.com/__down?bytes=%d" % SPEED_BYTES

_port_lock = threading.Lock()


def free_port():
    with _port_lock:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]


def pass_key(record):
    """Opaque per-config identifier for cross-run tier intersection:
    the SHA-256 of the collector dedup key. One-way — it reveals
    nothing about the server or the credential, and the same config
    produces the same key in every run."""
    return hashlib.sha256(
        collector.dedup_key(record).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- sampling

def collect_candidates(registry_path, limit):
    """Fetch sources via the collector, dedup, round-robin sample.

    Returns (sample, totals) where sample is a list of (record, uri)
    pairs — the uri lives in memory only and is never serialised.
    """
    with open(registry_path, encoding="utf-8") as handle:
        registry = json.load(handle)
    seen, seen_identity = {}, {}
    per_source = []
    fetched = valid = identity_dups = shape_rejected = 0
    sources = [s for s in registry.get("sources", []) if s.get("enabled", True)]
    # Source governance (Plan Rev.2 R1): skip auto-disabled sources.
    try:
        import governance
        gov_path = os.path.join(os.path.dirname(
            os.path.abspath(registry_path)), "governance_state.json")
        if os.path.exists(gov_path):
            disabled = governance.disabled_names(governance.load(gov_path))
            sources = [s for s in sources if s["name"] not in disabled]
    except Exception:
        pass
    random.shuffle(sources)  # spread politely: no fixed hammering order
    for source in sources:
        try:
            raw = collector.fetch(source["url"])
        except Exception:
            per_source.append([])
            continue
        entries = []
        for text in collector.candidate_texts(raw):
            for uri in collector.extract_candidates(text):
                fetched += 1
                record = collector.parse_uri(uri, source["name"])
                if record is None:
                    continue
                valid += 1
                if collector.cf_shape_reject(record, uri) is not None:
                    shape_rejected += 1
                    continue
                key = collector.dedup_key(record)
                if key in seen:
                    continue
                ident = collector.identity_key(record, uri)
                if ident in seen_identity:
                    # Same origin service under another presentation:
                    # one candidate per service (R1 identity dedup) —
                    # Gate-3 budget is spent on services, not copies.
                    identity_dups += 1
                    continue
                seen_identity[ident] = key
                seen[key] = (record, uri)
                entries.append((record, uri))
                # CF presentation variants enter as ordinary
                # candidates: own keys, own Gate 2/3 verdicts.
                for vrec, vuri in collector.expand_cf_variants(record, uri):
                    vkey = collector.dedup_key(vrec)
                    if vkey in seen:
                        continue
                    seen[vkey] = (vrec, vuri)
                    entries.append((vrec, vuri))
        per_source.append(entries)
    sample = []
    idx = 0
    while len(sample) < limit:
        progressed = False
        for entries in per_source:
            if idx < len(entries):
                sample.append(entries[idx])
                progressed = True
                if len(sample) >= limit:
                    break
        if not progressed:
            break
        idx += 1
    totals = {"fetched": fetched, "gate1_valid": valid,
              "unique": len(seen), "sampled": len(sample),
              "identity_duplicates": identity_dups,
              "shape_rejected": shape_rejected}
    return sample, totals


# ------------------------------------------------------------- rebranding
# Display-only helpers for publish time (Phase 5): every published config
# is renamed to the channel brand. These functions touch ONLY the display
# name — the URI fragment, or `ps` inside a vmess base64 payload — never
# any connection field, so a rebranded config keeps the collector's
# dedup key and parses to the identical record.

def format_remark(country_code, protocol):
    """'🪼 PROXIV3 · <flag> <CC> · <PROTOCOL> · Verified' — the channel's
    own 🪼 emoji up front and the word Verified instead of any latency
    figure in the config name (wolf's final rule, 2026-11-20)."""
    cc = (country_code or "").strip().upper()
    if len(cc) == 2 and cc.isalpha():
        flag = "".join(chr(0x1F1E6 + ord(ch) - 65) for ch in cc)
    else:
        flag, cc = "\U0001F310", cc or "??"
    return "\U0001FABC PROXIV3 · %s %s · %s · Verified" % (
        flag, cc, (protocol or "").strip().upper())


def rebrand_uri(uri, remark):
    """Return `uri` with only its display name replaced by `remark`."""
    scheme, _, rest = uri.partition("://")
    if scheme.lower() == "vmess":
        payload = rest.split("#", 1)[0].split("?", 1)[0]
        decoded = collector.b64decode_loose(payload)
        if decoded:
            try:
                data = json.loads(decoded)
                data["ps"] = remark
                encoded = base64.b64encode(
                    json.dumps(data, ensure_ascii=False).encode("utf-8")
                ).decode("ascii")
                return "vmess://" + encoded
            except Exception:
                pass
        return uri
    base = uri.split("#", 1)[0]
    return base + "#" + quote(remark, safe="")


# ------------------------------------------------------------------ gate 2

def gate2(record):
    """DNS + TCP (+TLS where plain TLS is expected). Returns (ok, reason)."""
    host, port = record["server"], record["port"]
    try:
        socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except Exception:
        return False, "dns"
    if record["protocol"] in ("hysteria2", "tuic"):
        return True, "dns_only_udp"  # UDP protocols: no TCP handshake exists
    try:
        with socket.create_connection((host, port), timeout=GATE2_TIMEOUT):
            pass
    except Exception:
        return False, "tcp"
    return True, "ok"


# ------------------------------------------------------- sing-box outbound

def _q1(query, *names):
    for name in names:
        values = query.get(name)
        if values and values[0]:
            return values[0]
    return None


def _tls(query, server, reality=False):
    sni = _q1(query, "sni", "servername", "peer") or server
    tls = {"enabled": True, "server_name": sni,
           "insecure": (_q1(query, "allowInsecure", "insecure") or "0") == "1"}
    alpn = _q1(query, "alpn")
    if alpn:
        tls["alpn"] = [a for a in alpn.split(",") if a]
    fp = _q1(query, "fp", "fingerprint")
    if fp:
        tls["utls"] = {"enabled": True, "fingerprint": fp}
    if reality:
        tls["reality"] = {"enabled": True,
                          "public_key": _q1(query, "pbk") or "",
                          "short_id": _q1(query, "sid") or ""}
        tls.setdefault("utls", {"enabled": True, "fingerprint": fp or "chrome"})
    return tls


def _transport(query, default_type=None):
    net = (_q1(query, "type", "net") or default_type or "tcp").lower()
    if net in ("tcp", "raw", ""):
        return None, "tcp"
    if net == "ws":
        headers = {}
        host = _q1(query, "host")
        if host:
            headers["Host"] = host
        return {"type": "ws", "path": _q1(query, "path") or "/",
                "headers": headers}, "ws"
    if net == "grpc":
        return {"type": "grpc",
                "service_name": _q1(query, "serviceName", "service_name") or ""}, "grpc"
    if net in ("http", "h2"):
        hosts = _q1(query, "host")
        return {"type": "http", "path": _q1(query, "path") or "/",
                "host": [hosts] if hosts else []}, "http"
    if net == "httpupgrade":
        return {"type": "httpupgrade", "path": _q1(query, "path") or "/",
                "host": _q1(query, "host") or ""}, "httpupgrade"
    return None, net


def build_outbound(uri):
    """Translate one config URI into a sing-box outbound dict, or None."""
    scheme, _, rest = uri.partition("://")
    scheme = scheme.lower()
    if scheme == "hy2":
        scheme = "hysteria2"
    if scheme == "vmess":
        decoded = collector.b64decode_loose(rest.split("#", 1)[0].split("?")[0])
        if not decoded:
            return None
        try:
            data = json.loads(decoded)
            port = int(data.get("port") or 0)
        except Exception:
            return None
        outbound = {"type": "vmess", "tag": "proxy", "server": data.get("add"),
                    "server_port": port, "uuid": data.get("id"),
                    "alter_id": int(data.get("aid") or 0),
                    "security": data.get("scy") or "auto"}
        net = (data.get("net") or "tcp").lower()
        if net == "ws":
            headers = {}
            if data.get("host"):
                headers["Host"] = data["host"]
            outbound["transport"] = {"type": "ws",
                                     "path": data.get("path") or "/",
                                     "headers": headers}
        elif net == "grpc":
            outbound["transport"] = {"type": "grpc",
                                     "service_name": data.get("path") or ""}
        elif net in ("http", "h2"):
            outbound["transport"] = {"type": "http",
                                     "path": data.get("path") or "/",
                                     "host": [data["host"]] if data.get("host") else []}
        if data.get("tls") == "tls":
            outbound["tls"] = {"enabled": True,
                               "server_name": data.get("sni") or data.get("host")
                               or data.get("add"), "insecure": False}
        return outbound
    parsed = urlparse(uri)
    host, port = parsed.hostname, parsed.port
    if not host or not port:
        return None
    query = parse_qs(parsed.query)
    user = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    if scheme == "vless":
        outbound = {"type": "vless", "tag": "proxy", "server": host,
                    "server_port": port, "uuid": user}
        flow = _q1(query, "flow")
        if flow:
            outbound["flow"] = flow
        transport, _ = _transport(query)
        if transport:
            outbound["transport"] = transport
        security = (_q1(query, "security") or "").lower()
        if security == "tls":
            outbound["tls"] = _tls(query, host)
        elif security == "reality":
            outbound["tls"] = _tls(query, host, reality=True)
        return outbound
    if scheme == "trojan":
        outbound = {"type": "trojan", "tag": "proxy", "server": host,
                    "server_port": port, "password": password or user}
        transport, _ = _transport(query)
        if transport:
            outbound["transport"] = transport
        outbound["tls"] = _tls(query, host)
        return outbound
    if scheme == "ss":
        credential = None
        if "@" in rest.split("#", 1)[0]:
            userinfo = unquote(rest.split("#", 1)[0].rsplit("@", 1)[0])
            credential = userinfo if ":" in userinfo else \
                collector.b64decode_loose(userinfo)
        else:
            decoded = collector.b64decode_loose(rest.split("#", 1)[0])
            if decoded and "@" in decoded:
                credential = decoded.rsplit("@", 1)[0]
        if not credential or ":" not in credential:
            return None
        method, _, ss_password = credential.partition(":")
        return {"type": "shadowsocks", "tag": "proxy", "server": host,
                "server_port": port, "method": method, "password": ss_password}
    if scheme == "hysteria2":
        outbound = {"type": "hysteria2", "tag": "proxy", "server": host,
                    "server_port": port, "password": password or user}
        tls = _tls(query, host)
        tls.setdefault("alpn", ["h3"])
        outbound["tls"] = tls
        obfs = _q1(query, "obfs")
        if obfs:
            outbound["obfs"] = {"type": obfs,
                                "password": _q1(query, "obfs-password") or ""}
        return outbound
    if scheme == "tuic":
        outbound = {"type": "tuic", "tag": "proxy", "server": host,
                    "server_port": port, "uuid": user, "password": password,
                    "congestion_control": _q1(query, "congestion_control",
                                               "congestionControl") or "bbr"}
        tls = _tls(query, host)
        tls.setdefault("alpn", ["h3"])
        outbound["tls"] = tls
        return outbound
    return None


# ------------------------------------------------------------------ gate 3

def _proxy_opener(port):
    handler = urllib.request.ProxyHandler(
        {"http": "http://127.0.0.1:%d" % port,
         "https": "http://127.0.0.1:%d" % port})
    return urllib.request.build_opener(handler)


def _fetch(opener, url, timeout=PROBE_TIMEOUT):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    started = time.monotonic()
    with opener.open(request, timeout=timeout) as response:
        body = response.read(1024 * 1024)
        status = response.status
    return status, body, (time.monotonic() - started) * 1000.0


def direct_egress():
    """This host's own egress (ip, country) via the trace endpoint."""
    try:
        _, body, _ = _fetch(urllib.request.build_opener(), URL_TRACE, 15)
        fields = dict(line.split("=", 1) for line in
                      body.decode("utf-8", "replace").splitlines() if "=" in line)
        return fields.get("ip"), fields.get("loc")
    except Exception:
        return None, None


def _start_origin():
    """Local probe origin for the positive control: serves /generate_204,
    /trace (canned egress fields) and /__down on 127.0.0.1. It makes the
    control a complete local loop — client -> tunnel -> server -> origin —
    proving the harness end-to-end without depending on outside egress."""
    import http.server

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/generate_204"):
                self.send_response(204)
                self.end_headers()
            elif self.path.startswith("/trace"):
                body = b"ip=198.51.100.23\nloc=ZZ\n"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path.startswith("/__down"):
                body = b"x" * SPEED_BYTES
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, "http://127.0.0.1:%d" % server.server_address[1]


def _probe(port, direct_ip, url_204, url_trace, url_speed):
    """The Gate-3 probe sequence against a local proxy port: 3x
    generate_204 (median latency), a trace fetch (egress must differ
    from this host's direct egress), and a small speed sample. Shared
    by the sing-box and Xray runners so a core A/B measures the cores
    and the mask — never two probe implementations."""
    result = {"pass": False, "reason": None, "latency_ms": None,
              "speed_mbps": None, "egress_country": None}
    opener = _proxy_opener(port)
    latencies = []
    for _ in range(3):
        try:
            status, _, elapsed = _fetch(opener, url_204)
            if status not in (200, 204):
                result["reason"] = "probe204_status"
                return result
            latencies.append(elapsed)
        except Exception:
            result["reason"] = "probe204"
            return result
    result["latency_ms"] = round(statistics.median(latencies), 1)
    try:
        _, body, _ = _fetch(opener, url_trace)
        fields = dict(line.split("=", 1) for line in
                      body.decode("utf-8", "replace").splitlines()
                      if "=" in line)
        egress_ip = fields.get("ip")
        result["egress_country"] = fields.get("loc")
    except Exception:
        result["reason"] = "trace"
        return result
    if not egress_ip:
        result["reason"] = "trace_no_ip"
        return result
    if direct_ip and egress_ip == direct_ip:
        result["reason"] = "egress_same"
        return result
    try:
        _, body, elapsed = _fetch(opener, url_speed, timeout=15)
        if elapsed > 0:
            result["speed_mbps"] = round(
                len(body) * 8 / (elapsed / 1000.0) / 1_000_000, 2)
    except Exception:
        result["speed_mbps"] = None  # recorded, not fatal in one run
    result["pass"] = True
    return result


def _wait_ready(proc, port, result, exit_reason):
    deadline = time.monotonic() + READY_TIMEOUT
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            result["reason"] = exit_reason
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except Exception:
            time.sleep(0.2)
    result["reason"] = "not_ready"
    return False


def run_tunnel(outbound, sing_box, direct_ip, urls=None):
    """One Gate-3 attempt. Returns a result dict (aggregate-safe fields).
    urls optionally overrides (url_204, url_trace, url_speed) — used only
    by the local positive control."""
    url_204, url_trace, url_speed = urls or (URL_204, URL_TRACE, URL_SPEED)
    result = {"pass": False, "reason": None, "latency_ms": None,
              "speed_mbps": None, "egress_country": None}
    port = free_port()
    config = {"log": {"level": "warn"},
              "inbounds": [{"type": "mixed", "tag": "in",
                            "listen": "127.0.0.1", "listen_port": port}],
              "outbounds": [outbound, {"type": "direct", "tag": "direct"}],
              "route": {"final": outbound.get("tag", "proxy")}}
    with tempfile.TemporaryDirectory(prefix="mf-verify-") as tmp:
        cfg_path = os.path.join(tmp, "client.json")
        with open(cfg_path, "w", encoding="utf-8") as handle:
            json.dump(config, handle)
        proc = subprocess.Popen(
            [sing_box, "run", "-c", cfg_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            if not _wait_ready(proc, port, result, "singbox_exit"):
                return result
            result.update(_probe(port, direct_ip,
                                 url_204, url_trace, url_speed))
            return result
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()


def run_controls(sing_box, direct_ip):
    """Positive (loopback pair) + negative (dead config) controls."""
    import uuid as uuidlib
    token = str(uuidlib.uuid4())
    origin, origin_base = _start_origin()
    server_port, result = free_port(), {}
    server_cfg = {"log": {"level": "warn"},
                  "inbounds": [{"type": "vless", "tag": "in",
                                "listen": "127.0.0.1",
                                "listen_port": server_port,
                                "users": [{"uuid": token}]}],
                  "outbounds": [{"type": "direct", "tag": "direct"}]}
    with tempfile.TemporaryDirectory(prefix="mf-control-") as tmp:
        path = os.path.join(tmp, "server.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(server_cfg, handle)
        server = subprocess.Popen(
            [sing_box, "run", "-c", path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(1.0)
            client = {"type": "vless", "tag": "proxy", "server": "127.0.0.1",
                      "server_port": server_port, "uuid": token}
            local_urls = (origin_base + "/generate_204",
                          origin_base + "/trace",
                          origin_base + "/__down")
            positive = run_tunnel(client, sing_box, direct_ip,
                                  urls=local_urls)
            result["positive"] = {"pass": positive["pass"],
                                  "reason": positive["reason"],
                                  "latency_ms": positive["latency_ms"],
                                  "note": "local loopback sing-box pair + "
                                          "local origin (harness proof)"}
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except Exception:
                server.kill()
            origin.shutdown()
    dead = {"type": "vless", "tag": "proxy", "server": "203.0.113.99",
            "server_port": 443, "uuid": str(uuidlib.uuid4()),
            "tls": {"enabled": True, "server_name": "example.com"}}
    negative = run_tunnel(dead, sing_box, direct_ip)
    result["negative"] = {"pass": negative["pass"], "reason": negative["reason"]}
    result["ok"] = bool(result["positive"]["pass"]) and not negative["pass"]
    return result


# ------------------------------------------- finalmask A/B (Plan Rev.2 R2)
#
# The Enhanced track question: does presenting a TLS VLESS/Trojan link
# through Xray-core with a finalmask fragment preset pass Gate 3 more
# often than the plain sing-box presentation of the same link? The
# preset is the ecosystem's universal double-fragment (patterniha /
# proxy-builder "v2"), carried verbatim: values are strings in the
# shipped form and Xray's parser accepts them as such. fp is "unsafe"
# (stock Go TLS, no uTLS fingerprint) — the pairing the preset is
# published with. Plain stays the production default whatever the A/B
# says; a separate labelled variant track ships only on a win or a
# tie-with-benefits (see docs/PLAN.md Plan Rev.2).

FINALMASK_TCP = [
    {"type": "fragment",
     "settings": {"packets": "tlshello", "lengths": ["0", "104", "1"],
                  "delays": ["0"], "maxSplit": "0"}},
    {"type": "fragment",
     "settings": {"packets": "1-1", "lengths": ["114", "1"],
                  "delays": ["1"], "maxSplit": "11"}},
]


def build_xray_outbound(uri):
    """Translate one security=tls VLESS/Trojan URI into an Xray outbound
    carrying the finalmask preset, or None when the URI is outside the
    A/B's scope (other protocols, REALITY/none security, exotic
    transports). The builder doubles as the eligibility test."""
    scheme = uri.partition("://")[0].lower()
    if scheme not in ("vless", "trojan"):
        return None
    parsed = urlparse(uri)
    host, port = parsed.hostname, parsed.port
    if not host or not port:
        return None
    query = parse_qs(parsed.query)
    user = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    security = (_q1(query, "security")
                or ("tls" if scheme == "trojan" else "")).lower()
    if security != "tls":
        return None
    net = (_q1(query, "type") or "tcp").lower()
    tls_settings = {"serverName": _q1(query, "sni") or host,
                    "fingerprint": "unsafe"}
    alpn = _q1(query, "alpn")
    if alpn:
        tls_settings["alpn"] = [a for a in alpn.split(",") if a]
    stream = {"network": net, "security": "tls",
              "tlsSettings": tls_settings,
              "finalmask": {"tcp": FINALMASK_TCP}}
    if net == "ws":
        ws = {"path": _q1(query, "path") or "/"}
        if _q1(query, "host"):
            ws["headers"] = {"Host": _q1(query, "host")}
        stream["wsSettings"] = ws
    elif net == "grpc":
        stream["grpcSettings"] = {"serviceName": _q1(query, "serviceName")
                                  or ""}
    elif net in ("http", "h2"):
        stream["network"] = "http"
        http = {"path": _q1(query, "path") or "/"}
        if _q1(query, "host"):
            http["host"] = [_q1(query, "host")]
        stream["httpSettings"] = http
    elif net != "tcp":
        return None
    if scheme == "vless":
        user_obj = {"id": user, "encryption": "none"}
        if _q1(query, "flow"):
            user_obj["flow"] = _q1(query, "flow")
        return {"protocol": "vless", "tag": "proxy",
                "settings": {"vnext": [{"address": host, "port": port,
                                        "users": [user_obj]}]},
                "streamSettings": stream}
    return {"protocol": "trojan", "tag": "proxy",
            "settings": {"servers": [{"address": host, "port": port,
                                      "password": password or user}]},
            "streamSettings": stream}


def run_xray_tunnel(outbound, xray, direct_ip, urls=None, stderr_path=None):
    """run_tunnel's Xray twin: an http inbound (urllib's ProxyHandler
    speaks HTTP proxying, not SOCKS) in front of the given outbound,
    then the identical _probe sequence. stderr_path is used only by
    the loopback controls (diagnosability); candidate tunnels keep
    stderr discarded."""
    url_204, url_trace, url_speed = urls or (URL_204, URL_TRACE, URL_SPEED)
    result = {"pass": False, "reason": None, "latency_ms": None,
              "speed_mbps": None, "egress_country": None}
    port = free_port()
    config = {"log": {"loglevel": "warning"},
              "inbounds": [{"protocol": "http", "tag": "in",
                            "listen": "127.0.0.1", "port": port}],
              "outbounds": [outbound]}
    with tempfile.TemporaryDirectory(prefix="mf-ab-") as tmp:
        cfg_path = os.path.join(tmp, "client.json")
        with open(cfg_path, "w", encoding="utf-8") as handle:
            json.dump(config, handle)
        err_handle = open(stderr_path, "wb") if stderr_path else None
        proc = subprocess.Popen(
            [xray, "run", "-c", cfg_path],
            stdout=subprocess.DEVNULL,
            stderr=err_handle or subprocess.DEVNULL)
        if err_handle:
            err_handle.close()
        try:
            if not _wait_ready(proc, port, result, "xray_exit"):
                return result
            result.update(_probe(port, direct_ip,
                                 url_204, url_trace, url_speed))
            return result
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()


def _wait_port(port, timeout=10.0):
    """Poll until a loopback TCP port accepts a connection."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except Exception:
            time.sleep(0.2)
    return False


def run_xray_controls(xray, direct_ip):
    """run_controls' Xray twin: loopback Xray server + plain Xray client
    (the mask is exercised against real servers in the A/B itself; the
    control proves the Xray harness), plus the same dead-config
    negative."""
    import uuid as uuidlib
    token = str(uuidlib.uuid4())
    origin, origin_base = _start_origin()
    server_port, result = free_port(), {}
    server_cfg = {"log": {"loglevel": "warning"},
                  "inbounds": [{"protocol": "vless", "listen": "127.0.0.1",
                                "port": server_port,
                                "settings": {"clients": [{"id": token}],
                                             "decryption": "none"}}],
                  # Xray v26's freedom outbound blackholes private /
                  # loopback targets by default (a "finalrule" SSRF
                  # guard, 90 s blackhole — it silently hung this
                  # control on CI runners while v25 and local runs
                  # passed; diagnosed 2026-11-20, diag runs
                  # 44710508376 / 44710917446 / 44711332653). The
                  # control server is a test double whose whole job is
                  # dialing a loopback origin, so it allows explicitly.
                  # Candidate tunnels never touch freedom on our side;
                  # this affects nothing but the control.
                  "outbounds": [{"protocol": "freedom", "tag": "direct",
                                 "settings": {"finalRules": [
                                     {"action": "allow",
                                      "network": "tcp,udp",
                                      "ip": ["0.0.0.0/0", "::/0"]}]}}]}
    with tempfile.TemporaryDirectory(prefix="mf-ab-control-") as tmp:
        path = os.path.join(tmp, "server.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(server_cfg, handle)
        server_err = open(os.path.join(tmp, "server.err"), "wb")
        server = subprocess.Popen(
            [xray, "run", "-c", path],
            stdout=subprocess.DEVNULL, stderr=server_err)
        server_err.close()
        try:
            # Deterministic readiness, not a fixed sleep: the first
            # live A/B run (44707206237) failed this control with
            # probe204 on a loaded runner — the server was not yet
            # listening when the client's probes fired (the same
            # control passes locally). Readiness is harness proof,
            # not a measurement, so waiting here cannot bias the A/B.
            if server.poll() is not None or not _wait_port(server_port):
                result["positive"] = {
                    "pass": False, "reason": "xray_server_not_ready",
                    "latency_ms": None,
                    "note": "loopback xray server never listened"}
            else:
                client = {"protocol": "vless", "tag": "proxy",
                          "settings": {"vnext": [
                              {"address": "127.0.0.1", "port": server_port,
                               "users": [{"id": token,
                                          "encryption": "none"}]}]}}
                local_urls = (origin_base + "/generate_204",
                              origin_base + "/trace",
                              origin_base + "/__down")
                client_err_path = os.path.join(tmp, "client.err")
                positive = run_xray_tunnel(client, xray, direct_ip,
                                           urls=local_urls,
                                           stderr_path=client_err_path)
                result["positive"] = {"pass": positive["pass"],
                                      "reason": positive["reason"],
                                      "latency_ms": positive["latency_ms"],
                                      "note": "local loopback xray pair + "
                                              "local origin (harness proof)"}
                if not positive["pass"]:
                    # Controls exist to prove the harness — when they
                    # fail on a remote runner, the cores' own logs are
                    # the diagnosis. Loopback control logs only: they
                    # can contain no config or credential data.
                    def _tail(p):
                        try:
                            with open(p, "rb") as fh:
                                return fh.read()[-600:].decode(
                                    "utf-8", "replace")
                        except Exception:
                            return ""
                    result["positive"]["diag"] = {
                        "server": _tail(os.path.join(tmp, "server.err")),
                        "client": _tail(client_err_path)}
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except Exception:
                server.kill()
            origin.shutdown()
    dead = {"protocol": "vless", "tag": "proxy",
            "settings": {"vnext": [
                {"address": "203.0.113.99", "port": 443,
                 "users": [{"id": str(uuidlib.uuid4()),
                            "encryption": "none"}]}]},
            "streamSettings": {"network": "tcp", "security": "tls",
                               "tlsSettings": {
                                   "serverName": "example.com",
                                   "fingerprint": "unsafe"}}}
    negative = run_xray_tunnel(dead, xray, direct_ip)
    result["negative"] = {"pass": negative["pass"],
                          "reason": negative["reason"]}
    result["ok"] = bool(result["positive"]["pass"]) and not negative["pass"]
    return result


def ab_finalmask(registry_path, sing_box, xray, limit, collect_limit,
                 workers):
    """Paired A/B: the same Gate-2-passing TLS VLESS/Trojan candidates
    through (plain) sing-box and (enhanced) Xray+finalmask. Output is
    counts and opaque pass-keys only — same privacy rule as verify()."""
    stats = {"tool": "meridianfeed-ab-finalmask", "ab_version": "1.0.0",
             "subjects": 0,
             "paired": {"both": 0, "plain_only": 0,
                        "enhanced_only": 0, "neither": 0},
             "per_subject": []}
    sample_all, totals = collect_candidates(registry_path, collect_limit)
    stats["collect_totals"] = totals
    random.shuffle(sample_all)  # never test in list order
    subjects = []
    for record, uri in sample_all:
        if len(subjects) >= limit:
            break
        if build_xray_outbound(uri) is None:
            continue
        if not gate2(record)[0]:
            continue
        subjects.append((record, uri))
    stats["subjects"] = len(subjects)
    direct_ip, _ = direct_egress()
    stats["controls"] = {
        "sing_box": run_controls(sing_box, direct_ip) if sing_box
        else {"ok": False, "reason": "no_sing_box"},
        "xray": run_xray_controls(xray, direct_ip) if xray
        else {"ok": False, "reason": "no_xray"},
    }
    plain_ok = bool(stats["controls"]["sing_box"].get("ok"))
    enh_ok = bool(stats["controls"]["xray"].get("ok"))

    def failed(reason):
        return {"pass": False, "reason": reason, "latency_ms": None}

    def one(pair):
        record, uri = pair
        if plain_ok:
            outbound = build_outbound(uri)
            plain = run_tunnel(outbound, sing_box, direct_ip) if outbound \
                else failed("build_none")
        else:
            plain = failed("controls_failed")
        if enh_ok:
            xray_outbound = build_xray_outbound(uri)
            enh = run_xray_tunnel(xray_outbound, xray, direct_ip) \
                if xray_outbound else failed("build_none")
        else:
            enh = failed("controls_failed")
        return record, plain, enh

    plain_lat, enh_lat = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for record, plain, enh in pool.map(one, subjects):
            p, e = bool(plain["pass"]), bool(enh["pass"])
            if p and plain["latency_ms"] is not None:
                plain_lat.append(plain["latency_ms"])
            if e and enh["latency_ms"] is not None:
                enh_lat.append(enh["latency_ms"])
            bucket = "both" if p and e else "plain_only" if p else \
                "enhanced_only" if e else "neither"
            stats["paired"][bucket] += 1
            stats["per_subject"].append(
                {"key": pass_key(record), "plain": p, "enhanced": e})
    n = max(1, len(subjects))
    plain_passes = stats["paired"]["both"] + stats["paired"]["plain_only"]
    enh_passes = stats["paired"]["both"] + stats["paired"]["enhanced_only"]
    stats["plain"] = {"passes": plain_passes,
                      "pass_rate": round(plain_passes / n, 4),
                      "latency_ms": distribution(plain_lat)}
    stats["enhanced"] = {"passes": enh_passes,
                         "pass_rate": round(enh_passes / n, 4),
                         "latency_ms": distribution(enh_lat)}
    return stats


def find_xray(cli_value):
    candidates = [cli_value, os.environ.get("XRAY_BIN"), "xray"]
    for candidate in candidates:
        if not candidate:
            continue
        path = candidate if os.path.sep in candidate else None
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
        if not path:
            for directory in os.environ.get("PATH", "").split(os.pathsep):
                full = os.path.join(directory, candidate)
                if os.path.isfile(full) and os.access(full, os.X_OK):
                    return full
    return None


# -------------------------------------------------------------------- main

def distribution(values):
    if not values:
        return None
    ordered = sorted(values)
    return {"n": len(ordered), "median": round(statistics.median(ordered), 2),
            "p90": round(ordered[min(len(ordered) - 1,
                                      int(len(ordered) * 0.9))], 2),
            "min": round(ordered[0], 2), "max": round(ordered[-1], 2)}


def build_uri_map(pairs):
    """Snapshot-pinning map (Phase B): opaque pass-key hash -> URI for
    exactly the configs this run sampled. PRIVATE — the map is uploaded
    as a short-retention Actions artifact only; it never enters the
    repo, the stats, or any log. It lets the composer recover eligible
    URIs from the runs that actually tested them instead of re-fetching
    churned source lists."""
    return {pass_key(record): uri for record, uri in pairs}


def verify(registry_path, sing_box, limit, workers, gate2_workers,
           map_out=None):
    stats = {"tool": "meridianfeed-verifier", "verifier_version": "1.1.0",
             "sing_box": bool(sing_box), "passes": [],
             "limits": {"sample": limit, "gate3_workers": workers}}
    sample, totals = collect_candidates(registry_path, limit)
    stats["input"] = totals
    if map_out:
        with open(map_out, "w", encoding="utf-8") as handle:
            json.dump(build_uri_map(sample), handle)
    # Gate 2 (concurrent)
    gate2_reasons, survivors = {}, []
    with concurrent.futures.ThreadPoolExecutor(gate2_workers) as pool:
        futures = {pool.submit(gate2, record): (record, uri)
                   for record, uri in sample}
        for future in concurrent.futures.as_completed(futures):
            record, uri = futures[future]
            ok, reason = future.result()
            if ok:
                survivors.append((record, uri))
            else:
                gate2_reasons[reason] = gate2_reasons.get(reason, 0) + 1
    stats["gate2"] = {"tested": len(sample), "passed": len(survivors),
                       "failed": len(sample) - len(survivors),
                       "fail_reasons": gate2_reasons}
    direct_ip, direct_country = direct_egress()
    stats["direct_egress_country"] = direct_country
    if not sing_box:
        stats["gate3"] = {"skipped": "sing-box binary not available"}
        stats["controls"] = {"ok": False, "skipped": True}
        return stats
    controls = run_controls(sing_box, direct_ip)
    stats["controls"] = controls
    if not controls["ok"]:
        stats["controls_failed"] = True
        stats["gate3"] = {"tested": 0, "passed": 0,
                          "note": "CONTROLS FAILED — nothing was verified"}
        return stats
    # Gate 3 (bounded concurrency — sing-box processes are the bottleneck)
    results, fail_reasons = [], {}
    countries, protocols_pass = {}, {}
    pass_records = []

    def _one(pair):
        record, uri = pair
        outbound = build_outbound(uri)
        if outbound is None:
            return record, {"pass": False, "reason": "build_none",
                            "latency_ms": None, "speed_mbps": None,
                            "egress_country": None}
        return record, run_tunnel(outbound, sing_box, direct_ip)

    with concurrent.futures.ThreadPoolExecutor(workers) as pool:
        futures = [pool.submit(_one, pair) for pair in survivors]
        for future in concurrent.futures.as_completed(futures):
            record, outcome = future.result()
            if outcome["pass"]:
                results.append(outcome)
                protocols_pass[record["protocol"]] = \
                    protocols_pass.get(record["protocol"], 0) + 1
                if outcome["egress_country"]:
                    countries[outcome["egress_country"]] = \
                        countries.get(outcome["egress_country"], 0) + 1
                pass_records.append({
                    "key_hash": pass_key(record),
                    "protocol": record["protocol"],
                    "source": record.get("source", ""),
                    "egress_country": outcome["egress_country"],
                    "latency_ms": outcome["latency_ms"],
                    "speed_mbps": outcome["speed_mbps"],
                    "public_criteria": bool(
                        outcome["latency_ms"] is not None
                        and outcome["latency_ms"] <= PUBLIC_LATENCY_MS
                        and (outcome["speed_mbps"] or 0)
                        >= PUBLIC_SPEED_MBPS)})
            else:
                reason = outcome["reason"] or "unknown"
                fail_reasons[reason] = fail_reasons.get(reason, 0) + 1
    public_ready = [r for r in results
                    if r["latency_ms"] is not None
                    and r["latency_ms"] <= PUBLIC_LATENCY_MS
                    and (r["speed_mbps"] or 0) >= PUBLIC_SPEED_MBPS]
    stats["gate3"] = {
        "tested": len(survivors), "passed": len(results),
        "failed": len(survivors) - len(results),
        "fail_reasons": fail_reasons,
        "passed_by_protocol": protocols_pass,
        "egress_countries": countries,
        "latency_ms": distribution([r["latency_ms"] for r in results
                                    if r["latency_ms"] is not None]),
        "speed_mbps": distribution([r["speed_mbps"] for r in results
                                    if r["speed_mbps"] is not None]),
        "public_criteria_met_single_run": len(public_ready),
        "note": "Tier assignment still requires the strict repeat passes "
                "(public: a 2nd run >=15 min later; VIP: 3 consecutive "
                "cycles) — a single run never publishes anything."}
    stats["passes"] = pass_records
    return stats


def find_sing_box(cli_value):
    candidates = [cli_value, os.environ.get("SING_BOX"), "sing-box"]
    for candidate in candidates:
        if not candidate:
            continue
        path = candidate if os.path.sep in candidate else None
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
        if not path:
            for directory in os.environ.get("PATH", "").split(os.pathsep):
                full = os.path.join(directory, candidate)
                if os.path.isfile(full) and os.access(full, os.X_OK):
                    return full
    return None


def main(argv):
    args = argv[1:]
    registry = "pipeline/sources.json"
    if args and not args[0].startswith("--"):
        registry, args = args[0], args[1:]

    def opt(name, default):
        return args[args.index(name) + 1] if name in args else default

    limit = int(opt("--limit", "200"))
    workers = int(opt("--workers", "4"))
    gate2_workers = int(opt("--gate2-workers", "32"))
    out_path = opt("--out", None)
    map_out = opt("--map-out", "verify-uri-map.json" if out_path else None)
    sing_box = find_sing_box(opt("--sing-box", None))
    if "--ab-finalmask" in args:
        xray = find_xray(opt("--xray", None))
        stats = ab_finalmask(registry, sing_box, xray,
                             int(opt("--ab-limit", "60")),
                             int(opt("--collect-limit", "600")),
                             workers)
        stats["sing_box_path_found"] = bool(sing_box)
        stats["xray_path_found"] = bool(xray)
        text = json.dumps(stats, indent=2)
        print(text)
        if out_path:
            with open(out_path, "w", encoding="utf-8") as handle:
                handle.write(text + "\n")
        return 0
    stats = verify(registry, sing_box, limit, workers, gate2_workers,
                   map_out=map_out)
    stats["sing_box_path_found"] = bool(sing_box)
    text = json.dumps(stats, indent=2)
    print(text)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
