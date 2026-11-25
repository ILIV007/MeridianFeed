#!/usr/bin/env python3
"""Unit tests for pipeline/fetch_governance_state.py — the
governance-state artifact restore (2026-11-25).

API seams are stubbed at the module level (api_get / download_zip);
no network, no token. The live proof is two dispatched verify runs
after merge.

Run: python3 -m unittest pipeline.test_fetch_governance_state
"""
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_governance_state as fgs  # noqa: E402


def state_zip(state):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(fgs.STATE_FILENAME, json.dumps(state))
    return buf.getvalue()


GOOD_STATE = {"version": 1, "sources": {
    "a": {"unique_history": [3, 0], "lifetime_unique": 3,
          "disabled": False, "disabled_reason": None,
          "disabled_ts": None}}}


class FindLatestTests(unittest.TestCase):
    def _runs(self, *ids):
        return {"workflow_runs": [{"id": i} for i in ids]}

    def _arts(self, *names):
        return {"artifacts": [
            {"id": 100 + k, "name": n, "expired": False}
            for k, n in enumerate(names)]}

    def test_picks_newest_run_with_artifact(self):
        calls = []

        def fake_api(token, path):
            calls.append(path)
            if "workflows" in path:
                return self._runs(300, 299, 298)
            if "/runs/300/artifacts" in path:
                return self._arts("verify-stats-300")
            if "/runs/299/artifacts" in path:
                return self._arts("governance-state-299")
            return self._arts()

        with mock.patch.object(fgs, "api_get", side_effect=fake_api):
            run_id, art = fgs.find_latest(
                "tok", "o/r", "verify.yml", skip_run_id=None)
        self.assertEqual(run_id, 299)
        self.assertEqual(art["name"], "governance-state-299")

    def test_skips_current_run(self):
        def fake_api(token, path):
            if "workflows" in path:
                return self._runs(300, 299)
            if "/runs/300/artifacts" in path:
                return self._arts("governance-state-300")
            return self._arts("governance-state-299")

        with mock.patch.object(fgs, "api_get", side_effect=fake_api):
            run_id, art = fgs.find_latest(
                "tok", "o/r", "verify.yml", skip_run_id=300)
        self.assertEqual(run_id, 299)

    def test_expired_artifact_is_skipped(self):
        def fake_api(token, path):
            if "workflows" in path:
                return self._runs(300)
            return {"artifacts": [
                {"id": 1, "name": "governance-state-300",
                 "expired": True}]}

        with mock.patch.object(fgs, "api_get", side_effect=fake_api):
            self.assertEqual(
                fgs.find_latest("tok", "o/r", "verify.yml", None),
                (None, None))

    def test_no_artifact_anywhere(self):
        def fake_api(token, path):
            if "workflows" in path:
                return self._runs(300)
            return self._arts("verify-stats-300")

        with mock.patch.object(fgs, "api_get", side_effect=fake_api):
            self.assertEqual(
                fgs.find_latest("tok", "o/r", "verify.yml", None),
                (None, None))


class ExtractTests(unittest.TestCase):
    def test_valid_zip(self):
        self.assertEqual(fgs.extract_state(state_zip(GOOD_STATE)),
                         GOOD_STATE)

    def test_missing_file(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("other.json", "{}")
        with self.assertRaises(ValueError):
            fgs.extract_state(buf.getvalue())

    def test_wrong_shape(self):
        with self.assertRaises(ValueError):
            fgs.extract_state(state_zip({"not": "a state"}))


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, "governance-state.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_restore_writes_artifact_state(self):
        with mock.patch.object(
                fgs, "find_latest",
                return_value=(299, {"id": 7,
                                    "name": "governance-state-299"})), \
             mock.patch.object(
                fgs, "download_zip",
                return_value=state_zip(GOOD_STATE)):
            kind, detail = fgs.restore(self.out, token="tok")
        self.assertEqual(kind, "artifact")
        self.assertEqual(detail, 299)
        self.assertEqual(json.load(open(self.out)), GOOD_STATE)

    def test_no_token_is_fallback_not_failure(self):
        kind, _detail = fgs.restore(self.out, token=None)
        self.assertEqual(kind, "fallback")
        self.assertFalse(os.path.exists(self.out))

    def test_api_failure_is_fallback_not_failure(self):
        with mock.patch.object(
                fgs, "find_latest",
                side_effect=RuntimeError("boom")):
            kind, detail = fgs.restore(self.out, token="tok")
        self.assertEqual(kind, "fallback")
        self.assertIn("RuntimeError", detail)
        self.assertFalse(os.path.exists(self.out))

    def test_bad_zip_is_fallback_not_failure(self):
        with mock.patch.object(
                fgs, "find_latest",
                return_value=(299, {"id": 7,
                                    "name": "governance-state-299"})), \
             mock.patch.object(fgs, "download_zip",
                               return_value=b"not a zip"):
            kind, _detail = fgs.restore(self.out, token="tok")
        self.assertEqual(kind, "fallback")
        self.assertFalse(os.path.exists(self.out))

    def test_main_returns_zero_on_fallback(self):
        with mock.patch.object(
                fgs, "restore", return_value=("fallback", "no token")):
            self.assertEqual(
                fgs.main(["fetch_governance_state.py",
                          "--out", self.out]), 0)

    def test_main_usage_error(self):
        self.assertEqual(fgs.main(["fetch_governance_state.py"]), 2)


if __name__ == "__main__":
    unittest.main()
