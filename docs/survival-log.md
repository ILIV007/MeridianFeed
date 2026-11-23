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
