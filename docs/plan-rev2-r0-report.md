# Plan Rev.2 — R0 report: source trials & metric reconciliation (2026-11-20)

Method: `pipeline/survival.py` in `gh` mode over each repo's commit
history (exact dedup-key persistence, the production collector's key),
plus local `dir`-mode snapshots taken 2026-11-20 ~08:29Z into the
observation store (windows complete ~2026-11-21 ~08:30Z). Controls in
the same style as Radikal's audits: our positive reference is the
incumbent set measured by the same harness; there is no negative
control in a persistence measurement, so cross-metric checks below
carry that role. All figures measured, none quoted from READMEs.

## Trial results — exact-key survival (gh history)

| Candidate | File measured | Snaps | Span | Keys now | @6h | @24h | ≥85% @24h |
|---|---|---|---|---|---|---|---|
| Au1rxx/free-vpn-subscriptions | output/all-verified/v2ray-base64-0001.txt | 96 | 94.9 h | 1,172 | 0.911 | **0.854** | **PASS** |
| LalatinaHub/LatinaSub | result/sub | 96 | 717.5 h | 207 | 0.879 | 0.777 | below |
| Danialsamadi/v2go | AllConfigsSub.txt | 96 | 705.8 h | 648 | 0.766 | 0.694 | below |
| 0xRadikal/Free-v2ray-Configs | verified/configs.txt | 55 | 2,709.9 h | 744 | 0.653 | 0.572 | below |
| iampedii/whitedns-sub | base64.txt | 96 | 510.0 h | 84 | 0.608 | 0.561 | below |
| 0xRadikal (reference tier) | fast/configs.txt | 55 | 2,709.9 h | 582 | 0.660 | 0.558 | below |
| Delta-Kronecker/V2ray-Config | config/all_configs.txt | 96 | 2,189.8 h | 2,269 | 0.701 | 0.531 | below |
| patterniha/Free-Configs | configs.txt (its output) | 96 | 1,949.0 h | **2** | 0.456 | 0.415 | REJECT as a source |
| *(incumbent)* mahdibland-eternity | Eternity.txt | 96 | 1,153.9 h | 199 | — | 0.800 | incumbent |
| *(incumbent)* peasoft/NoMoreWalls | list.txt | 96 | 686.8 h | 333 | 0.825 | 0.717 | incumbent |

Reading the table honestly:

- **Au1rxx clears the adoption bar outright** (0.854 @24h, 80 pairs) —
  the only candidate that does. Caveat: the measurement is on shard
  0001 of 6; keys may migrate between shards, which would depress
  single-shard persistence — it passed anyway. The concatenated
  all-shards snapshot is accruing in `dir` mode for the R4 whole-file
  confirmation.
- **The rest of the class clusters at 0.53–0.78, and that is a class
  property, not seven independent failures.** These are *rotating
  verified-set publishers*: the file is replaced each cycle with the
  currently-verified corpus, so a key leaves when it fails one of the
  publisher's own rounds and re-enters when it passes again. Exact-key
  persistence of the FILE understates per-config quality for this
  class — Radikal's own verified tier, the best-engineered of the
  set, scores 0.572 by this metric while its configs pass three real
  tunnel rounds before listing. The ≥85% bar was calibrated on
  curated LIST sources (PulseProxy ~0.91, Eternity 0.80); applying it
  unchanged to the verified-corpus class would reject the entire
  class, including the strongest verification pipelines we found.
- **patterniha/Free-Configs' published output is not a source** (2
  parse-valid keys today). Its value to this project is its transform
  and dedup patterns (R1/R3) and its source list — whose members we
  trial directly. Recorded as rejected-as-source, patterns adopted.
- LatinaSub's feed WAS found (`result/sub`, published by its hunt
  workflow) — the earlier "endpoint-not-found" note is superseded.
  At 0.777 it is the strongest of the below-bar class, consistent
  with Radikal's cascade audit (60–64% stable, 41–46 sole-stable).

**Reconciled adoption rule (for R4):** list-class sources keep the
≥85% @24h persistence bar. Verified-corpus-class sources (Radikal
verified, LatinaSub, v2go, whitedns-sub, Delta-Kronecker, Au1rxx
shards beyond the bar-passing measurement) are admitted as FLAGGED
upstreams under governance instead: admission evidence is the
publisher's own real-test discipline + our measured Gate-3 pass
contribution and unique yield over the first week; the R1
auto-disable (zero yield over the rolling window) and the Phase D
weekly audit police them thereafter. No trust is transferred either
way — every config faces the full gates, pinning and tier rules.
This mirrors the Eternity/NoMoreWalls reconciliation below: no
single metric decides a source's fate.

## Reconciliation — Eternity & NoMoreWalls

Radikal retired both from their list (their `scripts/sources.py`
records the measurements). Three metrics, measured independently on
both sides, reconcile as follows:

**Subset structure (verified by us on current data):**
- Eternity's 199 keys are a **100.00% subset** of mahdibland's own
  `sub/sub_merge.txt` (4,171 keys) — Radikal's claim reproduces
  exactly. But we do not ingest sub_merge, so within OUR registry
  Eternity's yield is not zero: **112 of its 199 keys are unique
  against the rest of our pool** (live collect, 2026-11-20).
- NoMoreWalls `list.txt` and `list_raw.txt` are the identical key set
  (Jaccard 1.0), so Radikal's audit of list_raw applies to the file
  we fetch. **94.3% of its keys are already in ermaozi** (which we
  keep and which is collected first); its unique yield today is
  **19 of 340 valid (5.6%)** — Phase 2 measured 53; it is shrinking.

**Working stability (theirs):** Radikal's real cascade (xray-knife,
3 rounds): Eternity 72/200 stable (36%) but **0 fresh-stable** — every
stable Eternity key also arrived via sub_merge, so its marginal
value TO THEM was zero. NoMoreWalls: **2/157 stable (1.27%)**,
median latency 951 ms, 0 fresh-stable; production-calibrated 0.34%.

**Working persistence (ours):** across the 15 verifier stats files
of 2026-11-20 (~9 h span), of the keys each source got through
Gate 3 in the first 3 runs, the fraction still passing in the last
3 runs: **Eternity 29/29 = 1.00** (and it was the largest single
pass contributor in the latest run, 32/96), ermaozi 0.92,
PulseProxy 0.79, bahemmat 0.30, Surfboard 0.35 — and
**NoMoreWalls 0/13 = 0.00**. (Attribution caveat: a passed key is
credited to the source whose copy the sampler drew; NoMoreWalls'
keys mostly also exist in ermaozi, which strengthens rather than
weakens the conclusion — the sampler can always get them from
ermaozi instead.)

**Verdicts (to be applied at R4):**
- **mahdibland-eternity: KEEP.** Radikal's retirement logic does not
  transfer: their zero was relative to a file we do not ingest.
  Here it yields 112 unique keys per cycle, its verified keys are
  the most persistent in the registry (1.00), and its list
  persistence (0.800 @24h) is the best of the family. It stays a
  keep, watched by governance like everything else — if a future
  ingest ever absorbs its corpus, its yield will fall and the
  auto-disable will catch it on evidence, not on analogy.
- **peasoft/NoMoreWalls: DEMOTE — disable.** All three metrics
  agree: unique yield 19 and shrinking, working persistence 0.00,
  cascade stability 1.27% with a 951 ms median that would fail our
  latency floors anyway. ermaozi covers 94.3% of its keys and is
  the family's strictly better representative. Disabling saves a
  full fetch + parse per cycle for ~19 low-quality keys. This is
  exactly the profile the R1 governance auto-disable exists for;
  the R4 step applies it through that mechanism (registry note +
  governance record in the survival log), so the precedent is
  procedural, not manual.

## First R1 ingest measurement (Radikal verified, live collect)

With radikal-verified added last in registry order (so incumbent
attribution is undisturbed): 1,024 valid → 640 duplicates of the
incumbent pool → **377 unique_new candidates per cycle** — the
largest single supply injection since Phase 2, aimed exactly at the
eligible-supply constraint (triple-pass VIP supply was US 41 /
non-US 4). Identity dedup collapsed a further 11 same-service
listings pool-wide; CF shape drops removed 3 plaintext-443 nodes.
Unique records per collect: 1,859 → **2,336**.

— Agent: Rick
