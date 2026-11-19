# Pipeline — collector & verifier (Phases 1–3)

The pipeline runs on GitHub Actions. Its job is simple to state and strict in practice: **find V2Ray configs, prove they work, and hand only the proven ones to the publisher.**

## Phase 1 — Source checkup (before any code is trusted)

Every candidate source (public subscription, GitHub list, channel feed) is sampled once and measured with real numbers:

- parse rate — how many entries are even well-formed configs
- dead rate — how many fail verification
- duplicate rate — how many repeat a server already seen

Sources with a non-viable alive ratio are dropped at this gate and never enter the registry. Real sources are added to the registry only after this audit (see `sources.example.json` for the registry shape).

## Phase 2 — Collector, parser, dedup

- Protocols in scope: VLESS, VMess, Trojan, Shadowsocks, Hysteria2, TUIC.
- Strict parsing and normalisation; malformed entries are discarded, not repaired by guessing.
- Dedup key = `protocol + server + port + credential hash`. The same server published under fifty different remarks is one entry.

## Phase 3 — The 3-gate verifier

A config must pass **all three** gates:

1. **Structure** — valid URI/JSON, sane TLS / SNI / transport fields.
2. **Network** — DNS resolves and the TCP/TLS handshake completes inside the timeout. This kills most junk cheaply, but passing it proves nothing on its own.
3. **Real tunnel** — a sing-box client is built from the config and traffic is sent through it: a generate_204 request succeeds, the **egress IP differs from the runner IP**, and latency plus a small download speed are measured. This is the only gate that counts as "working".

Every run also carries **controls**: a positive control config that must pass Gate 3 and a negative control (known-dead) config that must fail. If the controls fail, the run is invalid and publishes nothing.

### Tiers

- **Public pool** — Gate 3 passed once in the current cycle. Posted to @Proxiv3 hourly.
- **VIP pool** — Gate 3 passed in **2 consecutive cycles**, plus latency/speed thresholds, sorted best-first and capped. This tier feeds the single VIP subscription link.

Configs are re-verified every hour; two consecutive failures remove a config from the pool. Nothing is kept on age alone.
