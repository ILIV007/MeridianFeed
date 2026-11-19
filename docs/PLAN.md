# PROXIV3 — V2Ray Pool — Phased Plan (Rev. 1, 2026-11-20, Agent: Rick)

Scope locked by wolf (2026-11-20):
- NEW Cloudflare account + NEW GitHub repo. Old Proxiv3 repo/worker/bot untouched.
- SAME Telegram channel: @Proxiv3. Public language: English (standing rule).
- Channel posts: every 1 hour.
- ONE single VIP subscription link (secret path, given only via the new bot). No per-user tokens, no mass production.
- Hard rule: only configs proven working end-to-end are published. No filler.

## Phase 0 — Decisions & access (needs wolf)
- Repo created 2026-11-20: ILIV007/Pool-v2ray (public, empty at creation; scaffold in progress).
- Wolf is creating the new Cloudflare account himself (2026-11-20) and will hand it over together with the new Telegram bot token; Rick advances all phases that do not need them in the meantime.
- New bot created by wolf in BotFather and added as admin to @Proxiv3.
- Secrets only via Secure Vault / CF secrets / GH Actions secrets. Never in repo or chat.

## Phase 1 — Source checkup (before any code)
- Build a source registry (public subs / GitHub lists / channels), each source sampled once.
- Measure per source: parse rate, dead rate, duplicate rate. Drop junk sources at this gate.
- Output: checkup report with real numbers; only sources with a viable alive-ratio continue.

## Phase 2 — Collector + parser + dedup
- Protocols in scope: VLESS, VMess, Trojan, Shadowsocks, Hysteria2, TUIC.
- Strict parse + normalise; dedup key = protocol + server + port + credential hash (same server under 50 remarks = 1 entry).

## Phase 3 — Verifier (the core — config checkup)
Three gates; a config must pass ALL of them:
- Gate 1 — Structure: valid URI/JSON, sane TLS/SNI/transport fields.
- Gate 2 — Network: DNS resolves, TCP/TLS handshake inside timeout (8s). Kills most junk cheaply.
- Gate 3 — Real tunnel (sing-box on GitHub Actions): start a client from the config, then through the tunnel: (a) generate_204 succeeds, (b) egress IP differs from the runner IP, (c) latency measured, (d) small download speed test.
Controls in EVERY run (run is invalid and publishes NOTHING if controls fail):
- Positive control: our own Phase-4 Cloudflare config must pass Gate 3.
- Negative control: a known-dead config must fail.
Tiers:
- Public pool: Gate 3 passed once in the current cycle.
- VIP pool: Gate 3 passed in 2 consecutive cycles + latency/speed thresholds + sorted best-first, capped (~30–50), mixed countries/protocols.
Expiry: re-verified every hour before posting; 2 consecutive failures = removed. Nothing is published on age alone.
Known limit: runners are outside Iran — a pass proves the config truly works, not that an Iranian ISP won't block its IP. Mitigation: prefer REALITY + CDN-fronted configs, nearby geos, and bot user feedback (Phase 6) to drop Iran-dead entries fast.

## Phase 4 — Own anchor configs (Cloudflare)
- Minimal own VLESS+WS+TLS Worker on the new CF account (written in-house, no upstream project dependency).
- These are the guaranteed-alive anchors: public posts rotate them, VIP sub always includes them.
- Watch free-plan limits + abuse risk; anchors are a backbone, not the whole pool.

## Phase 5 — Publisher (new CF Worker)
- Cron hourly: read verified pool from KV, post one batch to @Proxiv3 (protocol, country, latency, tested-at, config in a copyable block).
- VIP sub endpoint: fixed link /sub/<secret> serving the current VIP pool (base64, standard headers) — content refreshed hourly, link never changes. Wrong secret = 404.
- Cron-only for the old bot token if reused for posting; the publisher never calls setWebhook (protects the old MTProto bot).

## Phase 6 — New VIP bot
- Own webhook on the new Worker (new bot = no conflict with @Prox_IVbot).
- Gives the single VIP sub link to VIP users; collects working/dead feedback per config to feed Phase 3 scoring.

## Phase 7 — Live test, tidy, ship
- Import tests: v2rayNG, Happ, Streisand — public post configs + VIP sub, on real connections.
- Full checkup/debug pass, then ship as v1.0.0 via branch + PR + merge, tagged `Agent: Rick`, changelog in repo.

Decided (corrected by wolf on 2026-11-20, superseding the earlier `Pool-v2` reading): repo name = `Pool-v2ray` (ILIV007/Pool-v2ray — checked 2026-11-20, name is free). Nothing was created under the old name.
Open items for wolf: new CF account hand-off, new bot token (via Secure Vault), who counts as VIP.
