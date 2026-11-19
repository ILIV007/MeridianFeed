# Changelog

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
