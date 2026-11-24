# Survival log — per-source exact-key survival (Phase D)

Weekly automated audit (`pipeline/survival.py`): a keep source that
drops below **85% key survival at 24 h** (or turns volatile) is flagged
here. Quiet by default — records only, nothing is posted anywhere.

## 2026-11-20 — baseline (harness series starts)

Measured with `pipeline/survival.py` (GitHub commit-history snapshots):

| Source | Snapshots | Span | Survival @24h | Verdict |
|---|---|---|---|---|
| mahdibland-eternity (keep) | 96 | 1153.9 h | 0.80 | incumbent keep — tracked weekly from here |
| mahdibland-eternityair (candidate) | 48 | 116.2 h | 0.00 (@6h: 0.018) | REJECTED — airport-merge firehose |
| pulseproxy githubmirror/1.txt (candidate) | 48 | 324.5 h | — (0 valid keys now) | NOT ADOPTED — shard retired/empty |

Observing (endpoint-class, local snapshots; windows complete
2026-11-21 ~07:41Z): flarefeed-fastest, kvruvpn (429 at first
snapshot), surfboard-preview.

— Agent: Rick

## 2026-11-23 — weekly survival audit

| Source | Snapshots | Span (h) | Survival @24h |
|---|---|---|---|
| NoMoreWalls | 96 | 706.0 | 0.718 |
| mahdibland-eternity | 96 | 1141.3 | 0.803 |
| pulseproxy | 96 | 46.9 | 0.891 |
| bahemmat-collector (volatile class) | 96 | 27.6 | 0.179 |
| au1rxx-allverified (observing) | 1 | 0.0 | — |
| au1rxx-single (observing) | 1 | 0.0 | — |
| delta-kronecker (observing) | 1 | 0.0 | — |
| flarefeed-fastest (observing) | 1 | 0.0 | — |
| kvruvpn (observing) | 1 | 0.0 | — |
| latinasub (observing) | 1 | 0.0 | — |
| patterniha-output (observing) | 1 | 0.0 | — |
| radikal-fast (observing) | 1 | 0.0 | — |
| radikal-verified (observing) | 1 | 0.0 | — |
| surfboard-preview (observing) | 1 | 0.0 | — |
| v2go (observing) | 1 | 0.0 | — |
| whitedns-sub (observing) | 1 | 0.0 | — |

**FLAGS (below the 85% @24h bar):** NoMoreWalls: 0.718 @24h < 0.85 bar; mahdibland-eternity: 0.803 @24h < 0.85 bar; bahemmat-collector (volatile class): 0.179 @24h < 0.85 bar

— Agent: Rick

## 2026-11-24 — Plan Rev.2 R4 adoptions (closing measurements)

Closing snapshots taken 2026-11-24 ~12:11Z into the local observation
store (first snapshots 2026-11-20 ~08:29Z; span 99.7 h). Two snapshots
~100 h apart give no in-tolerance 24 h pair in `dir` mode, so the
table below reports exact-key persistence over the ~100 h window
instead (fraction of the Nov-20 keys still present Nov-24); the
@24h bar-pass for Au1rxx is re-confirmed separately in `gh` mode on
fresh commit history.

| Candidate | Keys Nov-20 | Keys Nov-24 | Kept | ~100h persistence | Verdict |
|---|---|---|---|---|---|
| au1rxx-allverified (6 shards concat) | 1,368 | 1,368 | 1,368 | 1.000 | **ADOPTED** (multi-URL) |
| au1rxx-single (shard 0001) | 565* | 1,172 | 287 | 0.508 | bar-pass confirmed in gh mode (below) |
| latinasub | 207 | 205 | 121 | 0.585 | **ADOPTED** (verified-corpus class) |
| v2go | 648 | 506 | 324 | 0.500 | **ADOPTED** (verified-corpus class) |
| whitedns-sub | 84 | 65 | 28 | 0.333 | **ADOPTED** (verified-corpus class) |
| radikal-verified | 744 | 617 | 426 | 0.573 | already adopted (R1) — reference |
| radikal-fast | 582 | 459 | 349 | 0.600 | NOT adopted (subset funnel of verified) |
| delta-kronecker | 2,269 | — | — | — | **NOT adopted — upstream repo gone (404)** |
| patterniha-output | 2 | 6 | 0 | 0.000 | REJECTED as a source (confirmed) |

\* The Nov-20 au1rxx-single snapshot was a different single file, not
shard 0001 — its 0.508 figure is not a shard-0001 measurement and is
not used for the decision.

**Au1rxx bar-pass re-confirmed (gh mode, fresh history):** shard 0001,
96 snapshots, span 94.9 h — **0.854 @24h (80 pairs), bar_85_at_24h:
true**, identical to the R0 figure. **Caveat found at R4:** the
upstream repo last committed to these files on **2026-10-30** — the
gh history covers the publisher's active period (Oct 26–30) and the
concatenated file is byte-identical Nov 20 → Nov 24 (upstream
frozen). The adoption is therefore a one-time supply injection
(~1,368 keys on first collect); expect zero unique yield afterwards
and retirement by the R1 governance auto-disable on evidence. The
multi-URL entry is preferred per the checklist rule (concatenated
figure ≥ shard-0001's) and yields the full set, not just shard 0001.

**Delta-Kronecker NOT adopted:** `Delta-Kronecker/V2ray-Config`
returns 404 (repo page and API) as of 2026-11-24 — the upstream is
gone; there is nothing to ingest. Its Nov-20 snapshot stays in the
observation store as history only.

**Verdicts applied at R4:** **NoMoreWalls DISABLED** (registry
`enabled: false` + governance record; unique yield 19/340 shrinking,
working persistence 0.00, cascade 1.27% / 951 ms, ermaozi covers
94.3%; weekly audit 2026-11-23: 0.718 @24h). **mahdibland-eternity
KEPT** (112 unique/cycle; verified-key persistence 1.00; list 0.800
@24h; weekly audit 2026-11-23: 0.803).

**Weekly-audit fold-in:** the four adopted sources join
`survival_weekly.py` GH_KEEPS (gh mode: Au1rxx shard 0001,
LatinaSub `result/sub`, v2go `AllConfigsSub.txt`, whitedns-sub
`base64.txt`). **Verified-corpus demotion trigger:** a source in this
class whose Gate-3 pass contribution is zero after its first week is
demoted — measured from the verifier stats files (`passes[].source`
attribution, which the composer already downloads); first-week review
due 2026-12-01. Governance zero-yield auto-disable polices unique
yield in the meantime.

— Agent: Rick

## 2026-11-24 — First post-merge verify run with the R4 registry (run 45408448347)

First verify run on the post-R4/R5.1 registry (dispatched 13:55Z, completed ~14:22Z; controls ok; verifier 1.3.0). The R4 adoption lands as a supply jump, and all four adopted sources contribute Gate-3 passes in week 1.

**Funnel:** fetched **12,921** (pre-merge runs ~4,900) → gate1_valid 12,895 → unique **4,669** (profile 1,088 / other 3,581; pre-merge ~2,500–3,059) → sampled 900 (600 profile + 300 other) → Gate 2 passed 784 → Gate-3 passed **183** (pre-merge latest 160; public-criteria 124; profile-class 60). By protocol: ss 94, vless 36, vmess 25, hysteria2 25, trojan 3. Egress: US 75 (41% of passes — the leading share, under the 50% ceiling), DE 24, PL 17, NL 13, JP 9. `akamai_fronted` 0 — no Akamai-fronted candidates yet, as expected (the surface exists; supply has not appeared).

**Gate-3 passes by source (183 total):** v2go **67**, radikal-verified 44, mahdibland-eternity 23, **au1rxx-allverified 14**, latinasub 9, alireza-collector 8, bahemmat-collector 6, ermaozi 6, whitedns-sub 6. **All four R4-adopted sources contribute in week 1 — the verified-corpus demotion trigger (zero contribution after week 1) is NOT hit for any of them.** v2go is the single largest contributor (37% of passes) on its first run under the new registry. Au1rxx's 14 passes are consistent with the one-time injection (~1,368 keys first collect); its unique yield afterwards is expected to fall to zero and governance auto-disable retires it on evidence.

**First live MASQUE hunt numbers (`stats["hunt"]`):** 118 targets tested, **79 reachable, 64 TLS-OK on 443** (443: 69 reachable, 8443: 5, 500/1701/4500/4443/8095: 1 each; latency median 1.83 ms — runner-local anycast, as expected). Scope honesty stands: TCP/TLS liveness only, NOT a MASQUE protocol proof; the hunt never feeds the pools. The WARP/MASQUE endpoint surface is largely alive from the runner — the hunt is now a standing per-run measurement.

**Gate-IR this run:** 69 endpoints, reachable 2 / unreachable 0 / neutral 67 (97% neutral; controls via Globalping, positive ok). The API stage still gives almost no signal — the R6.2 browser checker (built 2026-11-24) is the residential vantage that has to carry this.

**Note on per-source unique_new:** the verifier stats artifact and the job log carry `passes[].source` (Gate-3 contribution, above) but no per-source collect counts — unique yield per source is measured by the weekly survival audit from snapshots (next: Mon 2026-11-30 09:55 Tehran), which also polices the Au1rxx retirement. The aggregate supply jump (fetched +8,000, unique +~1,600–2,100 vs pre-merge) is consistent with the Au1rxx injection plus the verified-corpus sources.

— Agent: Rick
