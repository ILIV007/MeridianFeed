# Plan Rev.2 — R4 adoption checklist (execute when windows complete)

Prepared 2026-11-20 (Agent: Rick) so the weekly survival audit or a
follow-up run can execute R4 without re-derivation. Evidence:
`docs/plan-rev2-r0-report.md`. Local `dir`-mode snapshots for all
candidates were taken 2026-11-20 ~08:29Z (observation store);
**windows complete ~2026-11-21 ~08:30Z** — take the closing snapshot
set first, then work this list top to bottom.

## 1. Closing measurements
- [ ] Re-snapshot every candidate into the observation store
      (same URLs as the R0 set: radikal-verified, radikal-fast,
      whitedns-sub, delta-kronecker, au1rxx-allverified (6 shards
      concatenated), v2go, latinasub, au1rxx-single, patterniha-output).
- [ ] Run `pipeline/survival.py dir <obs-dir>` and record the table
      in `docs/survival-log.md` (dated R4 entry).
- [ ] Re-run `pipeline/survival.py gh Au1rxx/free-vpn-subscriptions
      output/all-verified/v2ray-base64-0001.txt` to confirm the
      0.854 @24h bar-pass on fresh history.

## 2. Adoptions into pipeline/sources.json (flagged, full gates)
- [ ] **Au1rxx** — bar PASSED (0.854 @24h on shard 0001). Adopt the
      concatenated all-verified shards as ONE upstream
      (type github-raw cannot concatenate; either adopt shard 0001
      alone or add a multi-URL source — decide by the closing
      whole-file survival: if the concatenated dir-mode figure is
      ≥ shard-0001's, prefer a collector multi-URL entry).
      facet `aggregator-verified`, volatility `volatile`.
- [ ] **LatinaSub** (`result/sub`, 0.777) and **v2go**
      (AllConfigsSub.txt, 0.694) — verified-corpus class: adopt
      under governance per the R0 reconciled rule (admission =
      publisher discipline + first-week Gate-3 contribution/yield;
      auto-disable polices thereafter). facet `aggregator-verified`.
- [ ] **whitedns-sub** (base64.txt, 0.561) and **Delta-Kronecker**
      (config/all_configs.txt, 0.531) — same class, same terms.
      Delta is a raw aggregate (2,269 keys): expect a large
      duplicate share; its value is the sole-stable long tail.
- [ ] **Radikal fast/top100** — do NOT adopt (verified tier already
      ingested at R1; fast is a subset funnel of the same corpus).
- [ ] **patterniha/Free-Configs output** — REJECTED as a source
      (2 keys). No action; patterns already adopted in R1/R3.

## 3. Verdicts (from the R0 reconciliation)
- [ ] **NoMoreWalls: disable.** Set `enabled: false` in sources.json
      with a note citing the three metrics (unique yield 19/340 and
      shrinking; working persistence 0.00 over 15 runs; Radikal
      cascade 1.27% / 951 ms median; ermaozi covers 94.3%), and
      record the disable in governance_state.json + survival log.
      Keep the registry entry (history must not be lost).
- [ ] **mahdibland-eternity: KEEP** — record the keep decision and
      its numbers in the survival log (112 unique/cycle; verified-key
      persistence 1.00; list persistence 0.800 @24h).

## 4. Fold into the weekly audit (Phase D)
- [ ] Add every adopted source to `survival_weekly.py`'s measured
      set (gh mode for the GitHub-file sources) and to the
      governance yield review (a fresh collect + governance update
      ships in the same PR as the log entry).
- [ ] Confirm the audit flags any adopted verified-corpus source
      whose Gate-3 pass contribution is zero after its first week —
      that, not file persistence, is this class's demotion trigger.

## 5. Ship
- [ ] One PR: sources.json + governance_state.json + survival-log
      entry + CHANGELOG note, `Agent: Rick` tags, tests green.
- [ ] After merge, watch the next two hourly composes: report pool
      sizes and the non-US eligible supply movement (the constraint
      R4 exists to relieve) in the survival log entry.

— Agent: Rick
