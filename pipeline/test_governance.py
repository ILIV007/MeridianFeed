#!/usr/bin/env python3
"""Unit tests for governance.py — unique-yield auto-disable (R1).

Run: python3 -m unittest pipeline.test_governance
"""
import json
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


class RecordYieldTests(unittest.TestCase):
    """record_yield() — the artifact round-trip (2026-11-25): the
    working file is the previous run's artifact, the repo file is
    only the seed for the first run."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.seed_path = os.path.join(self.dir, "seed.json")
        self.state_path = os.path.join(self.dir, "state.json")
        self.names = ["dead", "s1", "s2", "s3", "s4"]
        seed_state = governance.empty_state()
        for n in self.names:
            seed(seed_state, n, [3])
        governance.save(self.seed_path, seed_state)
        self.registry_path = os.path.join(self.dir, "sources.json")
        with open(self.registry_path, "w") as handle:
            json.dump({"sources": registry(*self.names)}, handle)

    def tearDown(self):
        self.tmp.cleanup()

    def _stats(self, zero_name="dead"):
        return [stats(n, 0 if n == zero_name else 5)
                for n in self.names]

    def test_first_run_loads_seed_and_writes_working_file(self):
        state, newly, loaded = governance.record_yield(
            self.state_path, self.seed_path, self._stats(),
            self.registry_path, ts=1.0)
        self.assertEqual(loaded, "seed")
        self.assertEqual(newly, {})
        self.assertTrue(os.path.exists(self.state_path))
        reloaded = governance.load(self.state_path)
        self.assertEqual(
            reloaded["sources"]["dead"]["unique_history"], [3, 0])
        self.assertEqual(
            reloaded["sources"]["s1"]["unique_history"], [3, 5])

    def test_second_run_loads_artifact_and_accumulates(self):
        governance.record_yield(
            self.state_path, self.seed_path, self._stats(),
            self.registry_path, ts=1.0)
        state, newly, loaded = governance.record_yield(
            self.state_path, self.seed_path, self._stats(),
            self.registry_path, ts=2.0)
        self.assertEqual(loaded, "artifact")
        self.assertEqual(
            state["sources"]["dead"]["unique_history"], [3, 0, 0])

    def test_disable_fires_after_six_zero_rounds(self):
        # Seed "dead" with 5 zeros already; the 6th zero (this
        # cycle) must disable it — the exact failure the frozen
        # repo seed made impossible.
        seed_state = governance.empty_state()
        for n in self.names:
            seed(seed_state, n, [0] * 5 if n == "dead" else [3])
        governance.save(self.seed_path, seed_state)
        _state, newly, _loaded = governance.record_yield(
            self.state_path, self.seed_path, self._stats(),
            self.registry_path, ts=1.0)
        self.assertEqual(list(newly), ["dead"])
        self.assertEqual(
            governance.disabled_names(governance.load(self.state_path)),
            {"dead"})

    def test_no_seed_no_working_file_starts_empty(self):
        missing_seed = os.path.join(self.dir, "no-seed.json")
        state, newly, loaded = governance.record_yield(
            self.state_path, missing_seed, self._stats(),
            self.registry_path, ts=1.0)
        self.assertEqual(loaded, "empty")
        self.assertEqual(newly, {})
        self.assertEqual(
            state["sources"]["dead"]["unique_history"], [0])

    def test_failed_fetch_is_not_a_sample(self):
        bad = [stats("dead", 0, ok=False)] + [
            stats(n, 5) for n in self.names[1:]]
        governance.record_yield(
            self.state_path, self.seed_path, bad,
            self.registry_path, ts=1.0)
        # The seeded history is untouched: a failed fetch appends
        # no zero sample (a network failure is not a yield
        # measurement, and must never count toward a disable).
        self.assertEqual(governance.load(
            self.state_path)["sources"]["dead"]["unique_history"], [3])

    def test_never_raises_on_bad_registry(self):
        state, newly, loaded = governance.record_yield(
            self.state_path, self.seed_path, self._stats(),
            registry_path="/nonexistent/registry.json", ts=1.0)
        self.assertEqual(loaded, "seed")
        self.assertEqual(newly, {})
        self.assertTrue(os.path.exists(self.state_path))


if __name__ == "__main__":
    unittest.main()
