# PROXIV3 — V2Ray Pool — Phased Plan (Rev. 1, 2026-11-20, Agent: Rick)

Scope locked by wolf (2026-11-20):
- NEW Cloudflare account + NEW GitHub repo. Old Proxiv3 repo/worker/bot untouched.
- SAME Telegram channel: @Proxiv3. Public language: English (standing rule).
- Channel posts: every 1 hour.
- ONE single VIP subscription link (secret path, given only via the new bot). No per-user tokens, no mass production.
- Hard rule: only configs proven working end-to-end are published. No filler.

## Naming & risk rules (wolf, 2026-11-20 — the new CF account must NOT hit the problems the old proxy accounts hit)
- Repo renamed to the codename `MeridianFeed` (ILIV007/MeridianFeed) on 2026-11-20 at wolf's instruction; `Pool-v2ray` is retired.
- On the Cloudflare side, NO sensitive words in ANY identifier: account name, workers.dev subdomain, Worker names, KV/D1 names, routes, secret names. Banned words: proxy, v2ray, vpn, tunnel, bypass, free, pool, proxiv3, iran, filter and similar.
- CF codenames: publisher Worker `meridian-pub`, sub Worker `meridian-sub`, anchor Worker (Phase 4) under a separate bland name, KV `MERIDIAN_STORE`. Branding (PROXIV3 etc.) lives only in Telegram post text, never in infrastructure names.
- Risk posture: the CF account only serves light content (hourly post cron + static sub reads). No mass scraping from CF, no open relay; the sub path stays secret; the Phase-4 anchor stays low-volume. Heavy work (collecting/verifying) stays on GitHub Actions.
- Deployment rule (wolf, 2026-11-20): the GitHub account is NOT connected to Cloudflare — no Cloudflare GitHub App, no Workers Builds git integration, no OAuth link. Exactly like Lyra: Workers are deployed via API token only (wrangler/API from Rick's side), and the GitHub Actions pipeline talks to Cloudflare only through the CF API (e.g. KV writes with an API token held as an Actions secret). GitHub and Cloudflare stay fully decoupled.

## Phase 0 — Decisions & access (needs wolf)
- Repo created 2026-11-20: ILIV007/Pool-v2ray (public, empty at creation; scaffold in progress).
- Wolf is creating the new Cloudflare account himself (2026-11-20) and will hand it over together with the new Telegram bot token; Rick advances all phases that do not need them in the meantime.
- New bot created by wolf in BotFather and added as admin to @Proxiv3.
- Secrets only via Secure Vault / CF secrets / GH Actions secrets. Never in repo or chat.

## Phase 1 — Source checkup (before any code) — DONE 2026-11-20
- 11 sources sampled, report at phase1-source-checkup.md (also in repo docs/). Keep: ermaozi/get_subscribe, peasoft/NoMoreWalls, mahdibland/V2RayAggregator (Eternity). Watch: EternityAir, Pawdroid/Free-servers, free-nodes/v2rayfree, mehdirzfx/v2ray-sub. Drop: AutoMergePublicNodes (redundant + 17.3% malformed), barry-far (repo blocked), freefq/free (stale 2024), NiREvil wg feed (WireGuard only, out of scope).
- Findings: NoMoreWalls / AutoMerge / ermaozi are largely one pool in three hats → cross-source dedup mandatory; `127.0.0.53` appears as a config host → Gate 1 must hard-reject placeholder hosts. Estimated intake after cross-dedup: ~700–900 unique parse-valid configs per cycle (alive ratio is Phase 3's job).
- Build a source registry (public subs / GitHub lists / channels), each source sampled once.
- Measure per source: parse rate, dead rate, duplicate rate. Drop junk sources at this gate.
- Output: checkup report with real numbers; only sources with a viable alive-ratio continue.

## Phase 1b — Source diversification (added by wolf on 2026-11-20: sources must be diverse, from different facets)
- Phase 1's keeps are largely ONE upstream pool in three hats — not diverse enough. Scout additional facets: Telegram public channels that post configs, aggregators from other scenes/languages (CN/RU/FA), direct community/airport free lists, and index sites — each sampled with the same Phase 1 metrics before joining the registry.
- Diversity is enforced again at pool composition (Phase 3/5): no single source > ~30% of a published batch, caps per country, per protocol and per server IP/ASN, and a deliberate mix of protocols (VLESS/REALITY, Trojan, SS, Hysteria2, VMess) and geos (near: TR/DE/NL/FI + spread). A batch that fails the mix check is rebalanced, not padded from one source.
- Phase 1b DONE 2026-11-20 (report: phase1b-diverse-sources.md): 12 new candidates across Telegram / CN / RU / FA facets. Keeps: PulseProxy (RU whitelist — 772/772 valid, 710 hosts, only 0.6% overlap with the Phase-1 family = a genuinely independent second backbone), @outline_vpn (FA), @Surfboardv2ray (FA — prefer its pinned sub links in Phase 2), MohammadBahemmat/V2ray-Collector (broad, but 39.5% family overlap, dedup-critical). Watch ×5, Drop ×3. Registry now spans two near-disjoint large pools + operator-direct FA Telegram channels.

## Phase 2 — Collector + parser + dedup
- Protocols in scope: VLESS, VMess, Trojan, Shadowsocks, Hysteria2, TUIC.
- Strict parse + normalise; dedup key = protocol + server + port + credential hash (same server under 50 remarks = 1 entry).
- DONE 2026-11-20: built `pipeline/collector.py` + `pipeline/sources.json` (7 keep sources from Phases 1/1b) + `pipeline/test_collector.py` (18 tests, all passing). First live run: 7/7 sources fetched, 2,581 candidates → 2,554 parse-valid, 27 Gate-1 rejects, 733 duplicates → 1,821 unique configs / 1,681 hosts. Raw configs are never stored or committed — stats output only.

## Phase 3 — Verifier (the core — config checkup)
Three gates; a config must pass ALL of them:
- Gate 1 — Structure: valid URI/JSON, sane TLS/SNI/transport fields.
- Gate 2 — Network: DNS resolves, TCP/TLS handshake inside timeout (8s). Kills most junk cheaply.
- Gate 3 — Real tunnel (sing-box on GitHub Actions): start a client from the config, then through the tunnel: (a) generate_204 succeeds, (b) egress IP differs from the runner IP, (c) latency measured, (d) small download speed test.
Controls in EVERY run (run is invalid and publishes NOTHING if controls fail):
- Positive control: our own Phase-4 Cloudflare config must pass Gate 3.
- Negative control: a known-dead config must fail.
Tiers (STRICT — upgraded by wolf on 2026-11-20: "the stricter the better; every config we use must be healthy"):
- First publish (any tier): Gate 3 passed TWICE in two separate runs at least ~15 minutes apart. A single lucky pass publishes nothing.
- Public pool: the double-pass above + latency gate (median of 3 tunnel probes ≤ 800 ms, any probe timeout = fail) + minimum download speed on a small test file.
- VIP pool: Gate 3 passed in 3 consecutive cycles + stricter latency/speed floors + sorted best-first, capped (~30–50), mixed countries/protocols, max 2 configs per server IP (forces diversity).
- Gate 1 hard-rejects: loopback/private/reserved hosts (incl. the `127.0.0.53` placeholder found in Phase 1), expired or nonsense TLS/SNI, credentials shared by an implausible number of distinct hosts.
- Gate 3 must confirm BOTH a generate_204 success AND a real HTTPS fetch whose egress IP differs from the runner and whose geo matches the config's claimed country.
- Expiry/quarantine: re-verified every hour, and the exact post batch is re-verified right before posting (nothing older than 60 minutes is posted). ONE failed re-check = quarantined (not published); 2 consecutive failures = removed. VIP drops out on the first failure.
- Never lower the bar to fill a post: a thin hour posts fewer configs, an empty hour posts only the Phase-4 anchors or nothing. Quality over quantity, always.
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

Decided (corrected by wolf on 2026-11-20, superseding the earlier `Pool-v2` reading): repo name was `Pool-v2ray`; renamed the same night to the codename `MeridianFeed` under wolf's naming/risk rule (see Naming & risk rules above). Nothing was created under the old name.
Open items for wolf: new CF account hand-off, new bot token (via Secure Vault), who counts as VIP.
