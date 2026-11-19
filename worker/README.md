# Worker — publisher, VIP subscription & bot (Phases 5–6)

A single Cloudflare Worker on the project's new Cloudflare account. It publishes what the pipeline has already proven — it never verifies configs itself and never posts untested entries.

## Phase 5 — Hourly publisher + VIP subscription

- **Cron, hourly:** read the verified pool from KV and post one batch to [@Proxiv3](https://t.me/Proxiv3) — protocol, country, latency, tested-at time, and the config in a copyable block.
- **VIP subscription endpoint:** `GET /sub/<secret>` serves the current VIP pool from KV (base64, standard subscription headers). The link never changes; its contents are refreshed hourly with only the best-tier configs. A wrong secret returns 404. There is exactly **one** VIP link — no per-user tokens.

## Phase 6 — New VIP bot

- The project's **new** Telegram bot lives here and gives the single VIP subscription link to VIP users.
- It also collects working / dead feedback per config, which feeds the verifier's scoring in the pipeline.

## Webhook safety note

The publisher must **never** call `setWebhook` with the old MTProto bot token. The old bot (@Prox_IVbot) keeps its own webhook on the old system; this Worker is Cron-only for any posting done with that token. The new VIP bot uses its own token and its own webhook on this Worker, so the two bots cannot conflict.
