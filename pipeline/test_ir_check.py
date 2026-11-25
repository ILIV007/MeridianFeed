#!/usr/bin/env python3
"""Unit tests for pipeline/ir_check.py (Gate-IR, Plan Rev.2 R6.1).

Fake probes only — no network. The properties under test are the
verdict discipline: a success wins immediately; an unreachable
verdict needs two agreeing failures; anything inconclusive stays
neutral; failed controls neutralise the whole stage.

Run: python3 -m unittest pipeline.test_ir_check
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ir_check  # noqa: E402


def scripted(*results):
    """A probe returning the scripted results in order, then None."""
    queue = list(results)
    calls = []

    def probe(host, port):
        calls.append((host, port))
        return queue.pop(0) if queue else None

    probe.calls = calls
    return probe


class VerdictTests(unittest.TestCase):
    def test_first_success_wins_without_confirmation(self):
        ch = scripted(True)
        gp = scripted(False)
        self.assertIs(ir_check.endpoint_verdict("h", 443, ch, gp), True)
        self.assertEqual(len(gp.calls), 0)  # second opinion not needed

    def test_fail_then_retry_success_is_reachable(self):
        ch = scripted(False, True)
        self.assertIs(ir_check.endpoint_verdict("h", 443, ch,
                                                scripted()), True)

    def test_two_agreeing_failures_condemn(self):
        ch = scripted(False, False)
        self.assertIs(ir_check.endpoint_verdict("h", 443, ch,
                                                scripted()), False)

    def test_fail_retry_error_globalping_fail_agrees(self):
        ch = scripted(False, None)
        gp = scripted(False)
        self.assertIs(ir_check.endpoint_verdict("h", 443, ch, gp), False)

    def test_fail_retry_error_globalping_success_overrides(self):
        ch = scripted(False, None)
        gp = scripted(True)
        self.assertIs(ir_check.endpoint_verdict("h", 443, ch, gp), True)

    def test_fail_with_no_confirmation_available_is_neutral(self):
        ch = scripted(False, None)
        gp = scripted(None)
        self.assertIsNone(ir_check.endpoint_verdict("h", 443, ch, gp))

    def test_check_host_down_globalping_success_proves(self):
        ch = scripted(None)
        gp = scripted(True)
        self.assertIs(ir_check.endpoint_verdict("h", 443, ch, gp), True)

    def test_check_host_down_globalping_fail_never_condemns(self):
        ch = scripted(None)
        gp = scripted(False)
        self.assertIsNone(ir_check.endpoint_verdict("h", 443, ch, gp))

    def test_everything_down_is_neutral(self):
        self.assertIsNone(ir_check.endpoint_verdict(
            "h", 443, scripted(None), scripted(None)))


class ControlsTests(unittest.TestCase):
    def test_controls_ok(self):
        ch = scripted(True, False)
        self.assertTrue(ir_check.controls_ok(ch))

    def test_positive_control_failure_neutralises(self):
        self.assertFalse(ir_check.controls_ok(scripted(False, False)))
        self.assertFalse(ir_check.controls_ok(scripted(None, False),
                                              gp=scripted()))

    def test_negative_control_success_neutralises(self):
        self.assertFalse(ir_check.controls_ok(scripted(True, True)))
        self.assertFalse(ir_check.controls_ok(scripted(True, None)))

    def test_controls_retry_recovers_from_transient_hiccup(self):
        ch = scripted(None, False, True, False)
        self.assertTrue(ir_check.controls_ok(ch))
        self.assertEqual(ir_check.LAST_CONTROLS["attempts"], 2)
        self.assertIs(ir_check.LAST_CONTROLS["positive"], True)
        self.assertIs(ir_check.LAST_CONTROLS["negative"], False)

    def test_controls_stay_failed_after_both_attempts(self):
        self.assertFalse(ir_check.controls_ok(scripted(None, None),
                                              gp=scripted()))
        self.assertEqual(ir_check.LAST_CONTROLS["attempts"], 2)

    def test_controls_fall_back_to_globalping_when_checkhost_silent(self):
        gp = scripted(True, False)
        self.assertTrue(ir_check.controls_ok(scripted(None, None), gp=gp))
        self.assertEqual(ir_check.LAST_CONTROLS["via"], "globalping")
        # Globalping cannot create measurements for unroutable
        # targets, so its negative control is the dead-port variant.
        self.assertEqual(gp.calls[0], ir_check.POSITIVE_CONTROL)
        self.assertEqual(gp.calls[1], ir_check.GP_NEGATIVE_CONTROL)

    def test_globalping_controls_must_also_behave(self):
        self.assertFalse(ir_check.controls_ok(
            scripted(None, None), gp=scripted(True, True)))
        self.assertFalse(ir_check.controls_ok(
            scripted(None, None), gp=scripted(None, False)))

    def test_real_checkhost_verdict_failure_is_never_overridden(self):
        gp = scripted(True, False)
        self.assertFalse(ir_check.controls_ok(scripted(False, False),
                                              gp=gp))
        self.assertEqual(len(gp.calls), 0)


class AnnotateTests(unittest.TestCase):
    def test_failed_controls_make_everything_neutral(self):
        targets = {"k1": ("a.example", 443), "k2": ("b.example", 8443)}
        verdicts, stage, counts = ir_check.annotate(
            targets, ch=scripted(True), gp=scripted(), controls=False)
        self.assertEqual(stage, "neutral_controls")
        self.assertEqual(verdicts, {"k1": None, "k2": None})
        self.assertEqual(counts["neutral"], 2)
        self.assertIn("controls", counts)

    def test_counts_carry_control_verdicts(self):
        targets = {"k1": ("203.0.113.7", 443)}
        ch = scripted(True, False, True)  # controls pair, then verdict
        verdicts, stage, counts = ir_check.annotate(
            targets, ch=ch, gp=scripted())
        self.assertEqual(stage, "ok")
        self.assertEqual(counts["controls"]["attempts"], 1)
        self.assertIs(counts["controls"]["positive"], True)

    def test_verdicts_cached_per_endpoint(self):
        # Endpoint probes in order: same.example succeeds at once;
        # other.example fails once, retry is inconclusive -> neutral.
        ch = scripted(True, False)
        targets = {"k1": ("same.example", 443),
                   "k2": ("same.example", 443),
                   "k3": ("other.example", 443)}
        verdicts, stage, _ = ir_check.annotate(
            targets, ch=ch, gp=scripted(),
            controls=True)
        self.assertEqual(stage, "ok")
        self.assertIs(verdicts["k1"], True)
        self.assertIs(verdicts["k2"], True)   # shared endpoint verdict
        self.assertIsNone(verdicts["k3"])     # unscripted -> neutral

    def test_mute_check_host_is_skipped_per_endpoint(self):
        # check-host returns no verdict at all: controls pass via the
        # Globalping fallback, and the endpoint stage must not retry
        # check-host (it would only burn the budget). A lone
        # Globalping failure still cannot condemn.
        ch = scripted(None, None, None, None)
        gp = scripted(True, False, False)  # controls pair, then endpoint
        targets = {"k1": ("203.0.113.7", 443)}
        verdicts, stage, counts = ir_check.annotate(
            targets, ch=ch, gp=gp)
        self.assertEqual(stage, "ok")
        self.assertTrue(counts["check_host_mute"])
        self.assertEqual(len(ch.calls), 4)  # controls only
        self.assertIsNone(verdicts["k1"])

    def test_empty_targets_ok(self):
        verdicts, stage, counts = ir_check.annotate(
            {}, ch=scripted(), gp=scripted())
        self.assertEqual((verdicts, stage), ({}, "ok"))
        self.assertEqual(counts["endpoints"], 0)


def scripted_ping(*results):
    """A ping probe (host-only signature) returning scripted results."""
    queue = list(results)
    calls = []

    def probe(host):
        calls.append(host)
        return queue.pop(0) if queue else None

    probe.calls = calls
    return probe


class LatencyTests(unittest.TestCase):
    """Iran-side ping latency (field iteration 3): a ranking signal
    only — present values pass through, missing stays None, and the
    measurement can never fail the stage or touch a verdict."""

    def test_endpoint_latency_prefers_globalping(self):
        gp = scripted_ping(123.0)
        ch = scripted_ping(45.0)
        self.assertEqual(ir_check.endpoint_latency("h", gp=gp, ch=ch),
                         123.0)
        self.assertEqual(len(ch.calls), 0)

    def test_endpoint_latency_falls_back_to_check_host(self):
        self.assertEqual(ir_check.endpoint_latency(
            "h", gp=scripted_ping(None), ch=scripted_ping(45.0)), 45.0)

    def test_endpoint_latency_unmeasurable_is_none(self):
        self.assertIsNone(ir_check.endpoint_latency(
            "h", gp=scripted_ping(None), ch=scripted_ping(None)))

    def test_annotate_with_latency_measures_per_host(self):
        seen = []

        def ping(host):
            seen.append(host)
            return {"a.example": 111.0}.get(host)

        targets = {"k1": ("a.example", 443), "k2": ("a.example", 8443),
                   "k3": ("b.example", 443)}
        out = ir_check.annotate_with_latency(targets, ping=ping)
        self.assertEqual(out, {"k1": 111.0, "k2": 111.0, "k3": None})
        self.assertEqual(sorted(seen), ["a.example", "b.example"])

    def test_annotate_with_latency_reuses_earlier_measurements(self):
        def ping(host):
            raise AssertionError("must not re-measure")

        targets = {"k1": ("a.example", 443)}
        out = ir_check.annotate_with_latency(
            targets, latencies={"k1": 88.0}, ping=ping)
        self.assertEqual(out, {"k1": 88.0})

    def test_annotate_with_latency_probe_errors_stay_neutral(self):
        def ping(host):
            raise RuntimeError("API down")

        out = ir_check.annotate_with_latency(
            {"k1": ("a.example", 443)}, ping=ping)
        self.assertEqual(out, {"k1": None})

    def test_annotate_with_latency_empty_targets(self):
        self.assertEqual(ir_check.annotate_with_latency({}, ping=None),
                         {})


class AtlasVerdictTests(unittest.TestCase):
    """The third opinion (RIPE Atlas): it can confirm a failure or
    prove reachability, but — exactly like Globalping — its failure
    alone never condemns."""

    def test_atlas_and_globalping_failures_agree_condemn(self):
        ch = scripted(None)          # check-host silent
        gp = scripted(False)
        at = scripted(False)
        self.assertIs(ir_check.endpoint_verdict("h", 443, ch, gp, at),
                      False)

    def test_atlas_failure_alone_is_neutral(self):
        ch = scripted(None)
        gp = scripted(None)
        at = scripted(False)
        self.assertIsNone(ir_check.endpoint_verdict("h", 443, ch, gp, at))

    def test_atlas_confirms_checkhost_failure(self):
        ch = scripted(False, None)   # one failure, retry inconclusive
        gp = scripted(None)
        at = scripted(False)
        self.assertIs(ir_check.endpoint_verdict("h", 443, ch, gp, at),
                      False)

    def test_atlas_success_proves_reachability(self):
        ch = scripted(False, None)
        gp = scripted(None)
        at = scripted(True)
        self.assertIs(ir_check.endpoint_verdict("h", 443, ch, gp, at),
                      True)

    def test_two_failures_condemn_before_later_opinions(self):
        # Sequential discipline (same as the check-host/Globalping
        # precedent): once two failures agree, the verdict is False
        # and later opinions are not consulted.
        ch = scripted(False, None)
        gp = scripted(False)
        at = scripted(True)
        self.assertIs(ir_check.endpoint_verdict("h", 443, ch, gp, at),
                      False)
        self.assertEqual(len(at.calls), 0)

    def test_atlas_silent_without_key(self):
        saved = os.environ.pop("RIPE_ATLAS_KEY", None)
        try:
            self.assertIsNone(ir_check.probe_atlas("1.1.1.1", 443))
        finally:
            if saved is not None:
                os.environ["RIPE_ATLAS_KEY"] = saved

    def test_atlas_census_parses_count(self):
        ir_check._ATLAS_CENSUS.update({"done": False, "count": None})
        real = ir_check._http_json
        ir_check._http_json = lambda url, **kw: {"count": 89}
        try:
            self.assertEqual(ir_check.atlas_census(), 89)
        finally:
            ir_check._http_json = real
            ir_check._ATLAS_CENSUS.update({"done": False, "count": None})


class _FakeTime:
    """monotonic() that advances on every call so poll loops exit."""

    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        self.t += 7.0
        return self.t

    def sleep(self, seconds):
        self.t += seconds


class MultiNodeProbeTests(unittest.TestCase):
    """probe_check_host aggregates the Iranian nodes of ONE request:
    any success wins; >= 2 node failures condemn; sparse reports are
    inconclusive."""

    NODES = ["ir1.node.check-host.net", "ir2.node.check-host.net",
             "ir3.node.check-host.net", "ir6.node.check-host.net"]

    def _run_probe(self, result):
        real_http, real_time = ir_check._http_json, ir_check.time
        state = {"created": False}

        def fake_http(url, **kw):
            if "check-tcp" in url:
                state["created"] = True
                return {"request_id": "r1"}
            return result

        ir_check._http_json = fake_http
        ir_check.time = _FakeTime()
        try:
            return ir_check.probe_check_host("203.0.113.7", 443,
                                             nodes=self.NODES)
        finally:
            ir_check._http_json, ir_check.time = real_http, real_time

    def test_any_node_success_is_reachable(self):
        result = {self.NODES[0]: [[{"error": "timeout"}]],
                  self.NODES[1]: [[{"time": 0.05}]]}
        self.assertIs(self._run_probe(result), True)

    def test_two_node_failures_condemn(self):
        result = {self.NODES[0]: [[{"error": "timeout"}]],
                  self.NODES[2]: [[{"error": "refused"}]]}
        self.assertIs(self._run_probe(result), False)

    def test_single_node_failure_is_inconclusive(self):
        result = {self.NODES[0]: [[{"error": "timeout"}]]}
        self.assertIsNone(self._run_probe(result))


class GlobalpingAggregationTests(unittest.TestCase):
    def _run_gp(self, results):
        real_http, real_time = ir_check._http_json, ir_check.time

        def fake_http(url, **kw):
            if url.endswith("/measurements"):
                return {"id": "m1"}
            return {"status": "finished", "results": results}

        ir_check._http_json = fake_http
        ir_check.time = _FakeTime()
        try:
            return ir_check.probe_globalping("203.0.113.7", 443)
        finally:
            ir_check._http_json, ir_check.time = real_http, real_time

    def test_one_probe_success_among_failures_wins(self):
        results = [{"result": {"status": "failed"}},
                   {"result": {"statusCode": 403}},
                   {"result": {"status": "failed"}}]
        self.assertIs(self._run_gp(results), True)

    def test_all_probes_failed_is_failure(self):
        results = [{"result": {"status": "failed"}},
                   {"result": {"status": "failed"}}]
        self.assertIs(self._run_gp(results), False)


if __name__ == "__main__":
    unittest.main()
