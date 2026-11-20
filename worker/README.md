# Workers — publisher, VIP subscription & bot (Phases 4–6)

Three small Cloudflare Workers on the project's own Cloudflare account, plus a
fourth (anchor) that is written but currently blocked — see Phase 4 below.
They publish only what the GitHub Actions pipeline has already proven; none of
them verifies configs and none of them ever posts untested entries.

Deployed names are codenames only (no branding, no sensitive words). Branding
lives exclusively in Telegram message text.

## meridian-pub — hourly publisher (Phase 5)

- Cron `33 * * * *` (UTC): reads `public_pool` from KV `MERIDIAN_STORE` and
  posts one Telegram **Rich Message** batch to @Proxiv3 via the bot
  (header 🪼 PROXIV3, one copyable block per config).
- **At most 5 configs per post** (wolf's rule, 2026-11-20): the composer
  caps the pool at 5 and the Worker slices to `MAX_POST_CONFIGS = 5`
  again at render — never padded.
- The footer is a **bold blockquote** (`<blockquote><b>🪼 @PROXIV3</b></blockquote>`)
  as the final element of the message, nothing after it.
- Refuses pools older than 90 minutes — a stale pool is never posted.
- `GET /health` returns ok plus the last post's message id / timestamp.
- Needs the `TELEGRAM_TOKEN` secret and the KV binding `MERIDIAN_STORE`.

## meridian-sub — VIP subscription (Phase 5)

- `GET /sub/<secret>` serves the VIP pool from KV key `vip_sub` (base64 of the
  config URIs, one per line), with `profile-title: base64:` of
  `🪼 PROXIV3 VIP` and `profile-update-interval: 1`. Wrong secret → 404,
  empty pool → 503. Exactly **one** link — no per-user tokens.
- The secret path segment lives only in KV (`sub_secret`) and in the bot's
  /vip replies. It is never committed, logged or printed.

## meridian-bot — bot webhook (Phase 6)

- Webhook for the project's bot (@Pool_IVbot), guarded by a Telegram
  secret-token header checked against KV `webhook_secret`.
- `/start` — welcome text. `/vip` — the single VIP subscription link, only for
  admin ids compiled into the Worker (the two owner accounts) or ids in the
  KV list `vip_users`; everyone else gets an invite-only reply.
- `/help`. **Feedback v2 (2026-11-20):** /vip also sends the numbered
  VIP list (KV `vip_index`, written by the composer next to `vip_sub`)
  with a ❌ button per config and one ✅ "All worked" button; text
  `dead N` / `works N` works too. Reports are stored in the KV
  `feedback` object keyed by opaque pass-key hash ({works, dead,
  works_ts, dead_ts}); the composer quarantines dead-reported keys
  (both pools) until they re-verify, and weights works reports in
  ranking.
- Needs the `TELEGRAM_TOKEN` secret and the KV binding `MERIDIAN_STORE`.

## meridian-peak — own anchor (Phase 4) — CLOSED, parked by wolf's instruction

`worker/meridian-peak/index.js` is a minimal in-house VLESS+WS+TLS Worker
using `cloudflare:sockets`. On this account, **any** script whose code
references `cloudflare:sockets` (static import, dynamic import, or separate
module — all three bisected) returns HTTP 1101 on every route when deployed
through the Scripts API, while identical code without the reference works.
Final re-test (2026-11-20): the exact source uploaded as a throwaway probe
answered briefly, then returned HTTP 500 on every route, while a no-sockets
control Worker served normally — the platform block stands. The anchor is
in no pool and the system is fully live without it. Reopening needs a
dashboard/wrangler deploy or a Cloudflare platform change. KV keys
`anchor_uuid` / `node_path` stay reserved for it.

## Deploy (API token only — GitHub is NOT connected to Cloudflare)

1. Upload each script with the account API token (Scripts API, module format,
   KV binding `MERIDIAN_STORE` → the MERIDIAN_STORE namespace).
2. **Enable the workers.dev route** for each script
   (`POST /accounts/{id}/workers/scripts/{name}/subdomain {"enabled": true}`)
   — without this step the script exists but every route 404s (error 1042).
3. Set the cron schedule for meridian-pub via the schedules API
   (`33 * * * *`); set `TELEGRAM_TOKEN` secrets on meridian-pub and
   meridian-bot via the secrets API (value passed via stdin only, never
   written to a file).
4. Register the bot webhook to meridian-bot's `/webhook` with the KV
   `webhook_secret` as the Telegram secret token.
5. KV keys: `public_pool` (JSON), `vip_sub` (base64 text), `sub_secret`,
   `webhook_secret`, `vip_users`, `feedback`, `anchor_uuid`, `node_path`.

Gotcha found live: JavaScript has no `\U0001FABC` escape — emoji in Worker
strings must use `\u{1FABC}` (a literal `\U…` silently degrades to plain
text). All three Workers were fixed and re-verified after deploy.

The hourly loop is closed outside the Workers: the Actions `verify` workflow
runs hourly, and a composer job intersects the latest runs under the strict
tier rules (public: Gate-3 pass in 2 runs ≥ ~15 min apart meeting the public
floors; VIP: Gate-3 pass in 3 consecutive runs meeting the VIP floors),
rewrites the KV pools, and meridian-pub posts at :33.

Webhook safety note (unchanged from the original plan): the publisher never
calls `setWebhook` with the old MTProto bot token; the old bot keeps its own
webhook on the old system. The new bot uses its own token and its own webhook
on meridian-bot, so the two bots cannot conflict.
