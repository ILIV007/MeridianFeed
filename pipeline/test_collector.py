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


def vmess_ws_tls(host, sni="front.example.com", uid=UUID):
    payload = {"v": "2", "ps": "fixture", "add": host, "port": "443",
               "id": uid, "aid": "0", "net": "ws", "type": "none",
               "host": sni, "path": "/hls/x.m3u8", "tls": "tls",
               "sni": sni}
    return "vmess://" + base64.b64encode(
        json.dumps(payload).encode()).decode()


class VariantTests(unittest.TestCase):
    def test_cf_ip_vmess_multiplies(self):
        uri = vmess_ws_tls("172.64.145.93")
        rec = collector.parse_uri(uri)
        out = collector.expand_cf_variants(rec, uri)
        self.assertEqual(len(out), 1 + collector.MAX_CF_VARIANTS)
        keys = {collector.dedup_key(r) for r, _ in out}
        self.assertEqual(len(keys), len(out))  # own key per presentation
        for r, u in out:
            self.assertEqual(r["credential_hash"], rec["credential_hash"])
            self.assertEqual(r["port"], 443)
            self.assertIn(r["server"], collector.CF_VARIANT_IPS)
        # one service behind all presentations
        svc = {collector.service_key(r, u) for r, u in out}
        self.assertEqual(len(svc), 1)

    def test_cf_domain_vmess_multiplies(self):
        uri = vmess_ws_tls("front.example.com")
        rec = collector.parse_uri(uri)
        with unittest.mock.patch.object(
                collector, "_resolve_ips",
                lambda h: ["172.64.145.93"] if h else []):
            out = collector.expand_cf_variants(rec, uri)
        self.assertGreater(len(out), 1)
        self.assertEqual(out[0][0]["server"], "front.example.com")

    def test_non_fronted_no_variants(self):
        uri = vmess_uri()  # tcp, no tls
        rec = collector.parse_uri(uri)
        self.assertEqual(len(collector.expand_cf_variants(rec, uri)), 1)
        reality = ("vless://%s@node9.example.com:443?type=tcp"
                   "&security=reality&sni=www.example.com#x" % UUID)
        rec = collector.parse_uri(reality)
        self.assertEqual(
            len(collector.expand_cf_variants(rec, reality)), 1)
        ss = "ss://aes-256-gcm:passw0rd@172.64.145.93:8388#x"
        rec = collector.parse_uri(ss)
        self.assertEqual(len(collector.expand_cf_variants(rec, ss)), 1)


def vmess_ws_tls_port(host, port, sni="front.example.com", uid=UUID,
                      path="/hls/x.m3u8"):
    payload = {"v": "2", "ps": "fixture", "add": host, "port": port,
               "id": uid, "aid": "0", "net": "ws", "type": "none",
               "host": sni, "path": path, "tls": "tls", "sni": sni}
    return "vmess://" + base64.b64encode(
        json.dumps(payload).encode()).decode()


def collect_body(body, name="fixture-source"):
    """Run collect_source over an in-memory body (fetch stubbed)."""
    source = {"name": name, "url": "https://example.invalid/sub",
              "facet": "test", "type": "sub"}
    seen, seen_identity = {}, {}
    with unittest.mock.patch.object(collector, "fetch",
                                    lambda url: body.encode()):
        stats = collector.collect_source(source, seen, seen_identity)
    return stats, seen


class IdentityDedupTests(unittest.TestCase):
    """Plan Rev.2 R1: CDN-aware identity — one candidate per origin
    service, however many edge addresses the sources print for it."""

    def test_same_service_two_cf_ips_collapses(self):
        body = "\n".join([vmess_ws_tls("172.64.145.93"),
                          vmess_ws_tls("104.18.10.10")])
        stats, seen = collect_body(body)
        self.assertEqual(stats["unique_new"], 1)
        self.assertEqual(stats["identity_duplicates"], 1)
        # the survivor still expands into deliberate presentations
        self.assertEqual(stats["variants"], collector.MAX_CF_VARIANTS)

    def test_cf_alt_port_is_same_service(self):
        body = "\n".join([vmess_ws_tls_port("172.64.145.93", "443"),
                          vmess_ws_tls_port("104.18.10.10", "2053")])
        stats, _ = collect_body(body)
        self.assertEqual(stats["unique_new"], 1)
        self.assertEqual(stats["identity_duplicates"], 1)

    def test_distinct_services_on_one_front_do_not_collapse(self):
        body = "\n".join([
            vmess_ws_tls("172.64.145.93", uid=UUID),
            vmess_ws_tls("104.18.10.10", uid=UUID2),
            vmess_ws_tls_port("104.18.10.11", "443", path="/other")])
        stats, _ = collect_body(body)
        self.assertEqual(stats["unique_new"], 3)
        self.assertEqual(stats["identity_duplicates"], 0)

    def test_non_fronted_identity_is_dedup_key(self):
        rec = collector.parse_uri(
            "vless://%s@n.example.com:443#x" % UUID)
        self.assertEqual(collector.identity_key(rec, "vless://%s@"
                         "n.example.com:443#x" % UUID),
                         "key|" + collector.dedup_key(rec))


class CfShapeRejectTests(unittest.TestCase):
    """Plan Rev.2 R3: CF-edge shape drops (patterniha transform)."""

    def test_plaintext_443_on_cf_ip_rejected(self):
        uri = "vless://%s@172.64.145.93:443?type=ws#x" % UUID
        rec = collector.parse_uri(uri)
        self.assertEqual(collector.cf_shape_reject(rec, uri),
                         "cf_plaintext_443")

    def test_tls_8080_on_cf_ip_rejected(self):
        uri = ("vless://%s@172.64.145.93:8080?type=ws&security=tls#x"
               % UUID)
        rec = collector.parse_uri(uri)
        self.assertEqual(collector.cf_shape_reject(rec, uri),
                         "cf_tls_8080")

    def test_tls_443_on_cf_ip_kept(self):
        uri = ("vless://%s@172.64.145.93:443?type=ws&security=tls#x"
               % UUID)
        rec = collector.parse_uri(uri)
        self.assertIsNone(collector.cf_shape_reject(rec, uri))

    def test_trojan_443_without_security_param_kept(self):
        uri = "trojan://s3cret-pw@172.64.145.93:443#x"
        rec = collector.parse_uri(uri)
        self.assertIsNone(collector.cf_shape_reject(rec, uri))

    def test_non_cf_plaintext_443_kept(self):
        uri = "vless://%s@203.0.113.10:443?type=ws#x" % UUID
        rec = collector.parse_uri(uri)
        self.assertIsNone(collector.cf_shape_reject(rec, uri))

    def test_ss_exempt(self):
        uri = "ss://aes-256-gcm:passw0rd@172.64.145.93:443#x"
        rec = collector.parse_uri(uri)
        self.assertIsNone(collector.cf_shape_reject(rec, uri))


class FrontClassTests(unittest.TestCase):
    """collector.front_class — the shared survival-class definition
    (mirrors compose.classify_uri; the two must never drift)."""

    def fc(self, uri):
        record = collector.parse_uri(uri, "test")
        self.assertIsNotNone(record, uri)
        return collector.front_class(record, uri)

    def test_cf_ip_ws_tls_is_class_0(self):
        self.assertEqual(self.fc(
            "vless://u@172.67.190.164:443?type=ws&security=tls"
            "&sni=a.example#x"), 0)

    def test_domain_ws_tls_is_class_1(self):
        self.assertEqual(self.fc(
            "vless://u@cdn.example.com:443?type=ws&security=tls"
            "&sni=a.example#x"), 1)

    def test_plain_ss_is_class_2(self):
        self.assertEqual(self.fc(
            "ss://YWVzLTI1Ni1nY206cA@203.0.113.9:443#x"), 2)

    def test_ss_with_tls_plugin_is_not_plain(self):
        self.assertNotEqual(self.fc(
            "ss://YWVzLTI1Ni1nY206cA@203.0.113.9:443"
            "?plugin=v2ray-plugin%3Bmode%3Dwebsocket%3Btls#x"), 2)

    def test_reality_with_and_without_sni(self):
        self.assertEqual(self.fc(
            "vless://u@203.0.113.9:443?type=tcp&security=reality"
            "&sni=www.example.com#x"), 3)
        self.assertEqual(self.fc(
            "vless://u@203.0.113.9:443?type=tcp&security=reality#x"), 4)

    def test_hysteria2_is_class_5(self):
        self.assertEqual(self.fc("hy2://p@203.0.113.9:443#x"), 5)

    def test_garbage_never_crashes(self):
        record = {"protocol": "vless", "server": "not a host",
                  "port": "f5b4:88:105:1c00:eaff:fe00:3e1:61022"}
        self.assertEqual(collector.front_class(record, "vless://@@@"),
                         5)


if __name__ == "__main__":
    unittest.main()
