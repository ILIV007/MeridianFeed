# MeridianFeed (Pool-v2ray) — Phase 1b Source Diversification Checkup

- Date: 2026-11-20
- Agent: Rick
- Method: one fetch per candidate (normal browser UA, no retries), same metrics as Phase 1. Subscription payloads base64-decoded where applicable; Telegram channels sampled via the public web preview (`t.me/s/<channel>`, HTML page extract — the preview window only, roughly the last ~20 posts). Dedup key: `protocol + host + port + SHA-256(credential)[:12]`. **Parse-valid is not alive** — alive ratio is Phase 3's job. No config credentials are reproduced in this report; counts and hosts only.
- Overlap baseline: the Phase 1 family pool (peasoft/NoMoreWalls list.txt, 310 unique hosts) was fetched once as a *reference set only* — it is not a candidate and its metrics are not re-reported. Overlap % = share of the candidate's unique hosts that also appear in that family set.
- Not re-sampled: all 11 Phase 1 sources (mahdibland ×2, Pawdroid, free-nodes/v2rayfree, NoMoreWalls, AutoMergePublicNodes, ermaozi, barry-far, freefq, NiREvil, mehdirzfx).

## Results

| # | Source (facet) | Sample URL | HTTP | Fetched | Format | Total entries | Valid | Valid by protocol | Malformed % | Duplicate % (in-sample) | Unique hosts | Overlap with Phase 1 family |
|---|--------|-----------|------|---------|--------|---------------|-------|-------------------|-------------|--------------------------|--------------|------------------------------|
| 1 | Telegram @abc_vpn_configs (Telegram, EN/RU crawler channel) | t.me/s/abc_vpn_configs | 200 | 121,631 B | page extract | 17 | 17 | ss 8, vless 6, trojan 3 | 0.0% | 11.8% | 10 | 20.0% (2 hosts) |
| 2 | Telegram @Surfboardv2ray (Telegram, FA) | t.me/s/surfboardv2ray | 200 | 177,945 B | page extract | 50 | 50 | vless 40, vmess 10 | 0.0% | 24.0% | 38 | 10.5% (4 hosts) |
| 3 | Telegram @outline_vpn (Telegram, FA, ~669K subs) | t.me/s/outline_vpn | 200 | 218,359 B | page extract | 131 | 130 | vless 106, ss 19, vmess 5 | 0.8% | 16.0% | 108 | 11.1% (12 hosts) |
| 4 | Telegram @freeebirdss (Telegram, FA) | t.me/s/freeebirdss | 200 | 11,038 B | page extract | 0 | 0 | — | — | — | 0 | — |
| 5 | nodesfree (CN community site) — v2ray.txt | nodesfree.github.io/v2raynode/v2ray.txt | 200 | **0 B** | — | 0 | 0 | — | — | — | 0 | — |
| 6 | v2raydog-node/free-nodes (CN GitHub) — v2ray.txt | raw.githubusercontent.com/v2raydog-node/free-nodes/main/v2ray.txt | 200 | 7,165 B | base64 | 20 | 20 | vless 11, ss 9 | 0.0% | 0.0% | 20 | **60.0% (12 hosts)** |
| 7 | igareck/vpn-configs-for-russia (RU GitHub) — WHITE-CIDR-RU-checked.txt | raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/WHITE-CIDR-RU-checked.txt | 200 | 1,412 B | plain | 9 | 4 | vless 4 | 55.6% | 33.3% | 1 | 0.0% (0 hosts) |
| 8 | pie-with-jam/PulseProxy (RU GitHub) — githubmirror/30.txt (whitelist file) | raw.githubusercontent.com/pie-with-jam/PulseProxy/main/githubmirror/30.txt | 200 | 218,666 B | plain | 772 | 772 | vless 737, trojan 21, vmess 10, ss 4 | 0.0% | 2.5% | 710 | **0.6% (4 hosts)** |
| 9 | GitVerse KvRuVPN (RU forge, non-GitHub) — KvRuVPN.txt | gitverse.ru/api/repos/ru-wbl/wl/raw/branch/master/KvRuVPN/KvRuVPN.txt | **429** | 0 B | — | 0 | 0 | — | — | — | 0 | — |
| 10 | ebrasha/free-v2ray-public-list (FA GitHub) — vless_configs.txt | raw.githubusercontent.com/ebrasha/free-v2ray-public-list/refs/heads/main/vless_configs.txt | **404** | 0 B | — | 0 | 0 | — | — | — | 0 | — |
| 11 | MohammadBahemmat/V2ray-Collector (FA GitHub, Telegram-channel collector) — all_servers.txt | raw.githubusercontent.com/MohammadBahemmat/V2ray-Collector/main/all_servers.txt | 200 | 288,954 B | plain | 1,103 | 1,087 | vless 708, ss 192, trojan 78, vmess 63, hysteria2 45, tuic 1 | 1.5% | 16.6% | 785 | **39.5% (310 hosts)** |
| 12 | FlareFeed (RU community site on Cloudflare Workers) — fastest.txt | vless.svinakraft.workers.dev/fastest.txt | 200 | 2,051 B | plain | 13 | 7 | vless 4, trojan 2, vmess 1 | 46.2%* | 7.7% | 6 | 50.0% (3 hosts) |

\* FlareFeed's malformed % is inflated by header/comment lines in the file counting as entries; the parseable core is small either way.

## Cross-source findings

- **PulseProxy (#8) is the diversification win.** 772/772 valid, 710 unique hosts, and only **0.6% host overlap** with the Phase 1 family — a genuinely separate pool. It is itself an aggregator of ~29 RU-scene sources, health-checked upstream, VLESS/Reality-heavy and built for Russian whitelist (SNI/CIDR) bypass — a different operator, language scene, and filtering problem than the Phase 1 family.
- **Telegram channels are real, operator-direct diversity — with a scraping caveat.** @outline_vpn (#3) and @Surfboardv2ray (#2) parse at ~100%, with low family overlap (11.1% / 10.5%) and CDN-fronted VLESS-WS hosts the GitHub lists rarely carry. But the public preview only exposes the last ~20 posts, and both channels repost configs (16–24% in-sample duplicates), so per-fetch volume is small; #2 also publishes its own subscription links in pinned posts, which Phase 2 should prefer over post-scraping where available.
- **The FA Telegram-collector repo (#11) is big but drinks from the family pool.** Broadest protocol spread of any Phase 1b sample (incl. hysteria2 45, tuic 1) and 785 unique hosts — yet **39.5% of its hosts are the Phase 1 family set**, and it carries the family's junk fingerprint verbatim: host `127.0.0.53` appears 10×, exactly as in NoMoreWalls/ermaozi. It collects from Telegram channels that themselves republish the family lists. Still ~470 non-family hosts, so it earns a keep — behind the same strict cross-source dedup as ermaozi.
- **The CN GitHub scene overlaps too.** v2raydog-node/free-nodes (#6) is perfectly clean (20/20, 0% dup) but tiny, and 60% of its hosts are family hosts. Clean ≠ independent.
- **Three honest failures, three different causes:** @freeebirdss (#4) returned a valid preview page with zero extractable configs (posts don't expose URIs in preview); nodesfree's fixed sub path (#5) returned HTTP 200 with an empty body — its model is dated blog posts, not a stable endpoint; GitVerse (#9) rate-limited the single permitted fetch (429, not retried). igareck's checked whitelist file (#7) was nearly empty at sample time (9 lines, 1 host) despite the repo being active — the value in that repo sits in its larger unchecked lists, which defeats the point of a pre-checked source.
- **ebrasha (#10):** the well-known FA list's flagship per-protocol file 404s — the repo has restructured into chunk directories and dozens of identical forks make provenance murky. Not measured; needs a path re-discovery before any future verdict.

## Verdicts

| Source | Verdict | Reason |
|--------|---------|--------|
| pie-with-jam/PulseProxy (#8) | **KEEP** | Largest *independent* pool found in either phase: 772 valid, 710 hosts, 0.6% family overlap, 0% malformed, upstream health-checked. RU whitelist/Reality facet the pool completely lacked. |
| Telegram @outline_vpn (#3) | **KEEP** | Biggest Telegram sample: 130 valid, 108 hosts, 99.2% parse rate, 11.1% overlap. FA operator-direct VLESS feed; preview-window volume is the only limit. |
| Telegram @Surfboardv2ray (#2) | **KEEP** | 50/50 valid, 38 hosts, 10.5% overlap, FA scene, VLESS+VMess with CDN-fronted hosts. Prefer its pinned subscription links in Phase 2 over post-scraping; 24% repost dup handled by dedup. |
| MohammadBahemmat/V2ray-Collector (#11) | **KEEP** (dedup-critical) | 1,087 valid and the broadest protocol spread, ~470 hosts outside the family set — but 39.5% family overlap and the `127.0.0.53` junk fingerprint. Only behind strict cross-source dedup + Gate-1 loopback rejection. |
| Telegram @abc_vpn_configs (#1) | **WATCH** | Clean (17/17) EN/RU crawler channel, 20% overlap, but the preview sample is only 17 entries — too thin to judge volume; re-check if Phase 2 adds a channel-history collector. |
| v2raydog-node/free-nodes (#6) | **WATCH** | CN scene, flawless parse, daily updates — but 20 entries and 60% family overlap. A garnish, not diversity. |
| GitVerse KvRuVPN (#9) | **WATCH** (unmeasured) | RU non-GitHub forge is exactly the facet diversity wanted, but the single fetch was rate-limited (429). Re-sample in a later cycle; no verdict on quality yet. |
| ebrasha/free-v2ray-public-list (#10) | **WATCH** (unmeasured) | Sampled flagship path 404s after a repo restructure; fork provenance is murky. Re-discover the current chunk paths before judging. |
| FlareFeed (#12) | **WATCH** | RU Workers-hosted sub site is a genuinely different delivery facet, but fastest.txt yielded only 7 valid entries and 50% host overlap in a tiny sample. Check its full-list file in a later cycle. |
| Telegram @freeebirdss (#4) | **DROP** | Preview exposes zero config URIs — not collectable via the public preview, whatever it posts behind it. |
| nodesfree (#5) | **DROP** | Fixed subscription path returns an empty body; the site is a dated-post blog, not a stable feed a collector can poll. |
| igareck WHITE-CIDR-checked (#7) | **DROP** (this file) | The pre-checked flagship file held 9 lines / 1 unique host at sample time. A checked list this empty adds nothing; its unchecked siblings are out of scope for a strict pipeline. |

## Diversity summary — what Phase 1b adds that Phase 1 lacked

- **A second, independent backbone:** PulseProxy's RU aggregator pool is 99.4% disjoint from the Phase 1 family by host. Combined with the family representative (NoMoreWalls), the registry now has two large pools that do not share upstream — the single biggest diversity gain available.
- **Operator-direct Telegram facet (FA):** @outline_vpn and @Surfboardv2ray post configs from their own operator channels (CDN-fronted VLESS-WS, speedtest/host-trick SNIs) rather than re-listing GitHub subs — new geos (EU Hetzner/FR/DE + US) and a transport style underrepresented in Phase 1.
- **A Telegram-collection facet with eyes open:** Bahemmat adds ~470 non-family hosts and the best hysteria2/TUIC counts outside NoMoreWalls, but its 39.5% family overlap proves Telegram collectors partially re-publish the same lists — Phase 2's cross-source dedup and the Phase 3 batch caps (≤30% per source, per-IP/ASN caps) are what turn this from noise into diversity.
- **Scenes checked and found wanting (for now):** the CN GitHub scene (v2raydog) largely re-serves family hosts; CN community sites (nodesfree) don't expose a stable feed; the RU forge facet (GitVerse) and the FA list facet (ebrasha) are promising but were unmeasurable in one polite fetch (429 / restructured paths) — both stay on the watch list for a later cycle rather than being guessed at.
- **Net registry after Phase 1 + 1b:** 4 Phase-1 keeps/watches with real volume (ermaozi, NoMoreWalls, Eternity, EternityAir) + 4 new keeps (PulseProxy, @outline_vpn, @Surfboardv2ray, Bahemmat) spanning GitHub aggregators (CN/RU/FA), a Workers-hosted RU sub, and operator-direct Telegram channels — with dedup and batch-composition caps doing the rest.

— Agent: Rick
