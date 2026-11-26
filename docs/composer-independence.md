# Composer independence — GitHub Actions migration

Goal (wolf's standing rule): the system runs itself. Verification
already runs on GitHub Actions and publishing/serving on Cloudflare
Workers; this migration moves the last operator-machine piece — the
hourly composer — into GitHub Actions so the loop is:

```text
Cloudflare cron tick -> GitHub Actions compose (heavy work only) -> Cloudflare KV -> Workers
```

No operator runtime is in the loop after cutover. The former local
cron stays untouched as fallback until the cutover checklist below
is complete.

## What runs where

- `.github/workflows/compose.yml` — `workflow_dispatch` only
  (dry-run/live mode choice). The clock is Cloudflare's:
  `meridian-pub`'s `45 * * * *` UTC cron (= :15 Tehran, ahead of
  the :33 Tehran post) dispatches it. GitHub scheduling is not
  used (wolf's rule: Cloudflare owns triggers; GitHub use is kept
  to the heavy verify/compose execution only). The tick needs the
  `TICK_TOKEN` Worker secret (repo-scoped, Actions write only);
  without it the tick fails closed and records `tick_status` in KV.
  KV `tick_mode` selects dry-run (default) or live dispatch.
- `pipeline/composer/run_compose.py` — downloads the newest verify
  stats + URI-map artifacts with the built-in `GITHUB_TOKEN`,
  snapshots KV `feedback` / `vip_index` / `public_pool`, runs the
  composer, and writes KV only in live mode.
- `pipeline/composer/compose.py` — the strict composer, selection
  logic unchanged (gates, field-profile rules, VIP floor/tiers,
  country ceiling, rescue rule). Only paths moved to runner state.

## Modes and fail-closed behaviour

- **dry-run** (default): composes and reports `would_write`; never
  writes KV. Scheduled runs stay dry-run while the `COMPOSER_LIVE`
  repo variable is not `true`.
- **live**: requires `CF_KV_API_TOKEN`, `CF_ACCOUNT_ID`, and
  `CF_KV_NAMESPACE_ID`. Missing configuration or a KV read failure
  exits non-zero with no KV writes. Empty fresh pools never
  overwrite last-known-good. If the newest completed verify run is
  over 50 minutes old, the runner dispatches a fresh verify run and
  exits (dispatch-and-exit, unchanged from the local cron).

## State persistence on ephemeral runners

| State | Persistence |
| --- | --- |
| verify stats + pin maps | downloaded per run from verify artifacts |
| feedback / previous pools | read from KV at compose start |
| vip_sub change detection | sha256 vs current KV value (no local state file) |
| uri_cache / source snapshots | Actions cache (accelerator only; pin maps are primary) |
| compose summary/log | uploaded as a 30-day artifact (counts only, no URIs) |

## One-time owner setup (names/scopes only)

Add these in GitHub repo Settings -> Secrets and variables ->
Actions. Never paste secret values into chat or docs.

- Secret `CF_KV_API_TOKEN`: a Cloudflare API token for the Meridian
  account with **Workers KV Storage: Edit** only (no Workers Scripts
  edit, no DNS, no other accounts).
- Variable `CF_ACCOUNT_ID`: the Meridian Cloudflare account id.
- Variable `CF_KV_NAMESPACE_ID`: the `MERIDIAN_STORE` namespace id.
- Variable `COMPOSER_LIVE`: leave unset/`false` until cutover, then
  set to `true`.

`GITHUB_TOKEN` is built in; the workflow requests `contents: read`
and `actions: write` (artifact download + verify dispatch).

## Cutover checklist

1. Add the secret/variables above (`COMPOSER_LIVE` still off).
2. Run `compose` manually in dry-run mode; confirm the summary
   shows `kv_reads: available` and sane pool sizes/tiers.
3. Run `compose` manually in live mode once; confirm both
   subscription routes serve the refreshed set and the next :33
   post lands.
4. Set `COMPOSER_LIVE=true`.
5. Disable the former local `meridian-compose-hourly` cron.
6. Watch the next two scheduled compose runs + posts.

Rollback: set `COMPOSER_LIVE=false` (Actions returns to dry-run)
and re-enable the local cron; KV last-known-good keeps serving
throughout.

## Cutover complete (2026-11-26)

- The Cloudflare tick is live: `meridian-pub` dispatches compose at
  :15 Tehran with KV `tick_mode` set to the raw value `live`
  (a JSON-quoted value silently selects dry-run — write raw).
- Two cycles proven, the second with the local cron already
  disabled; the former local `meridian-compose-hourly` cron is
  retired (disabled, kept only as a documented rollback lever).
- Rollback remains: set KV `tick_mode` to `dry-run` (raw) and
  re-enable the local cron; KV last-known-good keeps serving.

Agent: Rick
