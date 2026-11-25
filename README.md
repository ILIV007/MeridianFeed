# MeridianFeed

**Verified V2Ray configs for [@PROXIV3](https://t.me/Proxiv3).**

MeridianFeed is the V2Ray complement to the main PROXIV3 MTProto bot/system in [ILIV007/Proxiv3](https://github.com/ILIV007/Proxiv3). Proxiv3 handles MTProto proxy distribution; MeridianFeed handles the V2Ray side for the same channel.

- Telegram channel: https://t.me/Proxiv3
- Main PROXIV3 project: https://github.com/ILIV007/Proxiv3

## What it does

- Collects V2Ray configs from public pools only.
- Verifies candidates end to end before anything is published.
- Publishes a fresh verified batch to @PROXIV3 every hour.
- Keeps the public feed quality-gated: if verification cannot prove a config works, it is not published.

## How it works

1. GitHub Actions runs the collection and verification pipeline.
2. The verifier tests configs through a real client path and measures whether traffic actually passes.
3. Passing configs are composed into the public pool.
4. Cloudflare Workers publish the hourly channel post and serve the generated pool data.
5. Failed or unproven configs are dropped; the system does not fill gaps with untested entries.

## Verification standard

- End-to-end proof, not just parsing or TCP reachability.
- Control checks in the verification flow; if controls fail, publishing is blocked.
- Public pools only; MeridianFeed does not run its own proxy endpoints.

## Layout

```text
.github/workflows/  Scheduled verification workflows
pipeline/           Collection, parsing, governance, and verification code
worker/             Cloudflare Workers for publishing and serving
data/               Reference data used by the pipeline
docs/               Project plan, reports, and operating notes
```

## Status

Live and self-running. The hourly loop collects, verifies, composes, and publishes without manual posting. See [CHANGELOG.md](CHANGELOG.md) for the project record and [docs/PLAN.md](docs/PLAN.md) for the longer plan.

## Related project

- Main PROXIV3 MTProto system: https://github.com/ILIV007/Proxiv3
- Telegram channel: https://t.me/Proxiv3
