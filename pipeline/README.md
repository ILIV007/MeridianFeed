# Pipeline — collector & verifier (Phases 1–3)

The pipeline runs on GitHub Actions. Its job is simple to state and strict in practice: **find V2Ray configs, prove they work, and hand only the proven ones to the publisher.**

## Phase 1 — Source checkup (before any code is trusted)

Every candidate source (public subscription, GitHub list, channel feed) is sampled once and measured with real numbers:

- parse rate — how many entries are even well-formed configs
- dead rate — how many fail verification
- duplicate rate — how many repeat a server already seen

Sources with a non-viable alive ratio are dropped at this gate and never enter the registry. Real sources are added to the registry only after this audit (see `sources.example.json` for the registry shape).

## Phase 2 — Collector, parser, dedup — BUILT (2026-11-20)

`pipeline/collector.py` (Python, stdlib only) is the collector:

- **Registry:** `pipeline/sources.json` — the keep sources from the Phase 1 / 1b checkups only (ermaozi, NoMoreWalls, mahdibland Eternity, PulseProxy, @outline_vpn, @Surfboardv2ray, Bahemmat collector), each tagged with its diversity facet.
- **Fetch:** one polite fetch per source (browser UA, timeout), base64 subscription payloads decoded, config URIs extracted from raw lists and Telegram public-preview pages alike.
- **Parse:** strict parsing for VLESS, VMess (base64 JSON), Trojan, Shadowsocks (plain, base64-userinfo and legacy whole-blob forms), Hysteria2 and TUIC, normalised into records of protocol + server + port + credential hash (SHA-256) + transport + source. Malformed entries are discarded, not repaired by guessing. **Raw configs are kept in memory only — the collector outputs a stats JSON (counts per source and totals); no credentials are stored or committed.**
- **Gate-1 rejects at parse time:** loopback / private / reserved hosts (including the `127.0.0.53` placeholder), missing ports or credentials, out-of-range ports.
- **Dedup:** key = `protocol + server + port + credential hash`, applied across all sources. The same server published under fifty different remarks is one entry.

Run it:

```
python3 pipeline/collector.py pipeline/sources.json
```

Tests (synthetic fixtures only): `python3 -m unittest pipeline.test_collector` — 18 tests covering the parser, the Gate-1 rejects and the dedup key, all passing.

First live run (2026-11-20): 7/7 sources fetched — 2,581 candidates → 2,554 parse-valid, 27 Gate-1 rejects, 733 duplicates removed → **1,821 unique configs on 1,681 hosts** (deduped mix: vless 1,376, ss 263, trojan 77, vmess 56, hysteria2 48, tuic 1). Parse-valid is still not alive — that is Phase 3's measurement.

## Phase 3 — The 3-gate verifier (STRICT)

A config must pass **all three** gates:

1. **Structure** — valid URI/JSON, sane TLS / SNI / transport fields. Gate 1 also **hard-rejects**: loopback / private / reserved hosts (including the `127.0.0.53` placeholder host found in Phase 1), expired or nonsense TLS/SNI, and credentials shared by an implausible number of distinct hosts.
2. **Network** — DNS resolves and the TCP/TLS handshake completes inside the timeout (8s). This kills most junk cheaply, but passing it proves nothing on its own.
3. **Real tunnel** — a sing-box client is built from the config and traffic is sent through it. Gate 3 must confirm **both** a generate_204 success **and** a real HTTPS fetch whose **egress IP differs from the runner IP** and whose **geo matches the config's claimed country**. Latency is the **median of 3 tunnel probes** (any probe timeout = fail) and a small download speed test is measured. This is the only gate that counts as "working".

Every run also carries **controls**: a positive control config that must pass Gate 3 and a negative control (known-dead) config that must fail. If the controls fail, the run is invalid and publishes nothing.

### Tiers (STRICT — the stricter the better; every config we use must be healthy)

- **First publish (any tier)** — Gate 3 passed **twice**, in two separate runs at least ~15 minutes apart. A single lucky pass publishes nothing.
- **Public pool** — the double-pass above, plus the latency gate (median of 3 tunnel probes ≤ 800 ms) and a minimum download speed on a small test file. Posted to @Proxiv3 hourly.
- **VIP pool** — Gate 3 passed in **3 consecutive cycles**, plus stricter latency/speed floors, sorted best-first and capped (~30–50), mixed countries/protocols, and max 2 configs per server IP (forces diversity). This tier feeds the single VIP subscription link.

### Expiry & quarantine

Configs are re-verified every hour, and the exact post batch is re-verified right before posting — nothing older than 60 minutes is posted. **One** failed re-check = quarantined (not published); **2 consecutive failures** = removed from the pool. VIP drops out on the first failure. Nothing is kept on age alone.

**Never lower the bar to fill a post:** a thin hour posts fewer configs, an empty hour posts only the Phase-4 anchors or nothing. Quality over quantity, always.
