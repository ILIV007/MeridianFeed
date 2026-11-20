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

    def test_empty_targets_ok(self):
        verdicts, stage, counts = ir_check.annotate(
            {}, ch=scripted(), gp=scripted())
        self.assertEqual((verdicts, stage), ({}, "ok"))
        self.assertEqual(counts["endpoints"], 0)


if __name__ == "__main__":
    unittest.main()
