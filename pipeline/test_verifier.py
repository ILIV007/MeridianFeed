#!/usr/bin/env python3
"""Unit tests for pipeline/verifier.py rebranding helpers.

Synthetic fixtures only — no real configs, no network. The key property:
rebranding is display-only, so the collector's record and dedup key for a
config must be identical before and after `rebrand_uri`.

Run: python3 -m unittest pipeline.test_verifier
"""
import base64
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collector  # noqa: E402
import verifier  # noqa: E402

UUID = "11111111-2222-3333-4444-555555555555"

FIXTURES = {
    "vless": "vless://%s@203.0.113.10:443?security=tls&sni=example.com"
             "&type=ws&path=/ws#old-name" % UUID,
    "trojan": "trojan://synthetic-pass@203.0.113.11:443?sni=example.com#old",
    "ss": "ss://%s@203.0.113.12:8388#old" % base64.b64encode(
        b"aes-256-gcm:synthetic-pass").decode(),
    "hysteria2": "hysteria2://synthetic-pass@203.0.113.13:443"
                 "?sni=example.com#old",
    "tuic": "tuic://%s:synthetic-pass@203.0.113.14:443?sni=example.com#old"
            % UUID,
}


def vmess_fixture():
    payload = {"v": "2", "ps": "old-name", "add": "203.0.113.15",
               "port": "443", "id": UUID, "aid": "0", "net": "ws",
               "type": "none", "host": "example.com", "path": "/ws",
               "tls": "tls", "sni": "example.com"}
    return "vmess://" + base64.b64encode(
        json.dumps(payload).encode()).decode()


class FormatRemarkTests(unittest.TestCase):
    def test_format(self):
        remark = verifier.format_remark("de", "vless")
        self.assertEqual(remark,
                         "\U0001FABC PROXIV3 · \U0001F1E9\U0001F1EA DE"
                         " · VLESS · Verified")
        self.assertTrue(remark.startswith("\U0001FABC PROXIV3"))
        self.assertTrue(remark.endswith("· Verified"))
        self.assertIn("\U0001F1E9\U0001F1EA DE", remark)
        self.assertIn("VLESS", remark)
        self.assertNotIn("ms", remark)
        # No latency digits may leak into the name (the "3" in PROXIV3
        # is part of the brand, not a measurement).
        self.assertFalse(any(ch.isdigit()
                             for ch in remark.replace("PROXIV3", "")))

    def test_unknown_country(self):
        remark = verifier.format_remark(None, "ss")
        self.assertTrue(remark.startswith("\U0001FABC PROXIV3 · \U0001F310"))
        self.assertIn("SS", remark)
        self.assertTrue(remark.endswith("· Verified"))


class RebrandTests(unittest.TestCase):
    def assert_display_only(self, uri):
        remark = verifier.format_remark("NL", "vless")
        before = collector.parse_uri(uri, "test")
        self.assertIsNotNone(before)
        after = collector.parse_uri(verifier.rebrand_uri(uri, remark), "test")
        self.assertEqual(before, after)
        self.assertEqual(collector.dedup_key(before),
                         collector.dedup_key(after))

    def test_all_protocols_display_only(self):
        for uri in FIXTURES.values():
            self.assert_display_only(uri)
        self.assert_display_only(vmess_fixture())

    def test_fragment_replaced_not_appended(self):
        out = verifier.rebrand_uri(FIXTURES["vless"], "NEW NAME")
        self.assertNotIn("old-name", out)
        self.assertTrue(out.endswith("#NEW%20NAME"))
        # Everything before the fragment is byte-identical.
        self.assertEqual(out.split("#", 1)[0],
                         FIXTURES["vless"].split("#", 1)[0])

    def test_vmess_ps_replaced_fields_intact(self):
        remark = verifier.format_remark("DE", "vmess")
        out = verifier.rebrand_uri(vmess_fixture(), remark)
        data = json.loads(base64.b64decode(out.partition("://")[2]))
        self.assertEqual(data["ps"], remark)
        self.assertEqual(data["add"], "203.0.113.15")
        self.assertEqual(data["id"], UUID)
        self.assertEqual(data["path"], "/ws")


if __name__ == "__main__":
    unittest.main()
