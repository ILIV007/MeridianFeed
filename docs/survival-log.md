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
