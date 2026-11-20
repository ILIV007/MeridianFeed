#!/usr/bin/env python3
"""Gate-IR — Iran-reachability stage (Plan Rev.2 R6.1), stdlib only.

Gate 3 verifies tunnels from US runners; it cannot see Iranian ISP
filtering. Gate-IR adds an Iran vantage for the keys that matter —
Gate-3 passes meeting the VIP floors (the composer's Tier-1 and
Tier-3 candidate material) — by asking external probe networks to
TCP-connect to each candidate's endpoint (host:port) from Iran:

- Primary: check-host.net, Tehran node (ir1.node.check-host.net).
  Async API: create a check, poll for the result.
- Second opinion: Globalping probes located in Iran (HTTPS probe —
  a completed TLS handshake + any HTTP response counts as reachable).

Verdict discipline (fail-open-to-neutral, always):
- A reachable verdict needs one success.
- An UNREACHABLE verdict needs confirmation: two agreeing failures
  (a second check-host attempt, or a Globalping failure agreeing
  with the first). A single node hiccup never condemns a config.
- Anything inconclusive is None (neutral), never False.

Controls run first, with the same discipline as Gate 3: a positive
control (Cloudflare anycast 1.1.1.1:443 — must be reachable from the
Tehran node) and a negative control (192.0.2.1, TEST-NET-1 reserved —
must fail). If the controls do not behave, the whole stage degrades
to NEUTRAL for every key ("neutral_controls") — a broken checker can
never mass-exclude the pool.

Scope honesty: this measures TCP/TLS reachability from a Tehran
datacenter node. It catches IP blocks, SNI blocks and RST injection.
It does NOT prove a tunnel works end-to-end from a residential ISP,
and UDP protocols (Hysteria2) are out of its reach entirely — those
stay governed by field feedback. Both APIs are used keyless at this
volume; all calls happen on the Actions runner; verdicts are cached
per host:port within a run and total added runtime is bounded.

Field iteration 3 (2026-11-20) adds an Iran-side PING latency per
endpoint (annotate_with_latency): wolf's field test #6 showed the
US-runner latency says nothing about speed from Iran — the working
VIP members measured 574–987 ms real delay from Iranian mobile at
peak hour. The ping RTT from an Iranian probe is the composer's
ranking signal within the field-verified/front-class order. It is a
ranking signal ONLY: missing latency is neutral (never a penalty,
never an exclusion), and the ping stage carries no controls of its
own — it cannot change any reachability verdict.
"""
import json
import os
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

TEHRAN_NODE = "ir1.node.check-host.net"
CHECK_HOST_BASE = "https://check-host.net"
GLOBALPING_BASE = "https://api.globalping.io/v1"
USER_AGENT = "MeridianFeed-GateIR/1.0 (+https://github.com/ILIV007/MeridianFeed)"

POSITIVE_CONTROL = ("1.1.1.1", 443)      # Cloudflare anycast, must pass
NEGATIVE_CONTROL = ("192.0.2.1", 443)    # TEST-NET-1 reserved, must fail
# Globalping rejects unroutable targets at creation (HTTP 400,
# verified live 2026-11-20), so its must-fail control is a dead port
# on the same anycast host instead — same intent, creatable target.
GP_NEGATIVE_CONTROL = ("1.1.1.1", 59999)

# The composer's VIP floors (compose.py VIP_LAT / VIP_SPD): Gate-IR
# only spends API calls on passes that meet them.
VIP_LATENCY_MS = 500.0
VIP_SPEED_MBPS = 2.5

POLL_DEADLINE_S = 30.0
GP_POLL_DEADLINE_S = 40.0
DEFAULT_BUDGET_S = 170.0
DEFAULT_WORKERS = 4
PACE_S = 0.3

_pace_lock = threading.Lock()
_pace_last = [0.0]


def _pace():
    with _pace_lock:
        wait = _pace_last[0] + PACE_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _pace_last[0] = time.monotonic()


def _http_json(url, data=None, timeout=15.0):
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _hostport(host, port):
    if ":" in host and not host.startswith("["):
        return "[%s]:%d" % (host, port)
    return "%s:%d" % (host, port)


# ------------------------------------------------------------- check-host

def probe_check_host(host, port, node=TEHRAN_NODE,
                     deadline=POLL_DEADLINE_S):
    """One check-host TCP check from the Tehran node.
    Returns True (connected), False (connect failed), None (the API
    or the node could not produce a verdict in time)."""
    try:
        _pace()
        created = _http_json("%s/check-tcp?host=%s&node=%s" % (
            CHECK_HOST_BASE,
            urllib.request.quote(_hostport(host, port), safe=""),
            node))
        request_id = created.get("request_id")
        if not request_id:
            return None
    except Exception:
        return None
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        time.sleep(2.0)
        try:
            result = _http_json("%s/check-result/%s"
                                % (CHECK_HOST_BASE, request_id))
        except Exception:
            continue
        entry = result.get(node) if isinstance(result, dict) else None
        if not entry:
            continue  # node has not reported yet
        attempts = entry[0] if isinstance(entry, list) and entry else []
        for attempt in attempts if isinstance(attempts, list) else []:
            if isinstance(attempt, dict) and "time" in attempt:
                return True
            if isinstance(attempt, dict) and "error" in attempt:
                return False
        return None  # reported in an unexpected shape: inconclusive
    return None


# ------------------------------------------------------------- globalping

def probe_globalping(host, port, deadline=GP_POLL_DEADLINE_S):
    """One Globalping HTTPS measurement from an Iran-located probe.
    A completed TLS handshake with any HTTP status counts as
    reachable (the endpoint's application layer is not the question).
    Returns True / False / None (no IR probe, API error, timeout)."""
    payload = {"type": "http", "target": host,
               "locations": [{"country": "IR", "limit": 1}],
               "measurementOptions": {
                   "port": int(port), "protocol": "https",
                   "request": {"path": "/", "method": "GET"}}}
    try:
        created = _http_json(GLOBALPING_BASE + "/measurements",
                             data=payload)
        measurement_id = created.get("id")
        if not measurement_id:
            return None
    except Exception:
        return None
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        time.sleep(2.5)
        try:
            result = _http_json("%s/measurements/%s"
                                % (GLOBALPING_BASE, measurement_id))
        except Exception:
            continue
        if result.get("status") not in ("finished", "failed"):
            continue
        results = result.get("results") or []
        if not results:
            return None
        probe_result = results[0].get("result") or {}
        if probe_result.get("statusCode") is not None:
            return True
        if probe_result.get("status") == "failed":
            return False
        return None
    return None


# ------------------------------------------------------- verdict logic

def endpoint_verdict(host, port, ch=probe_check_host, gp=probe_globalping):
    """Confirmed verdict for one endpoint. A False (unreachable)
    verdict requires two agreeing failures; a success at any point
    wins; anything else is None (neutral)."""
    first = ch(host, port)
    if first is True:
        return True
    if first is None:
        # check-host unavailable: Globalping may still prove
        # reachability, but its failure alone never condemns.
        return True if gp(host, port) is True else None
    # first is False — confirmation required before condemning.
    second = ch(host, port)
    if second is True:
        return True
    if second is False:
        return False
    opinion = gp(host, port)
    if opinion is False:
        return False
    if opinion is True:
        return True
    return None


LAST_CONTROLS = {"attempts": 0, "positive": None, "negative": None,
                 "via": "none"}


def controls_ok(ch=probe_check_host, gp=probe_globalping):
    """Positive control must be reachable from Tehran, negative must
    fail. Any other outcome means the checker itself is untrustworthy
    this run and the stage must go neutral. The pair is attempted
    twice: one transient API hiccup on a shared runner egress IP must
    not neutralise the whole stage (the first live cycle, run
    44721173582, went neutral_controls with no diagnosable trace —
    LAST_CONTROLS now records the verdicts into the run stats).

    If check-host never produces a verdict at all (API unavailable
    from the runner — live runs 44721173582 and 44723601784 both came
    back null/null on every attempt), the pair falls back to
    Globalping's Iran probes, the design's second opinion. A real
    check-host verdict failure (the Tehran node itself misbehaving)
    is never overridden this way."""
    LAST_CONTROLS.update({"attempts": 0, "positive": None,
                          "negative": None, "via": "none"})
    saw_verdict = False
    for _ in range(2):
        positive = ch(*POSITIVE_CONTROL)
        negative = ch(*NEGATIVE_CONTROL)
        LAST_CONTROLS.update({"attempts": LAST_CONTROLS["attempts"] + 1,
                              "positive": positive,
                              "negative": negative, "via": "check-host"})
        if positive is not None:
            saw_verdict = True
        if positive is True and negative is False:
            return True
    if saw_verdict:
        return False
    positive = gp(*POSITIVE_CONTROL)
    negative = gp(*GP_NEGATIVE_CONTROL)
    LAST_CONTROLS.update({"positive": positive, "negative": negative,
                          "via": "globalping"})
    return positive is True and negative is False


def annotate(targets, budget_s=DEFAULT_BUDGET_S, workers=DEFAULT_WORKERS,
             ch=probe_check_host, gp=probe_globalping, controls=None):
    """Annotate {key: (host, port)} with Iran-reachability verdicts.

    Returns (verdicts, stage, counts): verdicts maps every input key
    to True / False / None; stage is "ok", "neutral_controls" or
    "neutral_error"; counts summarises the unique endpoints checked.
    Verdicts are cached per host:port — several configs can share an
    endpoint. Work is bounded by budget_s; keys not reached within
    the budget stay None (neutral)."""
    verdicts = {key: None for key in targets}
    counts = {"endpoints": 0, "reachable": 0, "unreachable": 0,
              "neutral": 0}
    if not targets:
        return verdicts, "ok", counts
    try:
        ok = controls_ok(ch, gp) if controls is None else controls
    except Exception:
        ok = False
    if not ok:
        counts["endpoints"] = len({ep for ep in targets.values()})
        counts["neutral"] = counts["endpoints"]
        counts["controls"] = dict(LAST_CONTROLS)
        return verdicts, "neutral_controls", counts
    endpoints = {}
    for key, endpoint in targets.items():
        endpoints.setdefault(endpoint, []).append(key)
    counts["endpoints"] = len(endpoints)
    deadline = time.monotonic() + budget_s
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(endpoint_verdict, host, port, ch, gp):
                       (host, port) for host, port in endpoints}
            for future, endpoint in futures.items():
                remaining = deadline - time.monotonic()
                try:
                    verdict = future.result(timeout=max(remaining, 0.1))
                except Exception:
                    verdict = None
                if verdict is True:
                    counts["reachable"] += 1
                elif verdict is False:
                    counts["unreachable"] += 1
                else:
                    counts["neutral"] += 1
                for key in endpoints[endpoint]:
                    verdicts[key] = verdict
    except Exception:
        counts["controls"] = dict(LAST_CONTROLS)
        return {key: None for key in targets}, "neutral_error", counts
    counts["controls"] = dict(LAST_CONTROLS)
    return verdicts, "ok", counts


# ------------------------------------------------- Iran-side latency
# Ping RTT from an Iranian probe, per endpoint. Globalping's ping
# measurement reports per-packet timings (min/avg); check-host's
# check-ping reports per-attempt connect times from the Tehran node.
# Either source is accepted; a failure to measure is None (neutral).

def ping_globalping(host, deadline=GP_POLL_DEADLINE_S):
    """One Globalping ping measurement from an Iran-located probe.
    Returns the average RTT in ms (float) or None."""
    payload = {"type": "ping", "target": host,
               "locations": [{"country": "IR", "limit": 1}],
               "measurementOptions": {"packets": 3}}
    try:
        created = _http_json(GLOBALPING_BASE + "/measurements",
                             data=payload)
        measurement_id = created.get("id")
        if not measurement_id:
            return None
    except Exception:
        return None
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        time.sleep(2.5)
        try:
            result = _http_json("%s/measurements/%s"
                                % (GLOBALPING_BASE, measurement_id))
        except Exception:
            continue
        if result.get("status") not in ("finished", "failed"):
            continue
        results = result.get("results") or []
        if not results:
            return None
        stats = (results[0].get("result") or {}).get("stats") or {}
        avg = stats.get("avg")
        if isinstance(avg, (int, float)) and avg > 0:
            return float(avg)
        return None
    return None


def ping_check_host(host, node=TEHRAN_NODE, deadline=POLL_DEADLINE_S):
    """One check-host ping from the Tehran node. Returns the mean
    per-attempt time in ms (float) or None."""
    try:
        _pace()
        created = _http_json("%s/check-ping?host=%s&node=%s" % (
            CHECK_HOST_BASE, urllib.request.quote(host, safe=""), node))
        request_id = created.get("request_id")
        if not request_id:
            return None
    except Exception:
        return None
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        time.sleep(2.0)
        try:
            result = _http_json("%s/check-result/%s"
                                % (CHECK_HOST_BASE, request_id))
        except Exception:
            continue
        entry = result.get(node) if isinstance(result, dict) else None
        if not entry:
            continue  # node has not reported yet
        attempts = entry[0] if isinstance(entry, list) and entry else []
        times = [a["time"] for a in attempts if isinstance(a, dict)
                 and isinstance(a.get("time"), (int, float))]
        if times:
            return sum(times) / len(times) * 1000.0
        return None  # reported without timings: inconclusive
    return None


def endpoint_latency(host, gp=ping_globalping, ch=ping_check_host):
    """Iran-side ping RTT (ms) for one endpoint's host. Globalping
    first (its ping reports clean per-packet stats); check-host ping
    as the alternative. None when neither can measure — neutral."""
    value = gp(host)
    if value is not None:
        return value
    return ch(host)


def annotate_with_latency(targets, latencies=None,
                          budget_s=DEFAULT_BUDGET_S,
                          workers=DEFAULT_WORKERS, ping=None):
    """Measure Iran-side ping latency for {key: (host, port)}.

    Returns {key: ms-or-None} for every input key, cached per unique
    host, bounded by budget_s. `latencies` may carry latencies an
    earlier stage already measured per key (e.g. piggybacked on a
    probe) — those are reused and never re-measured. This stage has
    NO controls and changes NO verdict: it only ranks."""
    if ping is None:
        ping = endpoint_latency
    latencies = latencies or {}
    out = {key: latencies.get(key) for key in targets}
    hosts = {}
    for key, (host, _port) in targets.items():
        if out[key] is None:
            hosts.setdefault(host, []).append(key)
    if not hosts:
        return out
    deadline = time.monotonic() + budget_s
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(ping, host): host for host in hosts}
            for future, host in futures.items():
                remaining = deadline - time.monotonic()
                try:
                    value = future.result(timeout=max(remaining, 0.1))
                except Exception:
                    value = None
                if value is not None:
                    for key in hosts[host]:
                        out[key] = value
    except Exception:
        pass  # latency is best-effort ranking data, never fatal
    return out


def stage_from_env():
    """Kill switch for tests / incidents: IR_DISABLE=1 skips the
    stage entirely (every key neutral)."""
    return bool(os.environ.get("IR_DISABLE"))
