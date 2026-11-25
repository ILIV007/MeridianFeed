"""Compose the public pool + VIP sub from intersected verify runs (strict rules).

GitHub Actions home for the MeridianFeed composer (independence
migration, 2026-11-25). Selection logic is unchanged from the local
composer; only paths moved: state lives in MERIDIAN_STATE_DIR
(ephemeral runner state + Actions cache for uri/source caches), the
pipeline package is this repo's pipeline/ directory, and outputs go
to MERIDIAN_OUT_DIR. The runner (run_compose.py) downloads verify
artifacts, snapshots KV feedback/previous pools into the state dir,
calls main(), and writes KV only in live mode.
"""
import base64, ipaddress, json, os, sys, urllib.parse
from pathlib import Path
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
PIPELINE_DIR = REPO_ROOT / "pipeline"
STATE_DIR = Path(os.environ.get("MERIDIAN_STATE_DIR", REPO_ROOT / ".composer-state"))
OUT_DIR = Path(os.environ.get("MERIDIAN_OUT_DIR", STATE_DIR / "out"))
BASE = str(STATE_DIR)
os.environ.setdefault("COLLECTOR_CACHE_DIR", str(STATE_DIR / "source_cache"))
sys.path.insert(0, str(PIPELINE_DIR))
import collector, verifier  # noqa: E402
OUT = str(OUT_DIR)
STATE_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)
Path(os.environ["COLLECTOR_CACHE_DIR"]).mkdir(parents=True, exist_ok=True)
VIP_LAT, VIP_SPD = 500.0, 2.5
MIN_GAP_S = 900
# VIP minimum floor (wolf's directive, 2026-11-20): the served VIP set
# carries at least this many configs, quality-gated — the floor is
# filled from persisted previous members (Tier 2) and then from
# double-pass keys that met the VIP floors (Tier 3), all tiers under
# the hard field-profile gate; if the country ceiling alone blocks
# the floor, the ceiling-escape rule applies (see ceiling_escape).
# See main().
VIP_FLOOR = 8

def load_runs(spec):
    runs = []
    for run_id, created_ts in spec:
        stats = json.load(open(f"{BASE}/stats-{run_id}.json"))
        assert stats.get("controls", {}).get("ok"), f"run {run_id} controls not ok"
        runs.append({"id": run_id, "ts": created_ts,
                     "sampled": (stats.get("input") or {}).get("sampled"),
                     "ir_counts": stats.get("ir_counts") or {},
                     "passes": {p["key_hash"]: p for p in stats.get("passes", [])}})
    runs.sort(key=lambda r: r["ts"])
    return runs

def public_eligible(runs):
    keys = {}
    for r in runs:
        for k, p in r["passes"].items():
            if p["public_criteria"]:
                keys.setdefault(k, []).append(r["ts"])
    out = set()
    for k, times in keys.items():
        times.sort()
        if any(b - a >= MIN_GAP_S for i, a in enumerate(times) for b in times[i + 1:]):
            out.add(k)
    return out

def vip_eligible(runs):
    # 3 consecutive cycles, VIP floors in each, triple spanning >=25 min
    # (overnight cycles run ~13-15 min apart; in production the hourly
    # schedule gives the same triple a ~2-3 h span naturally).
    # Since the 2026-11-20 freshness restructure this set no longer
    # admits to Tier 1 by itself — it is the RANKING precedence inside
    # the core (triple-pass keys rank first) and a reported statistic.
    out = set()
    for i in range(len(runs) - 2):
        trio = runs[i:i + 3]
        if trio[2]["ts"] - trio[0]["ts"] < 1500: continue
        common = set(trio[0]["passes"]) & set(trio[1]["passes"]) & set(trio[2]["passes"])
        for k in common:
            if all((trio[j]["passes"][k]["latency_ms"] or 1e9) <= VIP_LAT
                   and (trio[j]["passes"][k]["speed_mbps"] or 0) >= VIP_SPD for j in range(3)):
                out.add(k)
    return out

def vip_core_eligible(runs):
    """VIP core admission (freshness restructure, wolf's licence
    2026-11-20): a key must hold a Gate-3 pass in BOTH of the 2 most
    recent verify runs, meeting the VIP floors (<= VIP_LAT ms,
    >= VIP_SPD Mbps) in both. Rationale: the old 3-consecutive-cycles
    rule certified keys on evidence up to ~3 hours old, and field
    tests #6/#7 kept finding those keys already dead from Iran;
    freshness (the composer now dispatches a just-in-time verify so
    the freshest run is <= ~30 min old at compose time) + the
    Gate-IR / field-profile gates are the stricter-in-practice bar
    for a pool whose configs churn hourly. Triple-pass keys keep
    top rank inside the core (see rank_items)."""
    if len(runs) < 2:
        return set()
    a, b = runs[-2], runs[-1]
    out = set()
    for k in set(a["passes"]) & set(b["passes"]):
        if all((r["passes"][k].get("latency_ms") or 1e9) <= VIP_LAT
               and (r["passes"][k].get("speed_mbps") or 0) >= VIP_SPD
               for r in (a, b)):
            out.add(k)
    return out

def latest_record(runs, key):
    for r in reversed(runs):
        if key in r["passes"]:
            return r["passes"][key]

def apply_quotas(items, cap, per_source, per_country, per_protocol, per_host,
                 volatile_sources=frozenset(), volatile_cap=None,
                 per_service=None, state=None):
    # `state` carries the cap counters across calls so a multi-phase
    # selection still enforces every cap globally.
    if state is None:
        state = {}
    for _k in ("cs", "cc", "cp", "ch", "cv"):
        state.setdefault(_k, {})
    state.setdefault("volatile_used", 0)
    chosen = []
    cs, cc, cp, ch, cv = (state["cs"], state["cc"], state["cp"],
                          state["ch"], state["cv"])
    volatile_used = state["volatile_used"]
    for it in items:
        if len(chosen) >= cap: break
        s, c, p, h = it["source"], it["country"], it["protocol"], it["host"]
        if cs.get(s, 0) >= per_source or cc.get(c, 0) >= per_country: continue
        if cp.get(p, 0) >= per_protocol or ch.get(h, 0) >= per_host: continue
        if per_service is not None and cv.get(it.get("service"), 0) >= per_service:
            continue
        # Volatile-class sources (audit 2026-11-20) never dominate a
        # batch: their configs are opportunistic extras on top of the
        # stable-class foundation.
        if (volatile_cap is not None and s in volatile_sources
                and volatile_used >= volatile_cap):
            continue
        chosen.append(it)
        if s in volatile_sources:
            volatile_used += 1
        cs[s] = cs.get(s, 0) + 1; cc[c] = cc.get(c, 0) + 1
        cp[p] = cp.get(p, 0) + 1; ch[h] = ch.get(h, 0) + 1
        cv[it.get("service")] = cv.get(it.get("service"), 0) + 1
    state["volatile_used"] = volatile_used
    return chosen

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def post_label(c):
    """Clean channel-post label: flag + country + protocol only.

    The full client remark stays in the URI/subscription; the post
    states the brand and verification once, in its heading/intro.
    """
    cc = str(c.get("country") or "").strip().upper()
    protocol = str(c.get("protocol") or "").strip().upper()
    if len(cc) == 2 and cc.isalpha() and protocol:
        flag = "".join(chr(0x1F1E6 + ord(ch) - 65) for ch in cc)
        return "%s %s · %s" % (flag, cc, protocol)
    parts = [p.strip() for p in str(c.get("remark") or "").split("·") if p.strip()]
    if len(parts) >= 3 and len(parts[1]) >= 2 and parts[1][-2:].isalpha():
        return "%s · %s" % (parts[1], parts[2])
    return str(c.get("remark") or protocol or "Config")

# --- Iran-reachability regime (wolf's field test, 2026-11-20) --------
# Gate 3 verifies from US runners: "verified" meant alive-from-America.
# Iranian fixed-line ISPs block most direct-IP foreign servers, so the
# pools are now composed for reachability-from-Iran: fronting class is
# the top ranking factor, absolute latency no longer ranks (it encoded
# the US vantage), and country quotas are gone — quality, not country.
# Port policy (wolf's correction, 2026-11-20): NO port lock — 443 is
# the anchor share of each pool, alternates spread over the Cloudflare
# HTTPS alt-port ladder for fronted configs, and the works/dead
# feedback loop demotes what users actually find dead.
CF_NETS = collector.CF_NETS
# Survival classes v2 (wolf's SECOND field test, 2026-11-20): of the
# served VIP 44, exactly 6 worked from Iran — 3 CF-fronted VMess WS+TLS
# (one service via three anycast IPs) and 3 plain Shadowsocks on direct
# IPs. REALITY direct-IP went 0/13 and Hysteria2 0/3. Field survival by
# class drives the order: CF-fronted WS first, plain SS (no TLS layer —
# nothing for SNI/DPI filters to fingerprint) as its own high class,
# direct-IP TLS/REALITY demoted to the bottom.
FRONT_NAMES = ["cf-ip-ws-tls", "domain-ws-tls", "plain-ss",
               "reality-sni", "reality", "other"]
FIELD_PROFILE_FRONTS = (0, 1, 2)  # classes matching the field-working traits

def classify_uri(uri):
    """(port, front_class) for a raw config URI. Classes (v2):
    0 CF-anycast-IP WS+TLS, 1 domain WS+TLS (CDN-fronted),
    2 plain Shadowsocks (no TLS layer), 3 REALITY with SNI,
    4 REALITY without SNI, 5 everything else (bare direct-IP TLS,
    Hysteria2/UDP — the classes that died wholesale in the field).
    Lower ranks first."""
    protocol = uri.split("://", 1)[0].lower()
    if protocol == "hy2":
        protocol = "hysteria2"
    if protocol == "vmess":
        try:
            d = json.loads(base64.b64decode(uri[8:]).decode("utf-8", "replace"))
            port = int(d.get("port") or 0)
            transport = str(d.get("net") or "tcp").lower()
            security = "tls" if str(d.get("tls") or "").lower() == "tls" else ""
            host = str(d.get("add") or "")
            sni = str(d.get("sni") or d.get("host") or "")
        except Exception:
            return None, 5
    else:
        p = urllib.parse.urlparse(uri)
        host = p.hostname or ""
        port = p.port
        q = urllib.parse.parse_qs(p.query)
        transport = (q.get("type") or q.get("net") or ["tcp"])[0].lower()
        security = (q.get("security") or [""])[0].lower()
        sni = (q.get("sni") or [""])[0]
        if protocol == "ss":
            plugin = (q.get("plugin") or [""])[0].lower()
            if "tls" in plugin:  # v2ray-plugin style SS-over-TLS is not plain
                security = "tls"
                transport = "ws"
    try:
        addr = ipaddress.ip_address(host)
        is_ip = True
    except ValueError:
        addr, is_ip = None, False
    cf = bool(is_ip and any(addr in n for n in CF_NETS))
    if transport == "ws" and security == "tls" and cf:
        front = 0
    elif transport == "ws" and security == "tls" and not is_ip:
        front = 1
    elif protocol == "ss" and security != "tls":
        front = 2
    elif security == "reality" and sni:
        front = 3
    elif security == "reality":
        front = 4
    else:
        front = 5
    return port, front

def load_feedback():
    try:
        fb = json.load(open(f"{BASE}/feedback.json"))
        return fb if isinstance(fb, dict) else {}
    except Exception:
        return {}

def key_quarantined(feedback, runs, k):
    """A key reported dead stays excluded until a verify run created
    AFTER the report passes it again (re-verification lifts it)."""
    fb = feedback.get(k)
    if not fb or not fb.get("dead_ts"):
        return False
    return not any(r["ts"] > fb["dead_ts"] and k in r["passes"]
                   for r in runs)

def fill_excluded(feedback, runs, k, it):
    """Exclusions for the VIP-floor fill tiers (2 and 3): quarantined
    keys, keys carrying ANY dead feedback (even if re-verified since —
    Tier 1 may re-admit those, the fill tiers may not), Hysteria2
    unless field-verified (works >= 3), and Gate-IR confirmed
    unreachable keys (ir is False — fill accepts true or neutral,
    never false)."""
    fb = feedback.get(k) or {}
    if key_quarantined(feedback, runs, k) or fb.get("dead", 0) > 0:
        return True
    if it.get("ir") is False:
        return True
    return it["protocol"] == "hysteria2" and it.get("works", 0) < 3

# --- Fill profile gate (field iteration 3, wolf's FF6 verdict) ------
# The first filled VIP (composed 2026-11-20) reached its floor of 8
# with resurrected previous-series members — and wolf's field test #6
# killed half of them from Iranian mobile: a VLESS ws/REALITY (front
# 3), two plain SS on :19999, while the working four were exactly the
# field-proven profile (fronted WS+TLS on 443 + SS on 443). The fill
# tiers therefore admit only that profile now; Tier 1 (the strict
# triple-pass core) is UNCHANGED — this gate binds the fill only.
# The port axis is judged by the SS rule's own yardstick — 443 or a
# field-verified endpoint — NOT by the CF ladder: :19999 is an
# ordinary port in the sources (the proven SS key lives there), and
# the ladder ports matter to the fronted classes, which the class
# rule already governs.
FILL_LADDER_PORTS = {2053, 2096, 8443, 2083, 2087}

def fill_profile_reason(it):
    """None if the item matches the field-proven profile for the
    VIP-floor FILL tiers, else the refusal reason:
    - front classes 0 (CF-IP WS+TLS) and 1 (domain WS+TLS): always
      allowed (subject to the port rule below);
    - plain SS (class 2): only on port 443, or when the host:port is
      itself field-verified;
    - REALITY (classes 3/4): excluded unless the specific key is
      field-verified — the Hy2 rule, mirrored (REALITY's field record
      is 0/13 plus the FF6 VLESS death);
    - any other class: excluded unless field-verified (they are the
      classes that died wholesale in the field);
    - a non-standard port (not 443, not the CF ladder) refuses every
      class unless field-verified (the :1270 case).
    Field-verified = works >= 3. For classes 0/1 and for the
    non-standard-port rule the credit is per KEY (this exact config);
    for plain SS it may also come from the exact host:port — wolf's
    proven SS@19999 key carries its credit on the endpoint even when
    a presentation variant's own key is young."""
    fv = it.get("works", 0) >= 3
    fv_ep = fv or it.get("endpoint_works", 0) >= 3
    front = it.get("front")
    port = it.get("port")
    if front == 2:
        # Plain SS has no fronting class to hide behind: 443, or an
        # endpoint that is itself field-verified (per key or per
        # host:port) — everything else is the FF6 death pattern.
        return None if (port == 443 or fv_ep) else "ss_off_443"
    if port != 443 and port not in FILL_LADDER_PORTS and not fv:
        return "nonstandard_port"
    if front in (0, 1):
        return None
    if front in (3, 4):
        return None if fv else "reality_not_field_verified"
    return None if fv else "class_not_field_verified"

def fill_profile_ok(it):
    return fill_profile_reason(it) is None

# Since the 2026-11-20 restructure the field profile is a HARD
# requirement for every VIP tier, Tier 1 included — not just the
# fill (brief: "field-profile as a hard VIP requirement (all
# tiers)"). FF6/FF7 evidence: REALITY is 0-for-everything in the
# field, Hysteria2 0/7, non-standard ports dead on arrival; a
# triple-pass REALITY key in Tier 1 was the last hole. The gate is
# the same function for all tiers; `profile_reason` is its
# tier-neutral name.
profile_reason = fill_profile_reason

def ir_tier1_ok(it):
    """Gate-IR (R6.1) Tier-1 admission: the key's latest verdict must
    be reachable — unless field truth overrides (works >= 3: repeated
    real-user confirmation from Iran outranks a probe node). Neutral
    (None — stage neutral, or the key was not a VIP-floor pass in its
    latest run) does not admit to Tier 1 on its own; the fill tiers
    below still accept neutral keys."""
    return it.get("ir") is True or it.get("works", 0) >= 3

def ir_fill_ok(it):
    """Gate-IR for the fill tiers: reachable or neutral, never a
    confirmed Iran-unreachable verdict."""
    return it.get("ir") is not False

def tier3_eligible(runs):
    """Tier-3 fill keys: double-pass keys (the public-tier pattern —
    passes >= MIN_GAP_S apart) whose records ALSO met the VIP floors
    (<= VIP_LAT ms, >= VIP_SPD Mbps) in at least two runs."""
    hits = {}
    for r in runs:
        for k, p in r["passes"].items():
            if (p.get("public_criteria")
                    and (p.get("latency_ms") or 1e9) <= VIP_LAT
                    and (p.get("speed_mbps") or 0) >= VIP_SPD):
                hits.setdefault(k, []).append(r["ts"])
    out = set()
    for k, times in hits.items():
        times.sort()
        if any(b - a >= MIN_GAP_S for i, a in enumerate(times)
               for b in times[i + 1:]):
            out.add(k)
    return out

def recent_pass(runs, key, n=3):
    """True if the key holds a Gate-3 pass in any of the last n runs."""
    return any(key in r["passes"] for r in runs[-n:])

def load_prev_vip_keys():
    """Keys of the PREVIOUS served VIP set (the Tier-2 persistence
    pool). The hourly driver snapshots the KV vip_index to
    prev_vip_index.json before composing; fall back to the last local
    out/vip_index.json."""
    for path in (f"{BASE}/prev_vip_index.json", f"{OUT}/vip_index.json"):
        try:
            idx = json.load(open(path))
            return [i["key"] for i in idx.get("items", []) if i.get("key")]
        except Exception:
            continue
    return []

def load_prev_rescue():
    """The PREVIOUS served pool's rescue list (wolf's rule, 2026-11-20:
    rescue configs never go in the channel post — when one is deleted,
    its removal is announced by reply in the same chat instead). The
    hourly driver snapshots the KV public_pool to
    prev_public_pool.json before composing. Returns [{key, remark}]
    with the opaque pass-key hash (URI parsed back to its dedup key);
    unparseable entries are skipped, a missing snapshot is []."""
    try:
        pool = json.load(open(f"{BASE}/prev_public_pool.json"))
    except Exception:
        return []
    out = []
    for entry in pool.get("rescue", []) or []:
        try:
            rec = collector.parse_uri(entry.get("uri", ""), "rescue")
            if rec is None:
                continue
            out.append({"key": verifier.pass_key(rec),
                        "remark": entry.get("remark", "")})
        except Exception:
            continue
    return out


def rescue_removed(prev_rescue, served_keys, feedback, runs):
    """Which previous rescue configs were DELETED this cycle (wolf,
    2026-11-20): a previous rescue key that serves nowhere now AND
    is dead by evidence — either quarantined (a dead report with no
    re-pass since) or holding no Gate-3 pass in any of this compose's
    runs. A rescue key that still serves (or just lost its slot to
    another rescue pick while alive) is NOT removed — rotation is not
    deletion. Rescue keys are front 0/1, i.e. the profile stratum the
    verifier samples in full every cycle, so 'no pass in any run'
    means it genuinely failed, not that it went untested."""
    out = []
    for item in prev_rescue:
        k = item["key"]
        if k in served_keys:
            continue
        if key_quarantined(feedback, runs, k) or \
                not any(k in r["passes"] for r in runs):
            out.append({"key": k, "remark": item["remark"]})
    return out

def rank_items(items, volatile=frozenset()):
    """The shared pool ranking (both tiers identical). Field-verified
    tier first (v2): a key with works >= 3 — repeated real-user
    confirmation from Iran, or a seeded field test — outranks
    survival CLASS inference; one tap (works 1) cannot reach this
    tier. Then fronting class, then Iran-side ping latency (Gate-IR,
    field iteration 3) — the first signal measured from Iran itself
    rather than from the US runners. A missing IR latency is neutral:
    it sorts after every measured value within the same tier/class,
    never a penalty beyond ordering and never an exclusion. Then
    source stability, pass consistency, field works, speed; the
    US-runner latency is only the final tiebreak."""
    return sorted(items, key=lambda x: (
        0 if x["works"] >= 3 else 1,
        0 if x.get("triple") else 1,
        x["front"],
        x["ir_latency_ms"] if x.get("ir_latency_ms") is not None
        else float("inf"),
        1 if x["source"] in volatile else 0,
        -x["pass_count"], -min(x["works"], 5),
        -x["speed_mbps"], x["latency_ms"]))

def port_order(items, anchor_frac, cap):
    """Consideration order: field-verified items (works >= 3) lead
    regardless of port — direct evidence from Iran beats the port
    preference. Everything else follows the port mix: the 443
    anchor share first, then alternate ports (fronted ladder ports
    first), then any remaining 443s."""
    import math
    verified = [i for i in items if i["works"] >= 3]
    rest = [i for i in items if i["works"] < 3]
    anchor_target = min(math.ceil(cap * anchor_frac),
                        sum(1 for i in rest if i["port"] == 443))
    on443 = [i for i in rest if i["port"] == 443]
    off443 = [i for i in rest if i["port"] != 443]
    off443.sort(key=lambda x: 0 if (x["front"] <= 1
                                    and x["port"] in FILL_LADDER_PORTS) else 1)
    return verified + on443[:anchor_target] + off443 + on443[anchor_target:]


def select(items, cap, anchor_frac, per_source, per_protocol,
           per_host, volatile_cap, per_service=None,
           volatile=frozenset()):
    """Selection over ranked eligible items with GLOBAL caps
    (source/protocol/host/service/volatile counters shared across
    phases) and a constructive anti-monoculture ceiling: the
    majority country's items are admitted only up to the number of
    non-majority items admitted, so the majority can never exceed
    50% of the served set. Every country is also capped at
    floor(cap/2) during selection (same rule as fill_to_floor) —
    before 2026-11-25 the non-majority phase had no per-country
    cap, so one second country could take 4 of 5 slots and the
    delete-only safety net trimmed 3 good configs away (Nov 24
    20:25 tick: served 2 of 172 qualifying). Scarce non-majority
    supply is therefore selected FIRST and never crowded out by
    other caps. If the eligible set has a single country only, the
    ceiling is unsatisfiable and the set serves as-is (flagged in
    the summary) rather than serving nothing."""
    from collections import Counter
    counts = Counter(i["country"] for i in items)
    majority = counts.most_common(1)[0][0] if counts else None
    per_country = cap if len(counts) <= 1 else max(1, cap // 2)
    state = {}
    chosen = apply_quotas(
        port_order([i for i in items if i["country"] != majority],
                   anchor_frac, cap),
        cap, per_source, per_country, per_protocol, per_host,
        volatile_sources=volatile, volatile_cap=volatile_cap,
        per_service=per_service, state=state)
    if not chosen:
        maj_cap = cap  # single-country supply: ceiling unsatisfiable
    else:
        maj_cap = min(cap - len(chosen), len(chosen))
    chosen += apply_quotas(
        port_order([i for i in items if i["country"] == majority],
                   anchor_frac, cap),
        maj_cap, per_source, per_country, per_protocol, per_host,
        volatile_sources=volatile, volatile_cap=volatile_cap,
        per_service=per_service, state=state)
    return rank_items(chosen, volatile), majority


def enforce_country_ceiling(chosen):
    """Safety net for the ceiling (see select): trims a majority
    excess lowest-ranked first. Normally drops 0 — the constructive
    selection already satisfies the share. Returns (kept, dropped)."""
    from collections import Counter
    chosen = list(chosen)
    dropped = 0
    while len(chosen) > 1:
        top, n = Counter(c["country"] for c in chosen).most_common(1)[0]
        if n * 2 <= len(chosen):
            break
        idx = max(i for i, c in enumerate(chosen)
                  if c["country"] == top)
        chosen.pop(idx)
        dropped += 1
    return chosen, dropped


def fill_to_floor(pool, candidates, floor_n):
    """Append ranked candidates until the pool reaches floor_n.
    Constructive 50% country ceiling: a candidate is skipped when
    adding it would put its country above half of the resulting set
    (waived when pool + candidates are single-country — the ceiling
    is then unsatisfiable, the standing select() philosophy). Never
    invents supply: returns what honestly exists. (pool, added)."""
    from collections import Counter
    pool = list(pool)
    have = {c["key_hash"] for c in pool}
    countries = ({c["country"] for c in pool}
                 | {c["country"] for c in candidates})
    single_country = len(countries) <= 1
    # The ceiling is judged against the FLOOR-sized target set: a
    # country may hold at most half of floor_n seats. (Judging against
    # the instantaneous pool deadlocked an empty pool — the first add
    # is always 1-of-1 = 100% — which is exactly the Tier-1-empty case
    # the floor exists for; found live 2026-11-20, Gate-IR's first
    # neutral cycle.) main() re-applies enforce_country_ceiling to
    # the filled set afterwards as the backstop for short supplies.
    cap = max(1, floor_n // 2)
    counts = Counter(c["country"] for c in pool)
    added = 0
    for it in candidates:
        if len(pool) >= floor_n:
            break
        if it["key_hash"] in have:
            continue
        if not single_country and counts.get(it["country"], 0) >= cap:
            continue
        pool.append(it)
        have.add(it["key_hash"])
        counts[it["country"]] += 1
        added += 1
    return pool, added

def ceiling_escape(pool, stream, floor_n, per_service=4, per_host=2):
    """Ceiling escape (documented rule refinement, wolf's addendum
    2026-11-20). The 50% country ceiling + US-heavy profile-clean
    supply mathematically pin VIP at 2x the non-US count — measured
    live: 2 served while profile-clean, gate-passing US supply sat
    unused. Wolf's standing priorities conflict there ("no
    monoculture" vs "grow the absolute working count, never a token
    few"), and the resolution is: the ceiling stays the default, but
    when the quality-gated floor cannot be met SOLELY because of the
    ceiling, the pool is topped up to the floor from the admissible
    stream (tier order, ranked) with the ceiling exceeded — and the
    relaxation is logged loudly (vip_ceiling_relaxed + slot count).
    ONLY the country share yields, and only up to the floor: the
    per-service (4) and per-host (2) caps are re-applied here, and
    every quality gate, the profile rule, the IR rule and the
    quarantine have already bound the stream before this runs."""
    from collections import Counter
    pool = list(pool)
    have = {c["key_hash"] for c in pool}
    services = Counter(c.get("service") for c in pool)
    hosts = Counter(c.get("host") for c in pool)
    added = 0
    for it in stream:
        if len(pool) >= floor_n:
            break
        if it["key_hash"] in have:
            continue
        if services.get(it.get("service"), 0) >= per_service:
            continue
        if hosts.get(it.get("host"), 0) >= per_host:
            continue
        pool.append(it)
        have.add(it["key_hash"])
        services[it.get("service")] += 1
        hosts[it.get("host")] += 1
        added += 1
    return pool, added

# Persistent URI cache (local build state, never committed): every compose
# merges the URIs it just fetched, keyed by the same opaque pass-key hash
# the verifier emits. Eligible keys whose URIs churned out of the current
# source lists are recovered from here instead of being lost — the cached
# URI is the identical config (same dedup key = same protocol, server,
# port and credential), and eligibility still comes only from the verify
# stats intersections. Entries not re-seen for 7 days are pruned.
CACHE_PATH = f"{BASE}/uri_cache.json"
CACHE_TTL_S = 7 * 86400

def load_cache():
    try:
        return json.load(open(CACHE_PATH))
    except Exception:
        return {}

def save_cache(cache, now_ts):
    cache = {k: v for k, v in cache.items() if now_ts - v.get("ts", 0) <= CACHE_TTL_S}
    open(CACHE_PATH, "w").write(json.dumps(cache, ensure_ascii=False))
    return cache

def main():
    spec = [(r["id"], r["ts"]) for r in json.load(open(f"{BASE}/runs.json"))]
    runs = load_runs(spec)
    pub_keys, vip_keys = public_eligible(runs), vip_eligible(runs)
    registry = json.load(open(PIPELINE_DIR / "sources.json"))
    seen = {}
    import random as _random
    _sources = [s for s in registry.get("sources", []) if s.get("enabled", True)]
    _random.shuffle(_sources)  # spread politely: no fixed hammering order
    for source in _sources:
        try:
            # fetch_source covers multi-URL registry entries (e.g.
            # Au1rxx's 6 shards); a bare source["url"] KeyError here
            # silently skipped those sources in live recovery
            # (checkup 2026-11-25).
            fetched, _fetch_errors = collector.fetch_source(source)
        except Exception:
            continue
        for _url, raw in fetched:
            for text in collector.candidate_texts(raw):
                for uri in collector.extract_candidates(text):
                    record = collector.parse_uri(uri, source["name"])
                    if record is None: continue
                    key = collector.dedup_key(record)
                    if key not in seen:
                        seen[key] = (record, uri)
                    for vrec, vuri in collector.expand_cf_variants(record, uri):
                        vkey = collector.dedup_key(vrec)
                        if vkey not in seen:
                            seen[vkey] = (vrec, vuri)
    by_hash = {verifier.pass_key(rec): (rec, uri) for rec, uri in seen.values()}
    from datetime import datetime, timezone
    now_ts = datetime.now(timezone.utc).timestamp()
    cache = load_cache()
    for k, (rec, uri) in by_hash.items():
        cache[k] = {"uri": uri, "protocol": rec["protocol"], "server": rec["server"],
                    "source": rec.get("source", ""), "ts": now_ts}
    cache = save_cache(cache, now_ts)
    # Snapshot pinning (Phase B): per-run sampled key->URI maps from the
    # verify runs themselves (private Actions artifacts, fetched by the
    # hourly driver into pin-<run_id>.json). Recovery order: pin maps of
    # the contributing runs -> live lists -> URI cache. A pinned URI is
    # byte-identical to the config the run tested (same opaque key).
    pinned, pin_maps = {}, 0
    for r in runs:
        try:
            m = json.load(open(f"{BASE}/pin-{r['id']}.json"))
        except Exception:
            continue
        pin_maps += 1
        pinned.update(m)
    volatile = {s["name"] for s in registry.get("sources", [])
                if s.get("volatility") == "volatile"}
    feedback = load_feedback()
    # Endpoint-level field credit (field iteration 3): the fill
    # profile gate lets a plain-SS candidate in when its exact
    # host:port is itself field-verified, even if this presentation's
    # own key is young. Credit is derived from the URI cache (key ->
    # server:port) joined with the feedback store's works counters —
    # max works over all keys sharing the endpoint.
    endpoint_works = {}
    for _k, _e in cache.items():  # already loaded + saved above
        _w = (feedback.get(_k) or {}).get("works", 0)
        if not _w:
            continue
        try:
            _rec = collector.parse_uri(_e["uri"], "")
        except Exception:
            _rec = None
        if _rec:
            _ep = (_rec["server"], _rec["port"])
            if _w > endpoint_works.get(_ep, 0):
                endpoint_works[_ep] = _w
    hits = {"pin": 0, "cache": 0}
    def build(keys):
        items, missing = [], 0
        for k in keys:
            pr = latest_record(runs, k)
            if k in pinned:
                uri = pinned[k]
                record = collector.parse_uri(uri, (pr or {}).get("source", ""))
                if record is None:
                    missing += 1; continue
                record["source"] = (pr or {}).get("source", "")
                hits["pin"] += 1
            elif k in by_hash:
                record, uri = by_hash[k]
            elif k in cache:
                e = cache[k]
                record = {"protocol": e["protocol"], "server": e["server"],
                          "source": e.get("source", "")}
                uri = e["uri"]
                hits["cache"] += 1
            else:
                missing += 1; continue
            country = (pr or {}).get("egress_country") or "??"
            remark = verifier.format_remark(country, record["protocol"])
            port, front = classify_uri(uri)
            items.append({"key_hash": k, "uri": verifier.rebrand_uri(uri, remark),
                          "remark": remark, "protocol": record["protocol"],
                          "country": country, "source": record.get("source", ""),
                          "host": record["server"],
                          "service": collector.service_key_from_uri(uri),
                          "port": port, "front": front,
                          "pass_count": sum(1 for r in runs if k in r["passes"]),
                          "speed_mbps": (pr or {}).get("speed_mbps") or 0.0,
                          "works": (feedback.get(k) or {}).get("works", 0),
                          "endpoint_works": endpoint_works.get(
                              (record["server"], port), 0),
                          "ir": (pr or {}).get("ir_reachable"),
                          "ir_latency_ms": (pr or {}).get("ir_latency_ms"),
                          "latency_ms": (pr or {}).get("latency_ms") or 99999.0})
        return items, missing
    pub_items, pub_missing = build(pub_keys)
    # VIP Tier 1 is built from the FRESHNESS core (passes in both of
    # the 2 freshest runs at VIP floors — vip_core_eligible), not
    # from the triple-pass set; triple-pass membership rides along
    # as the in-core ranking precedence.
    core_keys = vip_core_eligible(runs)
    vip_items, vip_missing = build(core_keys)
    for _i in vip_items:
        _i["triple"] = _i["key_hash"] in vip_keys

    # Field-feedback quarantine (both tiers): a key reported dead is
    # excluded until a verify run created AFTER the report passes it
    # again (re-verification lifts the quarantine automatically).
    def quarantined(k):
        return key_quarantined(feedback, runs, k)

    # Iran-reachability ranking (both tiers, identical): fronting class
    # first, then source stability, pass consistency, field works
    # reports, speed — latency only as the final tiebreak. No country
    # quotas. No port lock either (wolf's correction, 2026-11-20):
    # port 443 is the ANCHOR share of each pool (largest single share),
    # the remainder spreads over alternate ports — for fronted configs
    # preferring the Cloudflare HTTPS alt-port ladder (the BPB matrix
    # lesson). The feedback loop, not a hard lock, demotes dead ports.
    def rank(items):
        return rank_items(items, volatile)

    def admit(items):
        kept, n_quar = [], 0
        for it in items:
            if quarantined(it["key_hash"]):
                n_quar += 1
            else:
                kept.append(it)
        return rank(kept), n_quar

    pub_items, pub_quar = admit(pub_items)
    vip_items, vip_quar = admit(vip_items)
    # Field rule (wolf's field test #3, 2026-11-20): Hysteria2 is
    # EXCLUDED from VIP until a Hysteria2 key earns field-verified
    # status (works >= 3). Its field record across wolf's Iran tests
    # is 0/5 — UDP/QUIC is filtered hard there and Gate 3 from US
    # runners cannot see it. The channel pool is unaffected: it is
    # the proving ground where a Hy2 key can earn its way into VIP.
    vip_hy2_excluded = sum(1 for i in vip_items
                           if i["protocol"] == "hysteria2"
                           and i["works"] < 3)
    # HARD PROFILE GATE — every VIP tier (restructure, 2026-11-20):
    # the field profile that began as a fill-only gate in field
    # iteration 3 now binds Tier 1 too. A core candidate that is
    # REALITY / Hysteria2 / off-profile-port and not itself
    # field-verified never enters VIP, however fresh its passes are
    # (FF6/FF7: those classes are 0-for-everything from Iran). The
    # Hysteria2 rule above is subsumed (Hy2 is class 5) and its
    # counter kept for continuity.
    vip_profile_excluded = {}
    _profile_clean = []
    for i in vip_items:
        _reason = profile_reason(i)
        if _reason is None:
            _profile_clean.append(i)
        else:
            vip_profile_excluded[_reason] = \
                vip_profile_excluded.get(_reason, 0) + 1
    vip_items = _profile_clean
    profile_clean_keys = {i["key_hash"] for i in vip_items}
    # Funnel: Gate-IR verdict distribution over the profile-clean
    # core candidates (latest run record per key, as built).
    ir_verdict_counts = {"true": 0, "false": 0, "null": 0}
    for i in vip_items:
        ir_verdict_counts[{True: "true", False: "false"}.get(
            i.get("ir"), "null")] += 1
    # Gate-IR (Plan Rev.2 R6.1): Tier 1 now also requires an
    # Iran-reachable verdict from the key's latest run record, unless
    # the key is field-verified (works >= 3 — field truth outranks
    # the probe node). IR-false keys are excluded from every VIP tier
    # (fill_excluded) but stay channel-eligible: the channel remains
    # the proving ground. Neutral keys (stage neutral / unchecked)
    # are withheld from Tier 1 only — the fill tiers accept them.
    vip_ir_excluded = {"false": 0, "neutral": 0}
    _t1_items = []
    for i in vip_items:
        if ir_tier1_ok(i):
            _t1_items.append(i)
        elif i.get("ir") is False:
            vip_ir_excluded["false"] += 1
        else:
            vip_ir_excluded["neutral"] += 1
    vip_items = _t1_items
    t1_admissible = rank(vip_items)
    # Tier differentiation (wolf, 2026-11-20): VIP selects FIRST from
    # the eligible set (proven core: triple-pass, VIP floors); the
    # channel batch is then composed from what remains — no config is
    # in both the current VIP set and a channel post. VIP anchors
    # heavier on 443 (70%) than the channel (60% of 5 = 3).
    # Per-service caps (v2): one origin service — however many
    # presentation variants it has — may not flood a pool.
    vip_pool, vip_majority = select(vip_items, 48, 0.70, 16, 32, 2, 6,
                                    per_service=4, volatile=volatile)
    vip_pool, vip_ceiling_dropped = enforce_country_ceiling(vip_pool)
    # VIP minimum floor (wolf's directive, 2026-11-20): Tier 1 above is
    # the freshness core (passes in both of the 2 freshest runs at
    # VIP floors, profile gate + Gate-IR applied, triple-pass keys
    # ranked first), served first. If it falls below VIP_FLOOR, fill
    # from Tier 2 (persisted members of the PREVIOUS served VIP set:
    # not quarantined, no dead feedback, profile gate applied,
    # Gate-3 pass within the last 3 runs), then Tier 3 (double-pass
    # keys that met the VIP floors in their qualifying runs, ranked
    # v2, same exclusions). Fill URIs come from build()
    # (pin -> live -> cache), so served = tested holds for fill tiers
    # too. The 50% country ceiling binds the whole filled set —
    # unless it alone blocks the floor, in which case the ceiling
    # escape below yields (logged); if supply still falls short,
    # serve what honestly exists and log the shortfall — never
    # resurrect a quarantined key to fill.
    vip_tiers = {"t1": len(vip_pool), "t2": 0, "t3": 0}
    # Field iteration 3: fill candidates refused by the profile gate
    # are counted by reason, so a shortfall is explainable at a
    # glance (the floor is quality-gated now — see fill_profile_reason).
    vip_fill_refused = {}

    def _fill_gate(items):
        kept = []
        for i in items:
            reason = fill_profile_reason(i)
            if reason is None:
                kept.append(i)
                profile_clean_keys.add(i["key_hash"])
            else:
                vip_fill_refused[reason] = vip_fill_refused.get(reason, 0) + 1
        return kept

    t2_admissible, t3_admissible = [], []
    if len(vip_pool) < VIP_FLOOR:
        have = {c["key_hash"] for c in vip_pool}
        t2_keys = [k for k in load_prev_vip_keys()
                   if k not in have and recent_pass(runs, k, 3)]
        t2_items, _t2_missing = build(t2_keys)
        t2_items = [i for i in t2_items
                    if not fill_excluded(feedback, runs, i["key_hash"], i)]
        t2_admissible = rank(_fill_gate(t2_items))
        vip_pool, vip_tiers["t2"] = fill_to_floor(
            vip_pool, t2_admissible, VIP_FLOOR)
    if len(vip_pool) < VIP_FLOOR:
        have = {c["key_hash"] for c in vip_pool}
        t3_items, _t3_missing = build(tier3_eligible(runs) - have)
        t3_items = [i for i in t3_items
                    if not fill_excluded(feedback, runs, i["key_hash"], i)]
        t3_admissible = rank(_fill_gate(t3_items))
        vip_pool, vip_tiers["t3"] = fill_to_floor(
            vip_pool, t3_admissible, VIP_FLOOR)
    if len({c["country"] for c in vip_pool}) > 1:
        vip_pool, _fill_trim = enforce_country_ceiling(vip_pool)
        vip_ceiling_dropped += _fill_trim
    # Ceiling escape (see ceiling_escape): if the floor is still
    # unmet, the ONLY rule allowed to yield is the country share —
    # top up from the admissible stream in tier order and log it
    # loudly. Quality gates / profile / IR / quarantine all bound
    # the stream already; per-service and per-host caps re-apply.
    vip_ceiling_relaxed = False
    vip_ceiling_relaxed_slots = 0
    if len(vip_pool) < VIP_FLOOR:
        vip_pool, vip_ceiling_relaxed_slots = ceiling_escape(
            vip_pool,
            list(t1_admissible) + list(t2_admissible)
            + list(t3_admissible),
            VIP_FLOOR)
        vip_ceiling_relaxed = vip_ceiling_relaxed_slots > 0
    vip_floor_shortfall = max(0, VIP_FLOOR - len(vip_pool))
    vip_floor_shortfall_reason = None
    if vip_floor_shortfall:
        # Quality-gated floor (field iteration 3): the shortfall is
        # served honestly and explained — how much of it the profile
        # gate caused vs a plain supply gap.
        refused_n = sum(vip_fill_refused.values())
        if vip_ceiling_relaxed:
            vip_floor_shortfall_reason = \
                "supply_exhausted_after_ceiling_escape"
        else:
            vip_floor_shortfall_reason = (
                "profile_gate_refused_%d" % refused_n if refused_n
                else "supply_exhausted")
    vip_served = {c["key_hash"] for c in vip_pool}
    pub_before_disjoint = len(pub_items)
    pub_items = [i for i in pub_items if i["key_hash"] not in vip_served]
    pub_pool, pub_majority = select(pub_items, 5, 0.60, 2, 3, 2, 1,
                                    per_service=2, volatile=volatile)
    pub_pool, pub_ceiling_dropped = enforce_country_ceiling(pub_pool)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Rescue-post rule (wolf, 2026-11-20): rescue configs NEVER go in
    # the channel post any more — the post carries only the 5-config
    # batch. A rescue config that died this cycle is reported here
    # instead, and the publisher announces it by reply in the channel.
    served_keys = {c["key_hash"] for c in vip_pool} | \
        {c["key_hash"] for c in pub_pool}
    removed = rescue_removed(load_prev_rescue(), served_keys, feedback,
                             runs)
    pool_json = {"generated_at": generated, "runs": [r["id"] for r in runs],
                 "rescue_removed": [{"key": r["key"], "remark": r["remark"]}
                                    for r in removed],
                 "configs": [{"uri": c["uri"], "remark": c["remark"], "protocol": c["protocol"],
                              "country": c["country"], "latency_ms": c["latency_ms"]} for c in pub_pool]}
    open(f"{OUT}/public_pool.json", "w").write(json.dumps(pool_json, ensure_ascii=False))
    vip_sub_text = (base64.b64encode(
        "\n".join(c["uri"] for c in vip_pool).encode()).decode() if vip_pool else "")
    open(f"{OUT}/vip_sub.txt", "w").write(vip_sub_text)
    # vip_index: numbered key/remark list the bot uses for per-config
    # field feedback (buttons resolve number -> opaque key here).
    import hashlib as _hashlib
    vip_index = {"tag": _hashlib.sha256(vip_sub_text.encode()).hexdigest()[:8],
                 "items": [{"n": i + 1, "key": c["key_hash"], "remark": c["remark"]}
                           for i, c in enumerate(vip_pool)]}
    open(f"{OUT}/vip_index.json", "w").write(json.dumps(vip_index, ensure_ascii=False))
    html = "<h3>\U0001FABC Verified V2Ray Configs</h3>"
    html += "<p>%d configs, verified end-to-end.</p>" % len(pub_pool)
    for c in pub_pool:
        html += "<p><b>%s</b></p><pre>%s</pre>" % (esc(post_label(c)), esc(c["uri"]))
    html += "<blockquote><b>\U0001FABC @PROXIV3</b></blockquote>"
    open(f"{OUT}/post.html", "w").write(html)
    # Funnel (wolf's addendum, 2026-11-20): per-stage counts for the
    # whole cycle, so the choke points are numbers, not vibes —
    # collected -> sampled -> Gate-3 passed -> core candidates ->
    # profile-clean -> IR verdicts -> eligible per tier -> served.
    funnel = {"collected_unique": len(by_hash),
              "latest_run_sampled": runs[-1].get("sampled") if runs else None,
              "latest_run_gate3_passed": len(runs[-1]["passes"]) if runs else 0,
              "vip_core_candidates": len(core_keys),
              "vip_triple_pass_candidates": len(vip_keys),
              "vip_profile_clean_candidates": len(profile_clean_keys),
              "ir_verdicts_core": ir_verdict_counts,
              "vip_eligible_tiers": {"t1": len(t1_admissible),
                                     "t2": len(t2_admissible),
                                     "t3": len(t3_admissible)},
              "vip_served": len(vip_pool),
              "public_served": len(pub_pool)}
    summary = {"runs": [r["id"] for r in runs],
               "funnel": funnel,
               "vip_core_candidates": len(core_keys),
               "vip_profile_excluded": vip_profile_excluded,
               "vip_ceiling_relaxed": vip_ceiling_relaxed,
               "vip_ceiling_relaxed_slots": vip_ceiling_relaxed_slots,
               "gate3_passes_per_run": {r["id"]: len(r["passes"]) for r in runs},
               "public_double_pass_intersection": len(pub_keys),
               "public_pool_after_quotas": len(pub_pool),
               "rescue_removed": [r["remark"] for r in removed],
               "public_unrecovered_uris": pub_missing,
               "pin_maps_loaded": pin_maps,
               "recovered_from_pin": hits["pin"],
               "recovered_from_cache": hits["cache"],
               "vip_triple_pass_intersection": len(vip_keys),
               "vip_pool_after_quotas": len(vip_pool),
               "vip_tiers": vip_tiers,
               "vip_floor": VIP_FLOOR,
               "vip_floor_shortfall": vip_floor_shortfall,
               "vip_floor_shortfall_reason": vip_floor_shortfall_reason,
               "vip_fill_refused": vip_fill_refused,
               "vip_ir_latency_ranked": sum(
                   1 for c in vip_pool if c.get("ir_latency_ms") is not None),
               "vip_unrecovered_uris": vip_missing,
               "public_countries": sorted({c["country"] for c in pub_pool}),
               "public_protocols": sorted({c["protocol"] for c in pub_pool}),
               "vip_countries": sorted({c["country"] for c in vip_pool}),
               "vip_protocols": sorted({c["protocol"] for c in vip_pool}),
               "public_qualifying": len(pub_items),
               "public_removed_vip_disjoint": pub_before_disjoint - len(pub_items),
               "public_excluded_quarantine": pub_quar,
               "public_port_mix": {str(p): sum(1 for c in pub_pool if c["port"] == p)
                                   for p in sorted({c["port"] for c in pub_pool}, key=lambda v: (v is None, v))},
               "public_fronting": {FRONT_NAMES[f]: sum(1 for c in pub_pool if c["front"] == f)
                                   for f in range(len(FRONT_NAMES)) if any(c["front"] == f for c in pub_pool)},
               "public_country_mix": {c: sum(1 for x in pub_pool if x["country"] == c)
                                      for c in sorted({x["country"] for x in pub_pool})},
               "public_country_ceiling_dropped": pub_ceiling_dropped,
               "public_field_profile_share": (
                   round(sum(1 for c in pub_pool if c["front"] in FIELD_PROFILE_FRONTS)
                         / len(pub_pool), 3) if pub_pool else 0),
               "vip_qualifying": len(vip_items),
               "vip_excluded_quarantine": vip_quar,
               "vip_hy2_excluded": vip_hy2_excluded,
               "vip_ir_excluded": vip_ir_excluded,
               "vip_port_mix": {str(p): sum(1 for c in vip_pool if c["port"] == p)
                                for p in sorted({c["port"] for c in vip_pool}, key=lambda v: (v is None, v))},
               "vip_fronting": {FRONT_NAMES[f]: sum(1 for c in vip_pool if c["front"] == f)
                                for f in range(len(FRONT_NAMES)) if any(c["front"] == f for c in vip_pool)},
               "vip_country_mix": {c: sum(1 for x in vip_pool if x["country"] == c)
                                   for c in sorted({x["country"] for x in vip_pool})},
               "vip_country_ceiling_dropped": vip_ceiling_dropped,
               "vip_country_majority": vip_majority,
               "public_country_majority": pub_majority,
               "vip_field_profile_share": (
                   round(sum(1 for c in vip_pool if c["front"] in FIELD_PROFILE_FRONTS)
                         / len(vip_pool), 3) if vip_pool else 0),
               "post_html_chars": len(html)}
    open(f"{OUT}/summary.json", "w").write(json.dumps(summary, indent=1))
    # Starvation tracking: a public cycle serving <5 means the strict
    # regime (443 + fronting + tiers) genuinely had fewer qualifiers —
    # recorded, never padded.
    with open(f"{BASE}/compose_log.jsonl", "a") as fh:
        fh.write(json.dumps({
            "ts": generated, "public_qualifying": len(pub_items),
            "public_served": len(pub_pool), "vip_qualifying": len(vip_items),
            "vip_served": len(vip_pool), "vip_tiers": vip_tiers,
            "funnel": funnel,
            "vip_ceiling_relaxed": vip_ceiling_relaxed,
            "vip_ceiling_relaxed_slots": vip_ceiling_relaxed_slots,
            "vip_floor_shortfall": vip_floor_shortfall,
            "vip_floor_shortfall_reason": vip_floor_shortfall_reason,
            "vip_fill_refused": vip_fill_refused,
            "vip_country_ceiling_dropped": vip_ceiling_dropped,
            "public_country_ceiling_dropped": pub_ceiling_dropped}) + "\n")
    print(json.dumps(summary, indent=1))

if __name__ == "__main__":
    main()
