#!/usr/bin/env python3
"""Unit tests for governance.py — unique-yield auto-disable (R1).

Run: python3 -m unittest pipeline.test_governance
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import governance  # noqa: E402


def registry(*names):
    return [{"name": n, "enabled": True} for n in names]


def stats(name, unique, ok=True, stub=False):
    return {"name": name, "ok": ok, "unique_new": unique,
            "governance_disabled": stub}


def seed(state, name, history):
    state["sources"][name] = {
        "unique_history": list(history),
        "lifetime_unique": sum(history), "disabled": False,
        "disabled_reason": None, "disabled_ts": None}


class UpdateTests(unittest.TestCase):
    def test_only_successful_real_results_count(self):
        state = governance.empty_state()
        governance.update(state, [
            stats("a", 5), stats("b", 0, ok=False),
            stats("c", 0, stub=True)], ts=1.0)
        self.assertEqual(
            state["sources"]["a"]["unique_history"], [5])
        self.assertNotIn("b", state["sources"])
        self.assertNotIn("c", state["sources"])

    def test_history_clipped(self):
        state = governance.empty_state()
        seed(state, "a", [1] * governance.HISTORY_MAX)
        governance.update(state, [stats("a", 2)], ts=2.0)
        hist = state["sources"]["a"]["unique_history"]
        self.assertEqual(len(hist), governance.HISTORY_MAX)
        self.assertEqual(hist[-1], 2)


class DisableTests(unittest.TestCase):
    def test_disable_after_zero_rounds(self):
        state = governance.empty_state()
        names = ["dead", "s1", "s2", "s3", "s4"]
        seed(state, "dead", [0] * (governance.ZERO_ROUNDS - 1))
        for n in names[1:]:
            seed(state, n, [7] * governance.ZERO_ROUNDS)
        governance.update(state, [stats(n, 0 if n == "dead" else 3)
                                  for n in names], ts=3.0)
        newly = governance.apply_disables(state, registry(*names))
        self.assertEqual(list(newly), ["dead"])
        self.assertEqual(governance.disabled_names(state), {"dead"})

    def test_no_disable_before_window_fills(self):
        state = governance.empty_state()
        names = ["dead", "s1", "s2", "s3", "s4"]
        seed(state, "dead", [0] * (governance.ZERO_ROUNDS - 2))
        for n in names[1:]:
            seed(state, n, [7])
        governance.update(state, [stats("dead", 0)], ts=3.0)
        self.assertEqual(
            governance.apply_disables(state, registry(*names)), {})

    def test_nonzero_in_window_blocks_disable(self):
        state = governance.empty_state()
        names = ["dead", "s1", "s2", "s3", "s4"]
        seed(state, "dead", [0, 0, 3, 0, 0])
        for n in names[1:]:
            seed(state, n, [7])
        governance.update(state, [stats("dead", 0)], ts=3.0)
        self.assertEqual(
            governance.apply_disables(state, registry(*names)), {})

    def test_min_active_floor(self):
        state = governance.empty_state()
        names = ["d1", "d2", "s1", "s2", "s3"]
        for n in names:
            seed(state, n, [0] * governance.ZERO_ROUNDS
                 if n.startswith("d") else [5] * governance.ZERO_ROUNDS)
        # 5 active, floor 4 -> only ONE of the two dead may be disabled
        newly = governance.apply_disables(state, registry(*names))
        self.assertEqual(len(newly), 1)
        self.assertEqual(len(governance.disabled_names(state)), 1)

    def test_enable_roundtrip(self):
        state = governance.empty_state()
        seed(state, "dead", [0] * governance.ZERO_ROUNDS)
        state["sources"]["dead"]["disabled"] = True
        self.assertTrue(governance.enable(state, "dead"))
        self.assertEqual(governance.disabled_names(state), set())
        self.assertFalse(governance.enable(state, "dead"))


if __name__ == "__main__":
    unittest.main()
