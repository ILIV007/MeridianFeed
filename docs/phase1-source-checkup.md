# Pool-v2ray — Phase 1 Source Checkup

- Date: 2026-11-20
- Agent: Rick
- Method: one fetch per source (normal browser UA, no retries), subscription payloads base64-decoded where applicable, every entry parsed for protocol / host / port / credential. Dedup key: `protocol + host + port + SHA-256(credential)[:12]`. **Parse-valid is not alive** — dead-rate is measured in Phase 3, not here. No config credentials are reproduced in this report; counts and hosts only.

## Results

| # | Source | Sample URL | HTTP | Fetched | Format | Total entries | Valid | Valid by protocol | Malformed % | Duplicate % (in-sample) | Unique hosts | Repo last push |
|---|--------|-----------|------|---------|--------|---------------|-------|-------------------|-------------|--------------------------|--------------|----------------|
| 1 | mahdibland/V2RayAggregator — Eternity (speed-test-filtered track) | raw.githubusercontent.com/mahdibland/V2RayAggregator/master/Eternity.txt | 200 | 30,549 B | plain | 200 | 198 | ss 172, trojan 16, vmess 10 | 1.0% | 0.0% | 189 | 2026-11-19 |
| 2 | mahdibland/V2RayAggregator — EternityAir (airport track) | raw.githubusercontent.com/mahdibland/V2RayAggregator/master/EternityAir.txt | 200 | 9,613 B | plain | 61 | 61 | trojan 60, vmess 1 | 0.0% | 0.0% | 22 | 2026-11-19 |
| 3 | Pawdroid/Free-servers — sub | raw.githubusercontent.com/Pawdroid/Free-servers/main/sub | 200 | 3,100 B | base64 | 10 | 10 | vless 5, ss 3, trojan 2 | 0.0% | 10.0% | 9 | 2026-11-19 |
| 4 | free-nodes/v2rayfree — sub | raw.githubusercontent.com/free-nodes/v2rayfree/main/sub | 200 | 4,568 B | base64 | 18 | 18 | ss 10, vless 8 | 0.0% | 0.0% | 18 | 2026-11-19 |
| 5 | peasoft/NoMoreWalls — list.txt | raw.githubusercontent.com/peasoft/NoMoreWalls/master/list.txt | 200 | 84,944 B | base64 | 379 | 345 | vless 151, ss 112, hysteria2 41, trojan 24, vmess 16, tuic 1 | 9.0% | 2.6% | 311 | 2026-11-19 |
| 6 | chengaopan/AutoMergePublicNodes — list.txt | raw.githubusercontent.com/chengaopan/AutoMergePublicNodes/master/list.txt | 200 | 87,804 B | base64 | 423 | 350 | vless 153, ss 115, hysteria2 41, trojan 24, vmess 16, tuic 1 | 17.3% | 2.9% | 316 | 2026-11-19 |
| 7 | ermaozi/get_subscribe — v2ray sub endpoint | blog.ermao.net/sub/v2ray/ermao.net | 200 | 91,404 B | plain | 492 | 457 | vless 255, ss 108, hysteria2 44, trojan 34, vmess 16 | 7.1% | 16.8% | 346 | 2026-11-19 (repo) |
| 8 | barry-far/V2ray-Configs — All_Configs_Sub.txt | raw.githubusercontent.com/barry-far/V2ray-Configs/master/All_Configs_Sub.txt | **404** | 0 B | — | 0 | 0 | — | — | — | 0 | — (see verdict) |
| 9 | freefq/free — README.md (curated list) | raw.githubusercontent.com/freefq/free/master/README.md | 200 | 5,643 B | page extract | 14 | 14 | vmess 9, ss 5 | 0.0% | 0.0% | 10 | **2024-08-20** |
| 10 | NiREvil/vless — sub/v2rayng-wg.txt | raw.githubusercontent.com/NiREvil/vless/main/sub/v2rayng-wg.txt | 200 | 34,113 B | plain | 118 | 118 | wireguard 118 | 0.0% | 0.8% | 101 | 2026-11-19 |
| 11 | mehdirzfx/v2ray-sub — README.md (link collection) | raw.githubusercontent.com/mehdirzfx/v2ray-sub/main/README.md | 200 | 120,871 B | page extract | 0 config URIs (427 sub/list links found) | 0 | — | — | — | 0 | 2026-11-19 |

## Cross-source findings (the important part)

- **The NoMoreWalls family is one pool wearing three hats.** NoMoreWalls (#5), AutoMergePublicNodes (#6, a NoMoreWalls fork) and ermaozi (#7) share near-identical protocol counts (vmess 16 / hysteria2 41–44 / tuic 1) and the same top hosts. Counting them as three independent sources would triple-count the same configs — Phase 2 must dedup across sources with the credential-hash key, and source *diversity* is lower than the source *count* suggests.
- **Junk signal:** host `127.0.0.53` (the systemd-resolved stub address) appears 10× as a config host in #5, #6 and #7. A remote proxy cannot live there; those entries are placeholder/broken and Gate 1 in Phase 3 should hard-reject loopback/reserved hosts.
- **Eternity (#1) is small but pre-filtered:** exactly 200 entries, 0% duplicates, upstream runs its own speed test before publishing. SS-heavy (87%), which caps its value for VLESS/REALITY-first users.
- **EternityAir (#2) is one operator:** 43 of 61 entries sit on three `jcnode.top` hostnames — trial/airport nodes that typically expire fast.
- **barry-far is gone, not just moved:** the raw file 404s and the GitHub API reports the repository as access-blocked (ToS) since 2025-05-22. Any source list still pointing at it is stale by definition.

## Verdicts

| Source | Verdict | Reason |
|--------|---------|--------|
| mahdibland Eternity (#1) | **KEEP** | Cleanest sample measured: 99% parse rate, 0% dup, upstream speed-filtered, fresh daily. SS-heavy, so a supporting source, not the backbone. |
| peasoft/NoMoreWalls (#5) | **KEEP** | Largest diverse family pool (345 valid, best hysteria2/TUIC coverage), 91% parse rate, actively updated. Primary representative of its family. |
| ermaozi/get_subscribe (#7) | **KEEP** (dedup-critical) | Biggest valid count (457) and the richest VLESS share (255). But 16.8% internal duplicates and heavy overlap with #5 — only worth it behind strict cross-source dedup. Its own README admits its check is TCP-connect only, so Phase 3 must re-verify everything. |
| mahdibland EternityAir (#2) | **WATCH** | Parses perfectly but is a single airport operator's trial nodes (43/61 on 3 hostnames); expect fast expiry. Re-check alive-ratio in Phase 3 before promoting. |
| Pawdroid/Free-servers (#3) | **WATCH** | Hand-curated and clean, but only 10 entries — a trickle, not a pool. Possible VIP-tier garnish if its alive-ratio proves high. |
| free-nodes/v2rayfree (#4) | **WATCH** | Same story: 18/18 valid, 18 unique hosts, updated daily, but volume is negligible on its own. |
| mehdirzfx/v2ray-sub (#11) | **WATCH** (meta-source) | Not a feed — a 427-link index of other sources. Useful as a discovery list for future source hunting; nothing to collect from it directly. |
| chengaopan/AutoMergePublicNodes (#6) | **DROP** | Redundant: a NoMoreWalls fork with a near-identical valid set to #5 but a worse malformed rate (17.3% vs 9.0%). Adds noise, not diversity. |
| barry-far/V2ray-Configs (#8) | **DROP** | Repository access-blocked by GitHub (ToS, 2025-05-22); sampled file returns 404. Dead source. |
| freefq/free (#9) | **DROP** | Stale: repo last pushed 2024-08-20 and the README yields only 14 config URIs. A 15-month-old free-node list is a dead-node list. |
| NiREvil/vless wg file (#10) | **DROP** (for this pipeline) | The sampled feed is 100% WireGuard URIs — outside the Phase 2 protocol scope (vless/vmess/trojan/ss/hysteria2/tuic). The repo's Cloudflare-IP assets may be useful for Phase 4, but its sub feed is not a source for this pool. |

## Summary ranking (by usable, parse-valid, non-duplicate volume)

1. **ermaozi (#7)** — 457 valid, ~380 unique after in-sample dedup; VLESS-richest.
2. **peasoft/NoMoreWalls (#5)** — 345 valid, ~336 unique; broadest protocol spread.
3. **mahdibland Eternity (#1)** — 198 valid, 198 unique; highest quality per entry, SS-heavy.
4. **mahdibland EternityAir (#2)** — 61 valid; concentrated, fragile.
5. **free-nodes/v2rayfree (#4)** — 18 valid. **Pawdroid (#3)** — 10 valid, ~9 unique. Clean trickles.

**Bottom line for Phase 2:** build the collector on **3 keep sources** (ermaozi + NoMoreWalls + Eternity) with **3 watch sources** behind them (EternityAir, Pawdroid, v2rayfree), cross-source dedup from day one, and a Gate-1 rule rejecting loopback/reserved hosts. Realistic combined intake after cross-dedup is roughly **700–900 unique parse-valid configs per cycle** (estimate from the overlaps measured above) — plenty of raw material for the Phase 3 verifier; the alive ratio of that intake is the next number that matters, and only Phase 3 can measure it.

— Agent: Rick
