#!/usr/bin/env python3
"""MASQUE / WARP endpoint hunt (Plan Rev.2 R5.1).

Lifts the curated MASQUE Scout data (mirarr-app/network-checker
v1.7.3, GPL-3.0 — data only) from data/masque_warp.json and probes
the endpoints for liveness from the runner: seeds x ports, plus a
deterministic sample of 5 hosts per MASQUE CIDR on 443.

SCOPE HONESTY: this is a TCP/TLS liveness screen, NOT a MASQUE
protocol proof. MASQUE speaks QUIC/HTTP3; a TCP connect (and, on
443, a TLS handshake with SNI cloudflareaccess.com) only shows the
endpoint answers on that port. An endpoint that drops TCP but serves
MASQUE over UDP reads as dead here. The hunt's job is a cheap
baseline — which curated endpoints are even reachable — and its
numbers live in the verifier run stats under "hunt". It never feeds
the pools: MASQUE endpoints are not V2Ray configs.

Stdlib only. Never fails its caller: hunt_masque() returns an error
dict instead of raising.
"""
import concurrent.futures
import ipaddress
import json
import os
import socket
import ssl
import statistics
import time

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "data", "masque_warp.json")
SAMPLE_PER_CIDR = 5
DEFAULT_TIMEOUT = 5.0


def load_masque_data(path=DATA_PATH):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def hunt_targets(data, per_cidr=SAMPLE_PER_CIDR):
    """Deterministic endpoint list: (ip, port) pairs. Seeds on every
    MASQUE port, plus the first `per_cidr` host addresses of each
    MASQUE CIDR on 443 (the network-checker sampler's offsets 1..n)."""
    targets = []
    for seed in data.get("seeds_v4", []):
        for port in data.get("ports", [443]):
            targets.append((seed, int(port)))
    for cidr in data.get("cidrs_v4", []):
        try:
            net = ipaddress.ip_network(cidr)
        except ValueError:
            continue
        for host in list(net.hosts())[:per_cidr]:
            targets.append((str(host), 443))
    # Seeds are the first hosts of their own CIDRs — probe each
    # endpoint once.
    return list(dict.fromkeys(targets))


def probe(ip, port, sni=None, timeout=DEFAULT_TIMEOUT):
    """TCP connect; on 443 also a TLS handshake with the given SNI.
    Returns (tcp_ok, tls_ok, latency_ms). tls_ok is None when no TLS
    probe applies (non-443 port)."""
    start = time.monotonic()
    try:
        sock = socket.create_connection((ip, port), timeout=timeout)
    except Exception:
        return False, None, None
    latency = (time.monotonic() - start) * 1000.0
    if port != 443 or not sni:
        sock.close()
        return True, None, latency
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        wrapped = ctx.wrap_socket(sock, server_hostname=sni)
        wrapped.close()
        return True, True, latency
    except Exception:
        try:
            sock.close()
        except Exception:
            pass
        return True, False, latency


def hunt_masque(data=None, workers=8, timeout=DEFAULT_TIMEOUT):
    """Probe the MASQUE endpoint list; returns a stats dict (counts
    and latencies only — no credentials, no config material)."""
    try:
        data = data or load_masque_data()
        targets = hunt_targets(data)
    except Exception as exc:  # noqa: BLE001 - a hunt failure is data
        return {"error": "%s: %s" % (type(exc).__name__, exc),
                "tested": 0, "reachable": 0}
    sni = data.get("sni_default", "cloudflareaccess.com")
    results = []
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=workers) as pool:
        futures = [pool.submit(probe, ip, port, sni, timeout)
                   for ip, port in targets]
        for (ip, port), future in zip(targets, futures):
            try:
                tcp_ok, tls_ok, latency = future.result()
            except Exception:
                tcp_ok, tls_ok, latency = False, None, None
            results.append({"ip": ip, "port": port, "tcp": tcp_ok,
                            "tls": tls_ok, "latency_ms": latency})
    reachable = [r for r in results if r["tcp"]]
    tls_ok = [r for r in reachable if r["tls"] is True]
    lat = [r["latency_ms"] for r in reachable
           if r["latency_ms"] is not None]
    by_port = {}
    for r in reachable:
        by_port[str(r["port"])] = by_port.get(str(r["port"]), 0) + 1
    stats = {"tested": len(results), "reachable": len(reachable),
             "tls_ok_443": len(tls_ok),
             "by_port_reachable": by_port,
             "latency_ms": _distribution(lat),
             "scope": "TCP/TLS liveness only — not a MASQUE protocol proof"}
    return stats


def _distribution(values):
    if not values:
        return None
    ordered = sorted(values)
    return {"n": len(ordered),
            "median": round(statistics.median(ordered), 2),
            "p90": round(ordered[min(len(ordered) - 1,
                                      int(len(ordered) * 0.9))], 2),
            "min": round(ordered[0], 2),
            "max": round(ordered[-1], 2)}


if __name__ == "__main__":
    print(json.dumps(hunt_masque(), indent=2))
