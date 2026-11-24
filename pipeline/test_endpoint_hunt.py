#!/usr/bin/env python3
"""Unit tests for pipeline/endpoint_hunt.py and the R5.1 data lifts.

Synthetic fixtures only (mocked sockets); the data-file tests pin the
lifted lists' shape and the R5.1 cross-check outcomes. Run:
python3 -m unittest pipeline.test_endpoint_hunt
"""
import ipaddress
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collector  # noqa: E402
import endpoint_hunt  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "data")


def _load_json(name):
    with open(os.path.join(DATA_DIR, name), encoding="utf-8") as handle:
        return json.load(handle)


def _load_cidrs(name):
    nets = []
    with open(os.path.join(DATA_DIR, name), encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#"):
                nets.append(ipaddress.ip_network(line))
    return nets


class DataLiftTests(unittest.TestCase):
    """The R5.1 data files exist, parse, and hold the expected lists."""

    def test_masque_warp(self):
        data = _load_json("masque_warp.json")
        self.assertEqual(data["sni_default"], "cloudflareaccess.com")
        self.assertEqual(len(data["seeds_v4"]), 8)
        self.assertEqual(len(data["cidrs_v4"]), 14)
        self.assertEqual(data["ports"], [443, 500, 1701, 4500, 4443,
                                         8443, 8095])
        self.assertEqual(len(data["cdn_anycast_pool"]), 20)

    def test_akamai_ranges(self):
        self.assertEqual(len(_load_cidrs("akamai_ranges.txt")), 275)

    def test_cf_edge_ranges(self):
        self.assertEqual(len(_load_cidrs("cf_edge_ranges.txt")), 7887)

    def test_ir_dns(self):
        data = _load_json("ir_dns.json")
        self.assertEqual(len(data["ranges_by_provider"]), 28)
        self.assertEqual(len(data["public_providers"]), 51)
        self.assertEqual(len(data["top_domains"]), 169)
        self.assertIn("1.1.1.1", [a for p in data["public_providers"]
                                  for a in p["addresses"]])


class CrosscheckTests(unittest.TestCase):
    """R5.1 cross-check outcomes, pinned (measured 2026-11-24):
    our CF lists stay the authority; their edge list is a broader
    scanner list, not a replacement."""

    def test_all_variant_ips_in_their_cf_edge_list(self):
        edge = _load_cidrs("cf_edge_ranges.txt")

        def inside(ip):
            addr = ipaddress.ip_address(ip)
            return any(addr in net for net in edge)

        for ip in collector.CF_VARIANT_IPS:
            self.assertTrue(inside(ip), ip)

    def test_masque_seeds_in_our_cf_nets(self):
        data = _load_json("masque_warp.json")
        for seed in data["seeds_v4"]:
            self.assertTrue(collector._in_cf(seed), seed)

    def test_akamai_disjoint_from_cf(self):
        akamai = _load_cidrs("akamai_ranges.txt")
        edge = _load_cidrs("cf_edge_ranges.txt")
        for net in akamai:
            self.assertFalse(
                any(net.overlaps(o) for o in collector.CF_NETS), net)
            self.assertFalse(
                any(net.overlaps(e) for e in edge), net)


class HuntTargetTests(unittest.TestCase):
    def test_targets_are_deterministic_and_bounded(self):
        data = _load_json("masque_warp.json")
        first = endpoint_hunt.hunt_targets(data)
        second = endpoint_hunt.hunt_targets(data)
        self.assertEqual(first, second)
        # 8 seeds x 7 ports + 14 cidrs x 5 sampled hosts on 443, minus
        # the 8 seeds that re-appear as first hosts of their own CIDRs.
        self.assertEqual(len(first), 8 * 7 + 14 * 5 - 8)
        self.assertEqual(len({(ip, p) for ip, p in first}), len(first))


class ProbeTests(unittest.TestCase):
    def test_tcp_refused_is_dead(self):
        tcp_ok, tls_ok, latency = endpoint_hunt.probe(
            "127.0.0.1", 9, timeout=1.0)
        self.assertFalse(tcp_ok)
        self.assertIsNone(tls_ok)
        self.assertIsNone(latency)

    def test_tcp_ok_without_tls_on_non_443(self):
        import socket as _socket
        srv = _socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        try:
            tcp_ok, tls_ok, latency = endpoint_hunt.probe(
                "127.0.0.1", port, timeout=2.0)
        finally:
            srv.close()
        self.assertTrue(tcp_ok)
        self.assertIsNone(tls_ok)
        self.assertIsNotNone(latency)


class HuntStatsTests(unittest.TestCase):
    def test_hunt_counts_with_mocked_probe(self):
        data = {"sni_default": "cloudflareaccess.com",
                "seeds_v4": ["203.0.113.1", "203.0.113.2"],
                "cidrs_v4": ["203.0.113.0/30"],
                "ports": [443, 500]}
        # targets: 2 seeds x 2 ports + 2 sampled hosts on 443 = 6.

        def fake_probe(ip, port, sni=None, timeout=5.0):
            if ip == "203.0.113.1":
                return True, (True if port == 443 else None), 12.0
            return False, None, None

        with mock.patch.object(endpoint_hunt, "probe",
                               side_effect=fake_probe):
            stats = endpoint_hunt.hunt_masque(data=data)
        # targets: 2 seeds x 2 ports + 2 sampled hosts on 443, minus
        # the 2 sampled hosts that duplicate the seeds on 443 = 4.
        self.assertEqual(stats["tested"], 4)
        self.assertEqual(stats["reachable"], 2)
        self.assertEqual(stats["tls_ok_443"], 1)
        self.assertEqual(stats["latency_ms"]["n"], 2)
        self.assertIn("not a MASQUE protocol proof", stats["scope"])

    def test_hunt_never_raises(self):
        bad = endpoint_hunt.hunt_masque(
            data={"seeds_v4": [], "cidrs_v4": ["not-a-cidr"],
                  "ports": [443]})
        self.assertEqual(bad["tested"], 0)
        self.assertEqual(bad["reachable"], 0)


if __name__ == "__main__":
    unittest.main()
