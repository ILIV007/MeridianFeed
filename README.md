# Pool-v2ray

**A V2Ray config pool for the Telegram channel [@Proxiv3](https://t.me/Proxiv3) — only configs proven working, nothing else.**

Pool-v2ray collects public V2Ray configs (VLESS, VMess, Trojan, Shadowsocks, Hysteria2, TUIC), verifies them for real, and publishes the survivors to [@Proxiv3](https://t.me/Proxiv3). It is the V2Ray companion to the existing MTProto system in the Proxiv3 repo, built in its own repository and on a new Cloudflare account so the live MTProto service stays untouched.

## How it works

- **Collector + real end-to-end verifier on GitHub Actions.** A config is not "checked" by parsing it or by opening a TCP connection — it is only accepted after a sing-box client built from that config passes a real tunnel test: traffic flows through it, the egress IP changes, and latency and download speed are measured.
- **Controls in every run.** Each verification run includes a positive control (a config that must pass) and a negative control (a known-dead config that must fail). If the controls fail, the run is invalid and **publishes nothing**.
- **Hourly posts to @Proxiv3.** One batch of verified configs every hour, with protocol, country, latency and test time.
- **One VIP subscription.** There is exactly **one** VIP subscription link — a secret path served by the project Worker and given out only through the project's new Telegram bot. It is refreshed hourly and contains only the best-tier configs (the ones that pass verification in consecutive cycles, sorted best-first). Import it once into a V2Ray client or panel and the configs keep updating on their own.

## Hard rule

Only configs proven working end-to-end are published. No filler, no untested lists, no "probably alive" entries. When the verifier cannot prove a config works, the config does not ship.

## Layout

```
pipeline/   Collector, parser, dedup and the 3-gate verifier (Phases 1–3)
worker/     Cloudflare Worker: hourly publisher, VIP subscription endpoint, VIP bot (Phases 5–6)
data/       Generated pool output (not hand-edited)
docs/       Plan and notes
```

## Status

Phase 0–1 in progress: repository scaffolded, phased plan (Rev. 1) in [docs/PLAN.md](docs/PLAN.md), source checkup under way. See [CHANGELOG.md](CHANGELOG.md).

License: MIT
