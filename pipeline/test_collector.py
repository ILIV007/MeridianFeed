#!/usr/bin/env python3
"""Unit tests for collector.py — parser, Gate-1 rejects, dedup.

Synthetic fixtures only: fake hostnames and fake credentials, nothing real.
Run: python3 -m unittest pipeline.test_collector  (or)  python3 pipeline/test_collector.py
"""
import base64
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collector  # noqa: E402

UUID = "11111111-2222-3333-4444-555555555555"
UUID2 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def vmess_uri(host="node2.example.com", port="8443", uid=UUID2, net="tcp"):
    payload = {"v": "2", "ps": "fixture", "add": host, "port": port,
               "id": uid, "aid": "0", "net": net, "type": "none",
               "host": "", "path": "", "tls": ""}
    return "vmess://" + base64.b64encode(
        json.dumps(payload).encode()).decode()


class ParseTests(unittest.TestCase):
    def test_vless(self):
        rec = collector.parse_uri(
            "vless://%s@node1.example.com:443?type=ws&security=tls#one" % UUID)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["protocol"], "vless")
        self.assertEqual(rec["server"], "node1.example.com")
        self.assertEqual(rec["port"], 443)
        self.assertEqual(rec["transport"], "ws")
        self.assertEqual(len(rec["credential_hash"]), 64)

    def test_vmess(self):
        rec = collector.parse_uri(vmess_uri())
        self.assertIsNotNone(rec)
        self.assertEqual(rec["protocol"], "vmess")
        self.assertEqual(rec["server"], "node2.example.com")
        self.assertEqual(rec["port"], 8443)

    def test_trojan(self):
        rec = collector.parse_uri(
            "trojan://s3cret-pw@node3.example.com:443?security=tls#x")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["protocol"], "trojan")
        self.assertEqual(rec["port"], 443)

    def test_ss_plain_userinfo(self):
        rec = collector.parse_uri(
            "ss://aes-256-gcm:passw0rd@node4.example.com:8388#x")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["protocol"], "ss")
        self.assertEqual(rec["port"], 8388)

    def test_ss_base64_userinfo(self):
        userinfo = base64.urlsafe_b64encode(
            b"aes-128-gcm:passw0rd").decode().rstrip("=")
        rec = collector.parse_uri(
            "ss://%s@node5.example.com:8389#x" % userinfo)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["port"], 8389)

    def test_ss_legacy_whole_base64(self):
        blob = base64.b64encode(
            b"chacha20-ietf-poly1305:pw@node6.example.com:8390").decode()
        rec = collector.parse_uri("ss://" + blob)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["server"], "node6.example.com")
        self.assertEqual(rec["port"], 8390)

    def test_hysteria2_and_hy2_alias(self):
        for uri in ("hysteria2://pw@node7.example.com:443#x",
                    "hy2://pw@node7.example.com:443#x"):
            rec = collector.parse_uri(uri)
            self.assertIsNotNone(rec)
            self.assertEqual(rec["protocol"], "hysteria2")

    def test_tuic(self):
        rec = collector.parse_uri(
            "tuic://%s:tuic-pw@node8.example.com:10443#x" % UUID)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["protocol"], "tuic")
        self.assertEqual(rec["port"], 10443)


class Gate1RejectTests(unittest.TestCase):
    def test_placeholder_host_127_0_0_53(self):
        self.assertIsNone(collector.parse_uri(
            "vless://%s@127.0.0.53:443#x" % UUID))

    def test_loopback_and_private(self):
        for host in ("127.0.0.1", "10.0.0.5", "192.168.1.10",
                     "172.16.0.9", "localhost", "::1"):
            self.assertIsNone(collector.parse_uri(
                "vless://%s@%s:443#x" % (UUID, host)), host)

    def test_missing_port(self):
        self.assertIsNone(collector.parse_uri(
            "vless://%s@node1.example.com#x" % UUID))

    def test_missing_credential(self):
        self.assertIsNone(collector.parse_uri(
            "vless://node1.example.com:443#x"))
        self.assertIsNone(collector.parse_uri(
            "trojan://node3.example.com:443#x"))

    def test_bad_port(self):
        self.assertIsNone(collector.parse_uri(
            "vless://%s@node1.example.com:99999#x" % UUID))
        self.assertIsNone(collector.parse_uri(
            "vless://%s@node1.example.com:abc#x" % UUID))

    def test_vmess_private_host(self):
        self.assertIsNone(collector.parse_uri(vmess_uri(host="192.168.0.20")))

    def test_garbage(self):
        self.assertIsNone(collector.parse_uri("vless://"))
        self.assertIsNone(collector.parse_uri("vmess://not-base64-json!!!"))
        self.assertIsNone(collector.parse_uri("http://example.com:80/"))


class DedupTests(unittest.TestCase):
    def test_remark_does_not_change_key(self):
        a = collector.parse_uri("vless://%s@n.example.com:443#first" % UUID)
        b = collector.parse_uri("vless://%s@n.example.com:443#second" % UUID)
        self.assertEqual(collector.dedup_key(a), collector.dedup_key(b))

    def test_different_port_or_credential_differs(self):
        a = collector.parse_uri("vless://%s@n.example.com:443#x" % UUID)
        b = collector.parse_uri("vless://%s@n.example.com:8443#x" % UUID)
        c = collector.parse_uri("vless://%s@n.example.com:443#x" % UUID2)
        self.assertNotEqual(collector.dedup_key(a), collector.dedup_key(b))
        self.assertNotEqual(collector.dedup_key(a), collector.dedup_key(c))

    def test_extract_and_candidate_texts(self):
        text = ('junk vless://%s@n.example.com:443#x and '
                'ss://aes-256-gcm:pw@m.example.com:8388#y end' % UUID)
        self.assertEqual(len(collector.extract_candidates(text)), 2)
        blob = base64.b64encode(text.encode()).decode()
        texts = collector.candidate_texts(blob.encode())
        self.assertEqual(len(texts), 2)
        self.assertEqual(len(collector.extract_candidates(texts[1])), 2)


class ConditionalFetchTest(unittest.TestCase):
    """fetch() snapshots per-URL bodies and revalidates conditionally."""

    def _response(self, body, headers):
        import io
        resp = unittest.mock.MagicMock()
        resp.read.return_value = body
        resp.headers = headers
        resp.__enter__ = lambda s: resp
        resp.__exit__ = lambda s, *a: False
        return resp

    def test_snapshot_then_304_serves_cache(self):
        import io
        import tempfile
        import unittest.mock
        import urllib.error
        url = "https://example.com/sub"
        body = b"vless://example"
        with tempfile.TemporaryDirectory() as cache_dir:
            with unittest.mock.patch.dict(
                    "os.environ",
                    {"COLLECTOR_CACHE_DIR": cache_dir, "COLLECTOR_PACING": "0"}):
                seen_headers = []

                def first(request, timeout=None):
                    seen_headers.append(request.headers)
                    return self._response(body, {"ETag": '"v1"'})

                with unittest.mock.patch("urllib.request.urlopen", first):
                    self.assertEqual(collector.fetch(url), body)
                self.assertNotIn("If-none-match", seen_headers[0])

                def second(request, timeout=None):
                    seen_headers.append(request.headers)
                    raise urllib.error.HTTPError(
                        url, 304, "Not Modified", {}, io.BytesIO(b""))

                with unittest.mock.patch("urllib.request.urlopen", second):
                    self.assertEqual(collector.fetch(url), body)
                self.assertEqual(seen_headers[1].get("If-none-match"), '"v1"')


if __name__ == "__main__":
    unittest.main()
