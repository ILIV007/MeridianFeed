## 2026-11-20 — Phases 4–6 built; FIRST POST LIVE in @Proxiv3; VIP sub delivered

- **Verify runs (verifier v1.1.0):** five dispatch runs with controls OK — 44627118024 (Gate 3: 112 passes, 93 public-single), 44628683507 (113, 93), 44630781473 (112, 93), 44632829174 (111, 91), 44634869948 (114, 95). Run 44623695513 predates v1.1.0 per-pass keys, so tier intersections start with these runs (documented in the v1.1.0 entry below).
- **Strict tiers applied, bar never lowered:** public = Gate-3 pass + public floors (median latency ≤800 ms, speed ≥1.0 Mbps) in two runs ≥15 min apart → intersection **103 keys**; VIP = Gate-3 pass in 3 consecutive runs with VIP floors (≤500 ms, ≥2.5 Mbps in each) → intersection **45 keys** (qualifying triples B-C-D and C-D-E, spans ~27 min). Pool composition re-collects source lists to recover URIs (sources churn: 36–40 of 103 public and 19–20 of 45 VIP keys recovered per compose), then applies diversity quotas (public cap 12: source ≤3, country ≤3, protocol ≤5, host ≤2; VIP cap 30: source ≤9, country ≤6, protocol ≤12, host ≤2). First pools: **public 7** (US/FR/SE/JP; vless/ss/vmess), **VIP 6** (US; vless/vmess — only US configs met the VIP floors in 3 consecutive cycles; caps are ceilings, never filled by lowering the bar). Full audit: every pooled key ∈ its intersection set, every URI parses, every remark matches `🪼 PROXIV3 · <flag CC> · <PROTOCOL> · Verified`.
- **Workers deployed** on the new Cloudflare account (API token only; workers.dev routes enabled after upload — the 1042 step): `meridian-pub` (cron `33 * * * *`, Rich Message batches from KV `public_pool`, refuses pools >90 min old), `meridian-sub` (`/sub/<secret>` serves KV `vip_sub`; wrong secret 404; `profile-title` 🪼 PROXIV3 VIP), `meridian-bot` (@Pool_IVbot webhook: /start, /vip for admins + KV `vip_users`, /help, works/dead feedback). `TELEGRAM_TOKEN` secret set via stdin and verified (names only) on meridian-pub and meridian-bot. KV `MERIDIAN_STORE` created; keys: public_pool, vip_sub, sub_secret, webhook_secret, vip_users, feedback, anchor_uuid, node_path. Webhook registered (secret-token header = KV webhook_secret), pending 0, no errors.
- **FIRST POST:** Rich Message with the 7 double-pass configs → @Proxiv3 message **2621**, https://t.me/Proxiv3/2621.
- **VIP subscription:** one secret-path link served by meridian-sub (6 configs, verified live: 200, subscription headers, body byte-identical to KV and decodes to the 6 URIs). The full URL exists only in KV and in the bot's delivery messages — delivered by @Pool_IVbot to both admin accounts (bot message 5 to the main account, message 6 to @BLUE_WOLF_03). The bot's /vip returns the same link to admins/VIPs.
- **Hourly loop closed:** the `verify` workflow runs hourly; an hourly composer intersects the latest runs under the same strict rules and rewrites the KV pools only when content changed (and dispatches a fresh verify run if the newest completed run is >50 min old), so meridian-pub's :33 posts stay fresh.
- **Live-found bug, fixed:** JavaScript has no `\U` escape — the 🪼 emoji in Worker strings degraded to literal text (`U0001FABC…` in the sub's profile-title). All three Workers switched to `\u{1FABC}`, redeployed, and the profile-title was re-verified decoding to `🪼 PROXIV3 VIP`.
- **Phase 4 anchor — BLOCKED, documented:** `worker/meridian-peak/index.js` (minimal own VLESS+WS+TLS) is written but undeployable via the Scripts API on this account: any script referencing `cloudflare:sockets` (static import, dynamic import, or separate module — all bisected) returns HTTP 1101 on every route; identical code without the reference works. Anchor is not deployed and not in any pool. Options: dashboard/wrangler deploy or a Cloudflare-side fix.
- Worker sources for all four Workers live under `worker/` (deployed sources recovered from the API and tail-verified); `worker/README.md` documents deploy steps, the route-enable step, the KV inventory, and the anchor finding.

Agent: Rick

## 2026-11-20 — Verifier v1.1.0: per-pass opaque keys (tier intersection)

- `pipeline/verifier.py` now emits one opaque record per Gate-3 pass in the stats JSON: the SHA-256 of the config's dedup key plus protocol, source, egress country, latency, speed and a public-criteria flag. One-way hashes only — still no config, credential, server or egress IP is written anywhere. This makes the strict repeat-pass tiers computable across runs: public = the same key passed in two runs at least ~15 minutes apart; VIP = the same key passed in three consecutive cycles.
- Note: run 44623695513 predates this and kept stats only, so its individual passes cannot be intersected retroactively; the tier clocks start with the first v1.1.0 runs.
- Tests: 25/25 pass (18 collector + 7 verifier, 2 new pass-key tests).

Agent: Rick

## 2026-11-20 — First real GitHub Actions verify run (Phase 3)

- Workflow `verify` run 44623695513 completed with conclusion **success**; stats artifact `verify-stats-44623695513`. Run numbers: input fetched 2,581 → Gate 1 valid 2,554 → 1,821 unique → sampled 200. Controls ok (positive pass, negative correctly failed). Gate 2: 173/200 passed. Gate 3: 106/173 passed (ss 52, vless 38, vmess 10, hysteria2 4, trojan 2); latency median 359.7 ms / p90 811.9 ms; speed median 2.42 Mbps / p90 7.66 Mbps; 93 met the single-run public criteria. Nothing published — strict tier assignment still requires the repeat passes.
- Workflow now also appends the stats JSON to the step summary, so future run numbers are readable via the API without downloading the artifact zip.

Agent: Rick

# Changelog

## 2026-11-20 — Final remark format
- Published config remarks now use wolf's final format: `🪼 PROXIV3 · <flag> <CC> · <PROTOCOL> · Verified` — the @Proxiv3 channel's own 🪼 signature emoji up front, and the word Verified in place of any latency figure (no ms anywhere in config names).
- `format_remark()` in `pipeline/verifier.py` updated; `pipeline/test_verifier.py` asserts the 🪼 PROXIV3 prefix, the `· Verified` suffix, and that no digits / latency value leak into the name.
- Agent: Rick

## 2026-11-20 — Remark format corrected

- Config names carry NO latency figure (wolf's correction): `format_remark(country, protocol)` now returns `PROXIV3 · <flag> <CC> · <PROTOCOL>` only. Tests and pipeline README updated accordingly.

Agent: Rick

## 2026-11-20 — Phase 3 verifier core built

- `pipeline/verifier.py` (stdlib only, reuses the collector's fetch/parse/dedup; raw URIs in memory only): Gate 2 (DNS + TCP, concurrent) and Gate 3 (one sing-box tunnel per config — 3-probe median latency, generate_204, trace egress-IP/country confirmation, 256 KB speed sample; bounded concurrency of 4). Controls run first in every run: a local loopback sing-box pair + local origin as the positive control and a dead TEST-NET config as the negative; a failed control invalidates the run and nothing is verified. Output is a stats JSON only — no credentials, servers or egress IPs are ever written out.
- `.github/workflows/verify.yml`: hourly + manual runs on GitHub Actions with a pinned, checksum-verified sing-box (v1.11.15); uploads the stats JSON as an artifact. Publishes nothing (publishing is Phase 5; tiers need the strict repeat passes across runs).
- Rebranding helpers (display-only, for publish time): `format_remark()` → `PROXIV3 · <flag> <CC> · <PROTOCOL>` and `rebrand_uri()` (rewrites only the URI fragment / vmess `ps`; record and dedup key unchanged) — `pipeline/test_verifier.py`, 5 tests passing.
- Proof run (2026-11-20, build sandbox, 40-config sample): 2,581 fetched → 2,554 Gate-1 valid → 1,821 unique → 40 sampled; Gate 2: 40/40 (inflated here — the sandbox gateway accepts TCP broadly); controls OK (positive passed at 0.9 ms median, negative failed as required); Gate 3 candidates: 0/40, all at the 204 probe — an environment artifact: the sandbox blocks direct TLS egress (verified without sing-box), which candidate tunnels need. Real Gate-3 rates will be measured on Actions runners. Outbound-builder correctness checked separately: 60/60 sampled configs pass `sing-box check` (a ws-transport naming bug was found and fixed during the run).

Agent: Rick

## 2026-11-20 — Phase 2 collector built

- Phase 2 complete: `pipeline/collector.py` (stdlib-only) fetches the keep-source registry (`pipeline/sources.json` — 7 sources: ermaozi, NoMoreWalls, mahdibland Eternity, PulseProxy, @outline_vpn, @Surfboardv2ray, Bahemmat), parses vless/vmess/trojan/ss/hysteria2/tuic, applies Gate-1 hard-rejects, and dedups across sources on protocol+server+port+credential-hash. Raw configs stay in memory; the only output is a stats JSON — no credentials are stored or committed.
- First live run (2026-11-20): 7/7 sources fetched; 2,581 candidates → 2,554 parse-valid, 27 Gate-1 rejects, 733 duplicates removed → 1,821 unique configs on 1,681 hosts (deduped mix: vless 1,376, ss 263, trojan 77, vmess 56, hysteria2 48, tuic 1).
- Unit tests: `pipeline/test_collector.py` — 18 tests (parser, Gate-1 rejects, dedup), all passing.

Agent: Rick

## 2026-11-20 — Phase 1b source diversification complete

- Phase 1b source diversification complete: 12 candidates sampled across Telegram / CN / RU / FA facets (report: docs/phase1b-diverse-sources.md). Keeps: PulseProxy, @outline_vpn, @Surfboardv2ray, Bahemmat collector. The source registry now spans two near-disjoint large pools, reducing single-pool dependence.

Agent: Rick

## 2026-11-20 — Verifier upgraded to strict mode

- Verifier upgraded to strict mode at wolf's direction: double Gate-3 pass before first publish, 3-probe median latency and speed floors, dual egress/geo confirmation, Gate-1 hard-rejects (incl. placeholder hosts), and quarantine on the first failure — quality over quantity, and the bar is never lowered to fill a post.

Agent: Rick

## 2026-11-20 — Phase 1 source checkup complete

- Phase 1 source checkup complete: 11 sources sampled (report: docs/phase1-source-checkup.md). Keep: ermaozi, NoMoreWalls, mahdibland Eternity; 4 on watch, 4 dropped. Cross-source dedup is mandatory — several top sources are largely the same underlying pool.
- Deployment rule recorded: no GitHub–Cloudflare connection (no CF GitHub App / Workers Builds); Workers deploy via Cloudflare API token only, like Lyra, and the Actions pipeline reaches Cloudflare only via its API.

Agent: Rick

## 2026-11-20 — Rename to MeridianFeed

- Repository renamed Pool-v2ray → MeridianFeed (codename, per the naming & risk rules in docs/PLAN.md); README and plan synced.

Agent: Rick

## 2026-11-20

- Repository created (public) and scaffolded: README, phased plan Rev. 1 (docs/PLAN.md), pipeline and worker notes, source-registry template, .gitignore.
- Plan locked: new Cloudflare account + this new repo, publishing to the existing @Proxiv3 channel; hourly posts; one single VIP subscription link refreshed hourly with best-tier configs only; nothing is published unless it passes real end-to-end verification (controls in every run).

Agent: Rick
