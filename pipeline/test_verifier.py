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


class PassKeyTests(unittest.TestCase):
    def test_opaque_and_stable(self):
        record = collector.parse_uri(FIXTURES["vless"], "test")
        key = verifier.pass_key(record)
        self.assertEqual(len(key), 64)
        self.assertTrue(all(ch in "0123456789abcdef" for ch in key))
        # The key must not leak the server or the credential.
        self.assertNotIn("203.0.113.10", key)
        self.assertNotIn(UUID, key)
        # Stable across re-parses of the same config, and unchanged by
        # display-only rebranding.
        again = collector.parse_uri(FIXTURES["vless"], "other-source")
        self.assertEqual(verifier.pass_key(again), key)
        rebranded = collector.parse_uri(
            verifier.rebrand_uri(FIXTURES["vless"], "X"), "test")
        self.assertEqual(verifier.pass_key(rebranded), key)

    def test_distinct_configs_distinct_keys(self):
        keys = {verifier.pass_key(collector.parse_uri(uri, "test"))
                for uri in FIXTURES.values()}
        self.assertEqual(len(keys), len(FIXTURES))


class UriMapTests(unittest.TestCase):
    def test_map_covers_exactly_the_sample(self):
        pairs = [(collector.parse_uri(uri, "test"), uri)
                 for uri in FIXTURES.values()]
        mapping = verifier.build_uri_map(pairs)
        self.assertEqual(len(mapping), len(FIXTURES))
        for record, uri in pairs:
            self.assertEqual(mapping[verifier.pass_key(record)], uri)
        # Keys stay opaque (no server/credential leakage in key space).
        for key in mapping:
            self.assertEqual(len(key), 64)


class FinalmaskTests(unittest.TestCase):
    """Plan Rev.2 R2: the Xray finalmask outbound builder. Synthetic
    fixtures only — the live A/B runs on Actions."""

    VLESS_WS = ("vless://%s@edge.example.com:443?encryption=none"
                "&security=tls&sni=edge.example.com&type=ws"
                "&host=cdn.example.com&path=%%2Fws#x" % UUID)
    TROJAN_WS = ("trojan://secretpw@tr.example.com:8443?security=tls"
                 "&sni=tr.example.com&type=ws&path=%%2Ftj#x")

    def test_preset_is_the_universal_double_fragment(self):
        masks = verifier.FINALMASK_TCP
        self.assertEqual(len(masks), 2)
        self.assertTrue(all(m["type"] == "fragment" for m in masks))
        self.assertEqual(masks[0]["settings"]["packets"], "tlshello")
        self.assertEqual(masks[0]["settings"]["lengths"], ["0", "104", "1"])
        self.assertEqual(masks[0]["settings"]["delays"], ["0"])
        self.assertEqual(masks[0]["settings"]["maxSplit"], "0")
        self.assertEqual(masks[1]["settings"]["packets"], "1-1")
        self.assertEqual(masks[1]["settings"]["lengths"], ["114", "1"])
        self.assertEqual(masks[1]["settings"]["delays"], ["1"])
        self.assertEqual(masks[1]["settings"]["maxSplit"], "11")

    def test_vless_ws_tls_outbound(self):
        out = verifier.build_xray_outbound(self.VLESS_WS)
        self.assertEqual(out["protocol"], "vless")
        vnext = out["settings"]["vnext"][0]
        self.assertEqual(vnext["address"], "edge.example.com")
        self.assertEqual(vnext["port"], 443)
        self.assertEqual(vnext["users"][0]["id"], UUID)
        stream = out["streamSettings"]
        self.assertEqual(stream["network"], "ws")
        self.assertEqual(stream["security"], "tls")
        self.assertEqual(stream["tlsSettings"]["serverName"],
                         "edge.example.com")
        self.assertEqual(stream["tlsSettings"]["fingerprint"], "unsafe")
        self.assertEqual(stream["finalmask"],
                         {"tcp": verifier.FINALMASK_TCP})
        self.assertEqual(stream["wsSettings"]["path"], "/ws")
        self.assertEqual(stream["wsSettings"]["headers"]["Host"],
                         "cdn.example.com")

    def test_trojan_outbound(self):
        out = verifier.build_xray_outbound(self.TROJAN_WS)
        self.assertEqual(out["protocol"], "trojan")
        server = out["settings"]["servers"][0]
        self.assertEqual(server["address"], "tr.example.com")
        self.assertEqual(server["port"], 8443)
        self.assertEqual(server["password"], "secretpw")
        self.assertIn("finalmask", out["streamSettings"])

    def test_out_of_scope_returns_none(self):
        reality = ("vless://%s@203.0.113.10:443?security=reality"
                   "&sni=example.com#x" % UUID)
        self.assertIsNone(verifier.build_xray_outbound(reality))
        plain = "vless://%s@203.0.113.10:443?security=none#x" % UUID
        self.assertIsNone(verifier.build_xray_outbound(plain))
        for uri in FIXTURES.values():
            if uri.startswith(("ss://", "hysteria2://", "tuic://")):
                self.assertIsNone(verifier.build_xray_outbound(uri))


class WaitPortTests(unittest.TestCase):
    def test_live_and_dead_ports(self):
        import socket as _socket
        srv = _socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        try:
            self.assertTrue(verifier._wait_port(port, timeout=2.0))
        finally:
            srv.close()
        self.assertFalse(verifier._wait_port(port, timeout=0.6))


class AbFinalmaskSmokeTests(unittest.TestCase):
    """ab_finalmask orchestration with every network/binary seam
    stubbed. Regression guard: run 44704432326 died on
    gate2(record)["ok"] — gate2 returns an (ok, reason) tuple."""

    def test_paired_counts_with_stubbed_seams(self):
        from unittest import mock
        record = {"protocol": "vless", "server": "edge.example.com",
                  "port": 443, "source": "fixture",
                  "credential_hash": "fixturehash"}
        uri = FinalmaskTests.VLESS_WS

        def fake_tunnel(outbound, binary, direct_ip, urls=None):
            return {"pass": True, "reason": None, "latency_ms": 42.0,
                    "speed_mbps": 3.0, "egress_country": "NL"}

        def fake_xray_tunnel(outbound, binary, direct_ip, urls=None):
            return {"pass": False, "reason": "probe204",
                    "latency_ms": None, "speed_mbps": None,
                    "egress_country": None}

        with mock.patch.object(verifier, "collect_candidates",
                               return_value=([(record, uri)], {})), \
             mock.patch.object(verifier, "gate2",
                               return_value=(True, "ok")), \
             mock.patch.object(verifier, "direct_egress",
                               return_value=(None, None)), \
             mock.patch.object(verifier, "run_controls",
                               return_value={"ok": True}), \
             mock.patch.object(verifier, "run_xray_controls",
                               return_value={"ok": True}), \
             mock.patch.object(verifier, "run_tunnel",
                               side_effect=fake_tunnel), \
             mock.patch.object(verifier, "run_xray_tunnel",
                               side_effect=fake_xray_tunnel):
            stats = verifier.ab_finalmask("unused.json", "sb", "xray",
                                          10, 10, 2)
        self.assertEqual(stats["subjects"], 1)
        self.assertEqual(stats["paired"],
                         {"both": 0, "plain_only": 1,
                          "enhanced_only": 0, "neither": 0})
        self.assertEqual(stats["plain"]["passes"], 1)
        self.assertEqual(stats["enhanced"]["passes"], 0)
        self.assertEqual(stats["per_subject"][0]["plain"], True)
        self.assertEqual(stats["per_subject"][0]["enhanced"], False)


if __name__ == "__main__":
    unittest.main()
