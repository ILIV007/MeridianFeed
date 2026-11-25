# Composer — hourly pool composition on GitHub Actions

`compose.py` is the strict MeridianFeed composer (public pool + VIP
set from intersected verify runs). `run_compose.py` is the GitHub
Actions runner that feeds it verify artifacts + KV snapshots and
writes KV in live mode only. See
[docs/composer-independence.md](../../docs/composer-independence.md)
for modes, state persistence, secret setup, and the cutover
checklist.

Tests: `python3 pipeline/composer/test_compose.py`
