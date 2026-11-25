"""Tests for the VIP minimum-floor composition logic (compose.py).

Wolf's directive, 2026-11-20: VIP serves >= 8 configs via tiered
fill (Tier 1 strict triple-pass; Tier 2 persisted previous members;
Tier 3 double-pass keys meeting the VIP floors). Gates unchanged;
the 50% country ceiling binds the filled set; shortfalls are served
honestly, never padded with quarantined keys.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import compose  # noqa: E402


def item(key, country, protocol="vmess", works=0):
    return {"key_hash": key, "country": country,
            "protocol": protocol, "works": works}


def run(ts, passes):
    return {"id": str(ts), "ts": ts, "passes": passes}


def rec(public=True, lat=300.0, spd=3.0):
    return {"public_criteria": public, "latency_ms": lat,
            "speed_mbps": spd}


# --- fill_to_floor -------------------------------------------------

def test_floor_met_via_fill():
    pool = [item("a", "US"), item("b", "CA")]
    cands = [item("c", "FR"), item("d", "DE"), item("e", "NL"),
             item("f", "PL"), item("g", "SE"), item("h", "US")]
    pool, added = compose.fill_to_floor(pool, cands, 8)
    assert len(pool) == 8 and added == 6

def test_floor_ceiling_blocks_monoculture():
    # Fill-level cap is judged against the floor-sized set (cap =
    # floor/2 per country); the SERVED set's 50% ceiling is then
    # enforced exactly by enforce_country_ceiling in main(). (The
    # earlier instantaneous-pool rule deadlocked an empty pool live
    # on 2026-11-20 — see test_fill_bootstraps_from_empty_pool.)
    pool = [item("a", "US"), item("b", "CA")]
    cands = [item("u%d" % i, "US") for i in range(6)]
    pool, added = compose.fill_to_floor(pool, cands, 8)
    assert sum(1 for c in pool if c["country"] == "US") <= 4
    pool, _dropped = compose.enforce_country_ceiling(pool)
    us = sum(1 for c in pool if c["country"] == "US")
    assert us * 2 <= len(pool)

def test_floor_ceiling_partial_growth():
    pool = [item("a", "US"), item("b", "CA"), item("c", "FR")]
    cands = [item("u1", "US"), item("u2", "US")]
    pool, added = compose.fill_to_floor(pool, cands, 8)
    assert added == 2 and len(pool) == 5  # fill cap (4/country) not hit
    pool, _dropped = compose.enforce_country_ceiling(pool)
    us = sum(1 for c in pool if c["country"] == "US")
    assert us * 2 <= len(pool)  # served set back at the 50% ceiling

def test_floor_single_country_waived():
    pool = [item("a", "US"), item("b", "US")]
    cands = [item("u%d" % i, "US") for i in range(6)]
    pool, added = compose.fill_to_floor(pool, cands, 8)
    assert len(pool) == 8 and added == 6

def test_floor_shortfall_serves_what_exists():
    pool = [item("a", "US"), item("b", "CA")]
    cands = [item("c", "FR"), item("d", "DE"), item("e", "NL")]
    pool, added = compose.fill_to_floor(pool, cands, 8)
    assert len(pool) == 5 and added == 3

def test_floor_skips_duplicates_and_stops_at_floor():
    pool = [item("a", "US"), item("b", "CA")]
    cands = [item("a", "US"), item("c", "FR"), item("d", "DE"),
             item("e", "NL"), item("f", "PL"), item("g", "SE"),
             item("h", "TR"), item("i", "JP")]
    pool, added = compose.fill_to_floor(pool, cands, 8)
    keys = [c["key_hash"] for c in pool]
    assert len(pool) == 8 and len(set(keys)) == 8 and added == 6

# --- tier3_eligible --------------------------------------------------

def test_tier3_needs_two_vip_floor_passes_with_gap():
    runs = [run(0, {"A": rec(), "B": rec(), "C": rec(), "D": rec(public=False)}),
            run(500, {"C": rec()}),
            run(2000, {"A": rec(), "B": rec(lat=600.0), "D": rec(public=False)})]
    out = compose.tier3_eligible(runs)
    assert out == {"A"}  # B fails VIP latency once; C gap <900s; D not public

def test_tier3_speed_floor():
    runs = [run(0, {"E": rec(spd=2.0)}), run(2000, {"E": rec()})]
    assert compose.tier3_eligible(runs) == set()

# --- recent_pass -----------------------------------------------------

def test_recent_pass_window():
    runs = [run(t, {}) for t in (0, 100, 200, 300, 400)]
    runs[2]["passes"]["K"] = rec()
    runs[0]["passes"]["OLD"] = rec()
    assert compose.recent_pass(runs, "K", 3) is True
    assert compose.recent_pass(runs, "OLD", 3) is False

# --- exclusions --------------------------------------------------------

def test_quarantine_lifecycle():
    runs = [run(1000, {}), run(3000, {"K": rec()})]
    fb = {"K": {"works": 0, "dead": 1, "dead_ts": 2000}}
    assert compose.key_quarantined(fb, runs, "K") is False  # re-passed after
    runs2 = [run(1000, {}), run(1500, {"K": rec()})]
    assert compose.key_quarantined(fb, runs2, "K") is True
    assert compose.key_quarantined({}, runs, "K") is False

def test_fill_exclusions():
    runs = [run(1000, {}), run(3000, {"K": rec(), "H": rec()})]
    fb = {"K": {"works": 0, "dead": 1, "dead_ts": 2000}}
    # Dead-feedbacked: excluded from fill tiers even though the
    # quarantine itself lifted on re-verification.
    assert compose.fill_excluded(fb, runs, "K", item("K", "US")) is True
    # Hysteria2 excluded until field-verified.
    assert compose.fill_excluded(fb, runs, "H",
                                 item("H", "DE", "hysteria2", works=0)) is True
    assert compose.fill_excluded(fb, runs, "H",
                                 item("H", "DE", "hysteria2", works=3)) is False
    # Clean key passes.
    assert compose.fill_excluded(fb, runs, "X", item("X", "FR")) is False
    # A single-network failure OBSERVATION (FF5 style: obs entry, dead
    # untouched) does not exclude.
    fb2 = {"V": {"works": 3, "dead": 0,
                 "obs": [{"net": "adsl", "result": "fail"}]}}
    assert compose.fill_excluded(fb2, runs, "V", item("V", "US")) is False


# --- Gate-IR composer gating (R6.1) ------------------------------------

def test_ir_tier1_admission():
    assert compose.ir_tier1_ok(item("A", "US")) is False       # neutral: no
    assert compose.ir_tier1_ok({**item("A", "US"), "ir": True}) is True
    assert compose.ir_tier1_ok({**item("A", "US"), "ir": False}) is False
    # Field truth overrides the probe node, even an IR-false verdict.
    assert compose.ir_tier1_ok({**item("A", "US"), "ir": False,
                                "works": 3}) is True
    assert compose.ir_tier1_ok({**item("A", "US"), "works": 3}) is True

def test_ir_fill_accepts_true_or_neutral_never_false():
    assert compose.ir_fill_ok(item("A", "US")) is True
    assert compose.ir_fill_ok({**item("A", "US"), "ir": True}) is True
    assert compose.ir_fill_ok({**item("A", "US"), "ir": False}) is False

def test_fill_excluded_ir_false():
    runs = [run(1000, {}), run(3000, {"K": rec()})]
    assert compose.fill_excluded({}, runs, "K",
                                 {**item("K", "US"), "ir": False}) is True
    assert compose.fill_excluded({}, runs, "K",
                                 {**item("K", "US"), "ir": None}) is False


def test_fill_bootstraps_from_empty_pool():
    # Regression (live 2026-11-20): Tier 1 empty (Gate-IR neutral
    # cycle) — the fill must be able to start from zero. The old
    # instantaneous-pool ceiling deadlocked (first add = 1-of-1).
    cands = [item("a", "US"), item("b", "NL"), item("c", "DE"),
             item("d", "CA"), item("e", "FR"), item("f", "SE"),
             item("g", "PL"), item("h", "GB")]
    pool, added = compose.fill_to_floor([], cands, 8)
    assert added == 8 and len(pool) == 8

_PROTOS = ["ss", "vmess", "vless", "trojan", "hysteria2"]


def _sel_item(key, country, pc, source=None, proto_i=0):
    # Protocols cycle so the per_protocol=3 prod cap never binds in
    # the fixture (real pools are protocol-mixed too); ranking is
    # driven by pass_count alone.
    return {"key_hash": key, "country": country,
            "protocol": _PROTOS[proto_i % len(_PROTOS)],
            "host": "h-" + key, "service": "svc-" + key,
            "source": source or ("src-" + key), "port": 443,
            "front": 2, "works": 0, "pass_count": pc,
            "speed_mbps": 3.0, "latency_ms": 300.0}


def test_select_caps_second_country_constructively():
    # Regression test for the 2026-11-24 20:25 thin public pool:
    # with the old select() (no per-country cap in the non-majority
    # phase) the second country took 4 of 5 slots and the delete-only
    # safety net trimmed 3 good configs away (served 2 of 172
    # qualifying). With the constructive floor(cap/2) cap the same
    # ranked shape serves all 5 and the safety net drops nothing.
    items = [_sel_item("nl%d" % i, "NL", 100 - i) for i in range(4)]
    items += [_sel_item("de%d" % i, "DE", 90 - i) for i in range(2)]
    items += [_sel_item("pl0", "PL", 80)]
    items += [_sel_item("jp0", "JP", 70)]
    items += [_sel_item("us%d" % i, "US", 60 - i) for i in range(10)]
    for j, it in enumerate(items):
        it["protocol"] = _PROTOS[j % len(_PROTOS)]
    chosen, majority = compose.select(items, 5, 0.60, 2, 3, 2, 1,
                                      per_service=2)
    assert majority == "US"
    from collections import Counter
    counts = Counter(c["country"] for c in chosen)
    assert len(chosen) == 5
    assert max(counts.values()) <= 2
    kept, dropped = compose.enforce_country_ceiling(chosen)
    assert dropped == 0 and len(kept) == 5


def test_select_single_country_waives_ceiling():
    # Single-country supply: the ceiling is unsatisfiable and the
    # set serves as-is (standing select() philosophy, same as
    # fill_to_floor) — the per-country cap must not starve it to 2.
    items = [_sel_item("us%d" % i, "US", 60 - i) for i in range(10)]
    for j, it in enumerate(items):
        it["protocol"] = _PROTOS[j % len(_PROTOS)]
    chosen, majority = compose.select(items, 5, 0.60, 2, 3, 2, 1,
                                      per_service=2)
    assert majority == "US"
    assert len(chosen) == 5
    cands = ([item("u%d" % i, "US") for i in range(6)]
             + [item("n0", "NL"), item("d0", "DE"),
                item("c0", "CA"), item("f0", "FR")])
    pool, added = compose.fill_to_floor([], cands, 8)
    assert len(pool) == 8
    assert sum(1 for c in pool if c["country"] == "US") <= 4


# --- Rescue-post rule (wolf, 2026-11-20) ------------------------------
# Rescue configs NEVER go in the channel post any more. When one is
# deleted, its removal is announced by reply in the same chat. The
# composer reports the deletion in pool_json["rescue_removed"].

def run(ts, passes):
    return {"id": "r%d" % ts, "ts": ts, "passes": passes}


def test_rescue_removed_dead_report_with_no_repass():
    prev = [{"key": "K1", "remark": "R1"}, {"key": "K2", "remark": "R2"}]
    # K1: dead report, never re-passed. K2: dead report, re-passed
    # in the latest run (quarantine lifted) and still serving.
    fb = {"K1": {"dead": 1, "dead_ts": 1500},
          "K2": {"dead": 1, "dead_ts": 1500}}
    runs = [run(1000, {}), run(2000, {"K2": {}})]
    out = compose.rescue_removed(prev, {"K2"}, fb, runs)
    assert [r["key"] for r in out] == ["K1"]


def test_rescue_removed_no_pass_in_any_run():
    prev = [{"key": "K1", "remark": "R1"}]
    # No dead report, but no Gate-3 pass in any of this compose's
    # runs — it genuinely failed (rescue keys are profile-stratum,
    # sampled in full every cycle).
    runs = [run(1000, {"X": {}}), run(2000, {"Y": {}})]
    out = compose.rescue_removed(prev, set(), {}, runs)
    assert [r["key"] for r in out] == ["K1"]


def test_rescue_removed_not_when_still_serving_or_alive():
    prev = [{"key": "K1", "remark": "R1"}, {"key": "K2", "remark": "R2"},
            {"key": "K3", "remark": "R3"}]
    # K1 still serves. K2 passed in the latest run (alive, just not
    # picked this hour). K3 has no pass anywhere -> removed.
    runs = [run(1000, {"K2": {}}), run(2000, {"K2": {}})]
    out = compose.rescue_removed(prev, {"K1"}, {}, runs)
    assert [r["key"] for r in out] == ["K3"]


def test_load_prev_rescue_parses_uris_to_keys():
    import json, tempfile, os
    uri = ("vless://11111111-2222-3333-4444-555555555555"
           "@node.example.com:443?security=tls#x")
    pool = {"rescue": [{"uri": uri, "remark": "R1"},
                       {"uri": "not-a-uri", "remark": "BAD"}]}
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "prev_public_pool.json")
        json.dump(pool, open(p, "w"))
        orig = compose.BASE
        compose.BASE = d
        try:
            out = compose.load_prev_rescue()
        finally:
            compose.BASE = orig
    assert len(out) == 1
    assert out[0]["remark"] == "R1"
    assert len(out[0]["key"]) == 64


# --- Fill profile gate (field iteration 3, FF6) -------------------------
# The fill tiers admit only the field-proven profile. Since the
# 2026-11-20 restructure the SAME gate (compose.profile_reason)
# binds Tier 1 as well — see the restructure tests at the bottom.

def pitem(key, front, port, works=0, protocol="vless"):
    it = item(key, "US", protocol=protocol, works=works)
    it.update({"front": front, "port": port})
    return it

def test_fill_profile_fronted_classes_always_allowed():
    assert compose.fill_profile_ok(pitem("a", 0, 443)) is True
    assert compose.fill_profile_ok(pitem("b", 1, 443)) is True
    assert compose.fill_profile_ok(pitem("c", 0, 8443)) is True  # ladder
    assert compose.fill_profile_ok(pitem("d", 1, 2053)) is True  # ladder

def test_fill_profile_ss_needs_443_or_field_verified():
    assert compose.fill_profile_ok(pitem("a", 2, 443, protocol="ss")) is True
    # The FF6 deaths: plain SS on :19999, not field-verified.
    assert compose.fill_profile_reason(
        pitem("b", 2, 19999, protocol="ss")) == "ss_off_443"
    # ... but the field-proven SS@19999 (works=3, FF3/FF4) still fills.
    assert compose.fill_profile_ok(
        pitem("c", 2, 19999, works=3, protocol="ss")) is True
    # Endpoint credit: a young key on a field-verified host:port
    # (the task's "host:port that is itself field-verified" clause).
    young = pitem("d", 2, 19999, works=0, protocol="ss")
    young["endpoint_works"] = 3
    assert compose.fill_profile_ok(young) is True
    # Endpoint credit does NOT extend to REALITY or odd ports —
    # those exceptions are per specific key only.
    real = pitem("e", 3, 443, works=0)
    real["endpoint_works"] = 5
    assert compose.fill_profile_reason(real) == "reality_not_field_verified"
    odd = pitem("f", 0, 1270, works=0)
    odd["endpoint_works"] = 5
    assert compose.fill_profile_reason(odd) == "nonstandard_port"

def test_fill_profile_reality_excluded_unless_field_verified():
    # The FF6 VLESS ws/REALITY death (front 3) and bare REALITY (4).
    assert compose.fill_profile_reason(
        pitem("a", 3, 443)) == "reality_not_field_verified"
    assert compose.fill_profile_reason(
        pitem("b", 4, 443)) == "reality_not_field_verified"
    assert compose.fill_profile_ok(pitem("c", 3, 443, works=3)) is True
    assert compose.fill_profile_ok(pitem("d", 4, 8443, works=4)) is True

def test_fill_profile_nonstandard_port_excluded_unless_field_verified():
    # The FF6 :1270 case — refused for every class, fronted included.
    assert compose.fill_profile_reason(
        pitem("a", 0, 1270)) == "nonstandard_port"
    assert compose.fill_profile_reason(
        pitem("b", 1, 8888)) == "nonstandard_port"
    assert compose.fill_profile_ok(pitem("c", 0, 1270, works=3)) is True

def test_fill_profile_other_classes_need_field_verified():
    assert compose.fill_profile_reason(
        pitem("a", 5, 443)) == "class_not_field_verified"
    assert compose.fill_profile_ok(pitem("b", 5, 443, works=3)) is True
    assert compose.fill_profile_reason(
        pitem("c", None, 443)) == "class_not_field_verified"


# --- Iran-latency ranking (field iteration 3) ---------------------------
# compose.rank_items is the module-level ranking main() delegates to.

def _ritem(key, works=0, front=0, ir_lat=None, lat=300.0):
    return {"key_hash": key, "works": works, "front": front,
            "ir_latency_ms": ir_lat, "source": "src", "pass_count": 3,
            "speed_mbps": 3.0, "latency_ms": lat}

def test_ir_latency_orders_within_front_class():
    items = [_ritem("slow", ir_lat=900.0), _ritem("fast", ir_lat=120.0),
             _ritem("mid", ir_lat=450.0)]
    out = compose.rank_items(items)
    assert [i["key_hash"] for i in out] == ["fast", "mid", "slow"]

def test_ir_latency_missing_is_neutral_not_penalty():
    # Unmeasured sorts after measured ones in the same class, but a
    # missing latency never crosses the field-verified tier or the
    # front-class order.
    items = [_ritem("unmeasured", ir_lat=None),
             _ritem("measured", ir_lat=800.0)]
    out = compose.rank_items(items)
    assert [i["key_hash"] for i in out] == ["measured", "unmeasured"]
    items = [_ritem("fv_unmeasured", works=3, ir_lat=None),
             _ritem("plain_measured", works=0, ir_lat=50.0)]
    out = compose.rank_items(items)
    assert out[0]["key_hash"] == "fv_unmeasured"  # tier still leads
    items = [_ritem("front1_fast", front=1, ir_lat=50.0),
             _ritem("front0_slow", front=0, ir_lat=900.0)]
    out = compose.rank_items(items)
    assert out[0]["key_hash"] == "front0_slow"  # class still leads

def test_ir_latency_absent_field_behaves_like_missing():
    # Items built before the verifier emitted ir_latency_ms have no
    # such key at all — ranking must not crash and must stay neutral.
    a = _ritem("a", ir_lat=100.0)
    b = _ritem("b")
    del b["ir_latency_ms"]
    out = compose.rank_items([b, a])
    assert [i["key_hash"] for i in out] == ["a", "b"]


# --- Freshness core + hard profile + ceiling escape (2026-11-20) ------
# The restructure: Tier 1 admits passes in BOTH of the 2 freshest
# runs at VIP floors (triple-pass = ranking precedence only); the
# field profile binds every tier; the country ceiling yields — only
# to reach the floor, and logged — when it alone blocks the floor.

def test_core_needs_passes_in_two_freshest_runs():
    runs = [run(0, {"A": rec(), "B": rec(), "C": rec()}),
            run(1000, {"A": rec(), "B": rec(lat=600.0)}),
            run(2000, {"A": rec(), "C": rec()})]
    # Freshest two are ts 1000/2000: A is in both at floors; B missed
    # the latest run; C missed the middle one. A triple-pass over the
    # older window no longer admits on its own.
    assert compose.vip_core_eligible(runs) == {"A"}

def test_core_floors_must_hold_in_both_runs():
    runs = [run(0, {}), run(1000, {"A": rec(spd=2.0)}),
            run(2000, {"A": rec()})]
    assert compose.vip_core_eligible(runs) == set()

def test_core_single_run_admits_nothing():
    assert compose.vip_core_eligible([run(0, {"A": rec()})]) == set()

def test_profile_gate_is_one_function_for_all_tiers():
    assert compose.profile_reason is compose.fill_profile_reason
    # A Tier-1-shaped candidate (fresh passes, REALITY class) is
    # refused by the same gate that binds the fill tiers.
    assert compose.profile_reason(
        pitem("t1", 3, 443)) == "reality_not_field_verified"
    assert compose.profile_reason(pitem("t1", 0, 443)) is None

def test_triple_pass_ranks_first_inside_the_core():
    plain = _ritem("plain")
    triple = _ritem("triple")
    triple["triple"] = True
    out = compose.rank_items([plain, triple])
    assert out[0]["key_hash"] == "triple"
    # ... but the field-verified tier still outranks triple-pass.
    fv = _ritem("fv", works=3)
    out = compose.rank_items([triple, fv])
    assert out[0]["key_hash"] == "fv"

def _esc_item(key, country, service=None, host=None):
    return {"key_hash": key, "country": country,
            "service": service or ("svc-" + key),
            "host": host or ("host-" + key)}

def test_ceiling_escape_reaches_floor_despite_monoculture():
    pool = [_esc_item("a", "CA")]
    stream = [_esc_item("u%d" % i, "US") for i in range(7)]
    pool, added = compose.ceiling_escape(pool, stream, 8)
    assert len(pool) == 8 and added == 7
    us = sum(1 for c in pool if c["country"] == "US")
    assert us * 2 > len(pool)  # ceiling knowingly exceeded, to floor

def test_ceiling_escape_never_exceeds_floor():
    pool = [_esc_item("a", "CA")]
    stream = [_esc_item("u%d" % i, "US") for i in range(20)]
    pool, added = compose.ceiling_escape(pool, stream, 8)
    assert len(pool) == 8 and added == 7

def test_ceiling_escape_respects_service_and_host_caps():
    stream = [_esc_item("s%d" % i, "US", service="one-service")
              for i in range(8)]
    pool, added = compose.ceiling_escape([], stream, 8)
    assert added == 4  # per-service cap still binds under the escape
    stream = [_esc_item("h%d" % i, "US", host="one-host")
              for i in range(8)]
    pool, added = compose.ceiling_escape([], stream, 8)
    assert added == 2  # per-host cap still binds under the escape

def test_ceiling_escape_skips_served_keys():
    pool = [_esc_item("a", "CA"), _esc_item("u0", "US")]
    stream = [_esc_item("u0", "US"), _esc_item("u1", "US")]
    pool, added = compose.ceiling_escape(pool, stream, 3)
    assert added == 1 and len(pool) == 3

def test_post_label_is_flag_country_protocol_only():
    c = {"country": "DE", "protocol": "vless",
         "remark": "🪼 PROXIV3 · 🇩🇪 DE · VLESS · Verified"}
    assert compose.post_label(c) == "🇩🇪 DE · VLESS"
    legacy = {"remark": "🪼 PROXIV3 · 🇳🇱 NL · SS · Verified"}
    assert compose.post_label(legacy) == "🇳🇱 NL · SS"


def test_public_pool_changed_uses_snapshot_and_fails_open():
    import run_compose
    new = '{"configs": [1]}'
    assert run_compose.public_pool_changed({"configs": [1]}, new) is False
    assert run_compose.public_pool_changed({"configs": [2]}, new) is True
    assert run_compose.public_pool_changed(None, new) is True
    assert run_compose.public_pool_changed({"configs": [1]}, "not json") is True


def test_pool_counts_empty_is_zero():
    import base64 as _b64
    import run_compose
    assert run_compose.pool_counts('{"configs": []}', "") == (0, 0)
    sub = _b64.b64encode(b"a\nb\n").decode()
    assert run_compose.pool_counts('{"configs": [1]}', sub) == (1, 2)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print(len(fns), "tests passed")
