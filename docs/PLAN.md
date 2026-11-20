# PROXIV3 — V2Ray Pool — Phased Plan (Rev. 1, 2026-11-20, Agent: Rick)

Scope locked by wolf (2026-11-20):
- NEW Cloudflare account + NEW GitHub repo. Old Proxiv3 repo/worker/bot untouched.
- SAME Telegram channel: @Proxiv3. Public language: English (standing rule).
- Channel posts: every 1 hour.
- ONE single VIP subscription link (secret path, given only via the new bot). No per-user tokens, no mass production.
- Hard rule: only configs proven working end-to-end are published. No filler.

## Naming & risk rules (wolf, 2026-11-20 — the new CF account must NOT hit the problems the old proxy accounts hit)
- Repo renamed to the codename `MeridianFeed` (ILIV007/MeridianFeed) on 2026-11-20 at wolf's instruction; `Pool-v2ray` is retired.
- On the Cloudflare side, NO sensitive words in ANY identifier: account name, workers.dev subdomain, Worker names, KV/D1 names, routes, secret names. Banned words: proxy, v2ray, vpn, tunnel, bypass, free, pool, proxiv3, iran, filter and similar.
- CF codenames: publisher Worker `meridian-pub`, sub Worker `meridian-sub`, anchor Worker (Phase 4) under a separate bland name, KV `MERIDIAN_STORE`. Branding (PROXIV3 etc.) lives only in Telegram post text, never in infrastructure names.
- Risk posture: the CF account only serves light content (hourly post cron + static sub reads). No mass scraping from CF, no open relay; the sub path stays secret; the Phase-4 anchor stays low-volume. Heavy work (collecting/verifying) stays on GitHub Actions.
- Deployment rule (wolf, 2026-11-20): the GitHub account is NOT connected to Cloudflare — no Cloudflare GitHub App, no Workers Builds git integration, no OAuth link. Exactly like Lyra: Workers are deployed via API token only (wrangler/API from Rick's side), and the GitHub Actions pipeline talks to Cloudflare only through the CF API (e.g. KV writes with an API token held as an Actions secret). GitHub and Cloudflare stay fully decoupled.

## Phase 0 — Decisions & access (needs wolf)
- Repo created 2026-11-20: ILIV007/Pool-v2ray (public, empty at creation; scaffold in progress).
- Wolf is creating the new Cloudflare account himself (2026-11-20) and will hand it over together with the new Telegram bot token; Rick advances all phases that do not need them in the meantime.
- New bot created by wolf in BotFather and added as admin to @Proxiv3.
- Secrets only via Secure Vault / CF secrets / GH Actions secrets. Never in repo or chat.
- **Status 2026-11-20: COMPLETE.** New Cloudflare account handed over and in use (Workers + KV live); bot @Pool_IVbot created, profile completed, verified admin of @Proxiv3; bot admins with VIP access: the owner's main account + @BLUE_WOLF_03. Repo renamed Pool-v2ray → MeridianFeed (see the naming note at the end).

## Phase 1 — Source checkup (before any code) — DONE 2026-11-20
- 11 sources sampled, report at phase1-source-checkup.md (also in repo docs/). Keep: ermaozi/get_subscribe, peasoft/NoMoreWalls, mahdibland/V2RayAggregator (Eternity). Watch: EternityAir, Pawdroid/Free-servers, free-nodes/v2rayfree, mehdirzfx/v2ray-sub. Drop: AutoMergePublicNodes (redundant + 17.3% malformed), barry-far (repo blocked), freefq/free (stale 2024), NiREvil wg feed (WireGuard only, out of scope).
- Findings: NoMoreWalls / AutoMerge / ermaozi are largely one pool in three hats → cross-source dedup mandatory; `127.0.0.53` appears as a config host → Gate 1 must hard-reject placeholder hosts. Estimated intake after cross-dedup: ~700–900 unique parse-valid configs per cycle (alive ratio is Phase 3's job).
- Build a source registry (public subs / GitHub lists / channels), each source sampled once.
- Measure per source: parse rate, dead rate, duplicate rate. Drop junk sources at this gate.
- Output: checkup report with real numbers; only sources with a viable alive-ratio continue.

## Phase 1b — Source diversification (added by wolf on 2026-11-20: sources must be diverse, from different facets)
- Phase 1's keeps are largely ONE upstream pool in three hats — not diverse enough. Scout additional facets: Telegram public channels that post configs, aggregators from other scenes/languages (CN/RU/FA), direct community/airport free lists, and index sites — each sampled with the same Phase 1 metrics before joining the registry.
- Diversity is enforced again at pool composition (Phase 3/5): no single source > ~30% of a published batch, caps per country, per protocol and per server IP/ASN, and a deliberate mix of protocols (VLESS/REALITY, Trojan, SS, Hysteria2, VMess) and geos (near: TR/DE/NL/FI + spread). A batch that fails the mix check is rebalanced, not padded from one source.
- Phase 1b DONE 2026-11-20 (report: phase1b-diverse-sources.md): 12 new candidates across Telegram / CN / RU / FA facets. Keeps: PulseProxy (RU whitelist — 772/772 valid, 710 hosts, only 0.6% overlap with the Phase-1 family = a genuinely independent second backbone), @outline_vpn (FA), @Surfboardv2ray (FA — prefer its pinned sub links in Phase 2), MohammadBahemmat/V2ray-Collector (broad, but 39.5% family overlap, dedup-critical). Watch ×5, Drop ×3. Registry now spans two near-disjoint large pools + operator-direct FA Telegram channels.

## Phase 2 — Collector + parser + dedup — DONE 2026-11-20
- Built and committed: pipeline/sources.json (7 keep sources), pipeline/collector.py (stdlib-only, Gate-1 rejects, cross-source dedup on protocol+server+port+credential-hash, stats-only output — credentials never written out), pipeline/test_collector.py (18/18 tests pass).
- First live run: 2,581 fetched → 2,554 valid → 733 dupes → **1,821 unique configs / 1,681 hosts** (mix: vless 1,376 · ss 263 · trojan 77 · vmess 56 · hysteria2 48 · tuic 1). NoMoreWalls contributed only 53 unique-new (mostly ermaozi dupes — the one-pool finding, measured). These 1,821 are Phase 3's input; parse-valid ≠ alive.
- Protocols in scope: VLESS, VMess, Trojan, Shadowsocks, Hysteria2, TUIC.
- Strict parse + normalise; dedup key = protocol + server + port + credential hash (same server under 50 remarks = 1 entry).

## Phase 3 — Verifier (the core — config checkup)
Three gates; a config must pass ALL of them:
- Gate 1 — Structure: valid URI/JSON, sane TLS/SNI/transport fields.
- Gate 2 — Network: DNS resolves, TCP/TLS handshake inside timeout (8s). Kills most junk cheaply.
- Gate 3 — Real tunnel (sing-box on GitHub Actions): start a client from the config, then through the tunnel: (a) generate_204 succeeds, (b) egress IP differs from the runner IP, (c) latency measured, (d) small download speed test.
Controls in EVERY run (run is invalid and publishes NOTHING if controls fail):
- Positive control: our own Phase-4 Cloudflare config must pass Gate 3.
- Negative control: a known-dead config must fail.
Tiers (STRICT — upgraded by wolf on 2026-11-20: "the stricter the better; every config we use must be healthy"):
- First publish (any tier): Gate 3 passed TWICE in two separate runs at least ~15 minutes apart. A single lucky pass publishes nothing.
- Public pool: the double-pass above + latency gate (median of 3 tunnel probes ≤ 800 ms, any probe timeout = fail) + minimum download speed on a small test file.
- VIP pool: Gate 3 passed in 3 consecutive cycles + stricter latency/speed floors + sorted best-first, capped (~30–50), mixed countries/protocols, max 2 configs per server IP (forces diversity).
- Gate 1 hard-rejects: loopback/private/reserved hosts (incl. the `127.0.0.53` placeholder found in Phase 1), expired or nonsense TLS/SNI, credentials shared by an implausible number of distinct hosts.
- Gate 3 must confirm BOTH a generate_204 success AND a real HTTPS fetch whose egress IP differs from the runner and whose geo matches the config's claimed country.
- Expiry/quarantine: re-verified every hour, and the exact post batch is re-verified right before posting (nothing older than 60 minutes is posted). ONE failed re-check = quarantined (not published); 2 consecutive failures = removed. VIP drops out on the first failure.
- Never lower the bar to fill a post: a thin hour posts fewer configs, an empty hour posts only the Phase-4 anchors or nothing. Quality over quantity, always.
Known limit: runners are outside Iran — a pass proves the config truly works, not that an Iranian ISP won't block its IP. Mitigation: prefer REALITY + CDN-fronted configs, nearby geos, and bot user feedback (Phase 6) to drop Iran-dead entries fast.

## Phase 3 progress (2026-11-20)
- Verifier core BUILT and committed: pipeline/verifier.py (Gate 2 DNS+TCP; Gate 3 sing-box tunnel per config — 3-probe median latency, generate_204, egress-IP/country confirmation, speed sample), controls run first in every run (positive loopback pair passed 0.9 ms; negative dead config correctly failed), stats-only output. .github/workflows/verify.yml added (hourly + dispatch, pinned sing-box v1.11.15, publishes nothing). Rebrand helper + tests in place.
- Proof run in this sandbox: Gate 3 passed 0/40 sampled — an ENVIRONMENT artifact (the sandbox blocks direct TLS egress, verified independently of sing-box; the sing-box outbound builder passed 60/60 `sing-box check`). Real Gate-3 pass rates come from the Actions workflow run, still to be observed.
- First real GitHub Actions run (workflow `verify`, run 44623695513, conclusion: success; stats artifact verify-stats-44623695513): input fetched 2,581 → Gate 1 valid 2,554 → 1,821 unique → sampled 200. Controls ok: true — positive control pass (latency_ms 1.1, local loopback harness proof), negative control correctly failed (reason: probe204). Gate 2: tested 200, passed 173, failed 27 (fail_reasons: tcp 25, dns 2). Gate 3: tested 173, passed 106, failed 67 (fail_reasons: probe204 66, trace 1); passed_by_protocol: ss 52, vless 38, vmess 10, hysteria2 4, trojan 2; egress_countries across 19 countries (US 44, NL 20, DE 8, SG 7, JP 5, …); latency_ms of passes: n 106, median 359.7, p90 811.9, min 66.5, max 3589.5; speed_mbps: n 106, median 2.42, p90 7.66, min 0.27, max 24.95. public_criteria_met_single_run: 93 — the count that passed full strict Gate 3 in this single run AND met the single-run public latency/speed criteria; strict tier assignment still requires the repeat passes (public: 2nd run ≥15 min later; VIP: 3 consecutive cycles), so this run published nothing. Future runs append the stats JSON to the workflow step summary, so numbers are API-readable without the artifact zip.

## Phase 4 — Own anchor configs (Cloudflare)
- Minimal own VLESS+WS+TLS Worker on the new CF account (written in-house, no upstream project dependency).
- These are the guaranteed-alive anchors: public posts rotate them, VIP sub always includes them.
- Watch free-plan limits + abuse risk; anchors are a backbone, not the whole pool.
- **Status 2026-11-20: CLOSED — PARKED by wolf's instruction.** The anchor Worker (`worker/meridian-peak/index.js`) is written, but on this account any script whose code references `cloudflare:sockets` returns HTTP 1101 on every route when deployed via the Scripts API (bisected: static import, dynamic import and separate-module variants all fail; identical code without the reference works). A genuine final re-test on 2026-11-20 uploaded the exact source as a throwaway probe Worker: it answered 200/404 only briefly, then returned HTTP 500 on every route, while a no-sockets control Worker on the same account served normally and meridian-pub stayed healthy — the platform block stands, and there is no sockets-free way to egress arbitrary TCP from a Worker. The anchor is NOT deployed, is in NO pool, and the system is fully live without it. Reopening needs a dashboard/wrangler deploy or a Cloudflare platform change. KV keys `anchor_uuid` / `node_path` stay reserved.

## Phase 5 — Publisher (new CF Worker)
- Rebranding rule (wolf, 2026-11-20): every published config is RENAMED to the channel's own name before posting — the remark is display-only (URI `#fragment`, vmess `ps`) and never affects the connection; dedup/verifier keys ignore remarks entirely. Format: `🪼 PROXIV3 · <flag> <country> · <PROTOCOL> · Verified` — the channel's own 🪼 emoji up front (its signature: channel title "🪼PROXIV3", post footer "🪼 @PROXIV3"), the word Verified instead of any real latency figure (wolf, 2026-11-20: no real latency on the names, "Verified" is enough). VIP sub profile-title: `🪼 PROXIV3 VIP`. Renaming happens after verification, at publish time.
- Cron hourly: read verified pool from KV, post one batch to @Proxiv3 (protocol, country, latency, tested-at, config in a copyable block).
- VIP sub endpoint: fixed link /sub/<secret> serving the current VIP pool (base64, standard headers) — content refreshed hourly, link never changes. Wrong secret = 404.
- Cron-only for the old bot token if reused for posting; the publisher never calls setWebhook (protects the old MTProto bot).
- **Status 2026-11-20: DONE and live.** `meridian-pub` (cron `33 * * * *` UTC, Rich Messages, refuses pools older than 90 min) and `meridian-sub` (`/sub/<secret>` from KV, wrong secret 404, `profile-title` 🪼 PROXIV3 VIP) are deployed on the new account with routes enabled and health/endpoint checks verified live. KV `MERIDIAN_STORE` holds `public_pool` + `vip_sub`, refreshed hourly by the composer from the strict tier intersections. First channel post: https://t.me/Proxiv3/2621 (7 double-pass configs). Tier clocks: run 44623695513 predates verifier v1.1.0's per-pass keys, so intersections start with the v1.1.0 runs 44627118024 / 44628683507 / 44630781473 / 44632829174 / 44634869948 (Gate 3: 112 / 113 / 112 / 111 / 114 passes) — public double-pass intersection 103 keys → 7 published after URI recovery + quotas; VIP triple-pass intersection 45 keys → 6 published.

## Phase 6 — New VIP bot
- Own webhook on the new Worker (new bot = no conflict with @Prox_IVbot).
- Gives the single VIP sub link to VIP users; collects working/dead feedback per config to feed Phase 3 scoring.
- **Status 2026-11-20: DONE and live.** `meridian-bot` serves the @Pool_IVbot webhook (secret-token header verified against KV): /start, /vip (admins + KV `vip_users` only), /help, works/dead feedback to KV. The VIP link was delivered by the bot to both admin accounts (bot messages 5 and 6 in the respective chats). Webhook registered with zero pending updates and no delivery errors.
- **Webhook proof CLOSED (2026-11-20):** wolf personally tested /start and /vip and confirmed both work, and the VIP subscription link works. The "first real admin test" open item is closed by the owner's own test.
- **Feedback v2 (2026-11-20):** /vip also sends a numbered list of the current VIP configs (KV `vip_index`, written by the composer next to `vip_sub`) with a ❌ button per config and one ✅ "All worked" button; "dead N" / "works N" text replies work too. Reports land in the KV `feedback` object keyed by opaque pass-key hash ({works, dead, works_ts, dead_ts}). The composer consumes it hourly: a dead report quarantines the key in BOTH pools until a verify run created after the report passes it again; works reports add ranking weight.

## Phase 7 — Live test, tidy, ship
- Import tests: v2rayNG, Happ, Streisand — public post configs + VIP sub, on real connections.
- Full checkup/debug pass, then ship as v1.0.0 via branch + PR + merge, tagged `Agent: Rick`, changelog in repo.
- **Status 2026-11-20: live-verified server-side** — KV read-backs byte-identical, sub endpoint fetched with a real HTTP client (200 + correct subscription headers + decodable body), first Rich post confirmed in the channel, bot deliveries confirmed by API message ids, publisher cron armed. On-device client imports (v2rayNG/Happ/Streisand) remain a wolf-side spot check; every published config passed a real sing-box tunnel test at least twice (VIP: three times), which is the same connection path those clients use.

Decided (corrected by wolf on 2026-11-20, superseding the earlier `Pool-v2` reading): repo name was `Pool-v2ray`; renamed the same night to the codename `MeridianFeed` under wolf's naming/risk rule (see Naming & risk rules above). Nothing was created under the old name.
Open items for wolf: new CF account hand-off, new bot token (via Secure Vault), who counts as VIP.

## MORNING CHECKUP — 2026-11-20 (Agent: Rick)

- **Incident:** composer dispatch-loop stalled the pool after 03:28Z; the 05:33Z post was correctly skipped by the staleness guard. Fixed the same morning: the composer now waits for the dispatched run and composes in the same tick (see CHANGELOG). The 06:33Z post fired (message 2672); the hourly loop is healthy since.
- **Known flake:** the verify workflow's `17 * * * *` schedule fired only once in 8 hours — the composer no longer depends on it.
- **Still open:** ~~Phase 4 anchor (1101, wolf's call), first real admin /start over the webhook as final delivery proof, device import spot check.~~ — all three superseded by the CLOSE-OUT below (anchor parked by wolf's instruction after a final re-test; webhook proof closed by wolf's own test; the device check became wolf's field test, whose results drove the Iran-reachability regime).

## CLOSE-OUT — 2026-11-20 (Agent: Rick)

Every previously open item is closed by this section.

### Post format (wolf's rules, 2026-11-20)
- A channel post carries **at most 5 configs** — the best-ranked eligible ones, never padded. Enforced twice: the composer caps the KV public pool at 5, and `meridian-pub` slices to `MAX_POST_CONFIGS = 5` at render. Dry-run verified: pools of 5 and of 12 both render exactly 5 config blocks.
- The Rich post's final element is the footer as a **bold blockquote** — `<blockquote><b>🪼 @PROXIV3</b></blockquote>` — nothing after it. Dry-run verified (single blockquote, at the very end). Rich messages cannot be edited, so no test post was sent; the next scheduled :33 post is the live proof.

### Iran-reachability regime (from wolf's field test, 2026-11-20)
- **Field data:** wolf tested the VIP set from Iran — of ~44 served configs only 4 worked, only on mobile data, only on port 443; on fixed-line ADSL nothing connected; all were US picks.
- **Root cause (documented):** Gate 3 verifies from GitHub US runners. (a) The latency floors bias selection to US servers; (b) nothing models Iranian ISP filtering, so direct-IP foreign servers that Iranian fixed-line (TCI) blocks wholesale pass the gates and die for the user. "Verified" meant *alive-from-America*, not *reachable-from-Iran*. The pre-fix VIP set measured: 36 configs, only 19 on port 443, **zero** Cloudflare-fronted WS+TLS, 18 direct-IP, 13 REALITY, 17 Shadowsocks (mostly port 19999).
- **New admission + ranking (both tiers identical; the only difference is pass-count confidence — public double-pass, VIP triple-pass + VIP floors):**
  - Fronting class is the top ranking factor: CF-anycast-IP WS+TLS → domain WS+TLS (CDN-fronted class) → REALITY with SNI → REALITY without → bare direct last.
  - US-latency bias removed: rank by fronting, source stability, pass consistency across runs, field works weight, speed; latency is only the final tiebreak inside a class.
  - Country quotas removed entirely (quality, not country); per-source / per-protocol / per-host ceilings stay.
  - **Port policy (wolf's correction, superseding a same-day 443-only rule):** NO port lock. Port 443 is the *anchor share* of each pool (VIP ~70%, channel 60%), the remainder spreads over alternate ports — for fronted configs preferring the Cloudflare HTTPS alt-port ladder (2053, 2096, 8443, 2083, 2087). The works/dead feedback loop is the tuner: what users report dead is demoted/quarantined by data, not by a hard lock.
  - **Tier differentiation:** VIP selects FIRST from the eligible set (proven core); the channel batch is composed from what remains — a config never appears in both the current VIP set and a channel post. The channel is the proving ground (double-pass, may include promising newer configs); VIP is the proven core.
  - Feedback loop wired end-to-end (bot buttons → KV `feedback` → composer quarantine + works weight, both pools).
- **First recompose under the regime:** VIP 36 served (port mix 443×23, 19999×12, 23576×1; fronting 4 CF-IP WS+TLS, 13 REALITY-SNI, 19 other — the CF-fronted class went from 0 to present and top-ranked; alt-port share is the legacy SS set, ranked last and subject to feedback demotion). Channel 5 served (443×3 anchor, 445×1, 23576×1; all 5 REALITY-SNI — the best remaining after VIP's first pick). Public starvation (a cycle serving <5) is tracked per compose in the composer's log; this cycle: none (62 qualifying after disjoint removal).

### BPB lessons (wolf's own BPB subscription, analysed 2026-11-20)
BPB's 24 configs are ONE Cloudflare Pages origin presented as a variant matrix: {origin domain, CF IPv4 ×2, clean-IP front (www.speedtest.net as address)} × ports {443, 2053, 2096} × {VLESS, Trojan} — all WS+TLS, fp=chrome, alpn http/1.1, early-data path ed=2560, SNI = the origin domain with randomised letter case. Adopted into selection: redundancy by presentation-variant; CDN fronting as the Iran-survival trait; the CF HTTPS port ladder as fallback thinking (while the mix stays feedback-tuned). NOT adopted: self-hosted endpoints — the pool still only *selects collected configs* exhibiting these traits; it operates no endpoints of its own.

### Snapshot pinning (Phase B) + load spreading — LIVE
- **Pinning:** each verify run writes a PRIVATE per-run key→URI map for exactly its sampled configs, uploaded as a separate Actions artifact (`verify-uri-map-<run_id>`, 7-day retention, never in the repo/logs/chat). Composer recovery order: pin maps of the contributing runs → live lists → persistent URI cache. Eligible-key recovery becomes ~100% by construction, independent of list churn (the churn audit measured the pre-pinning lottery at ~40% bad-moment / ~81–89% good-moment).
- **Load spreading (measured before → after):** stages were already staggered (:17 verify, :25 compose, :33 publish) but each stage burst. Now: conditional requests (ETag / If-Modified-Since) with per-source snapshot caches on both sides (Actions cache for the verifier, local cache for the composer) — unchanged lists revalidate as 304s instead of full downloads (before: 2 full downloads per source per hour); fetches are sequential with 0.4–1.5 s jitter and randomised source order (before: fixed order, no pacing); Gate-3 concurrency stays capped at 4; Gate-3 sample widened 200 → 300 (job 2.3 → 4.2 min, far inside the 55-min timeout). KV per cycle: composer reads 3 (pools + feedback), writes only on change (public_pool carries a fresh timestamp by design; vip_sub + vip_index are sha-gated).
- **Registry volatility flags (Phase A):** `bahemmat-collector` and `surfboardv2ray` are `volatile` (demoted to discovery class — bahemmat NOT dropped); ermaozi, NoMoreWalls, mahdibland-eternity, pulseproxy, outline_vpn are `stable`. Composition is stability-weighted and volatile sources are batch-capped (channel ≤1, VIP ≤6).
- **Decision (recorded):** the audit's optional sample-window rotation was NOT adopted — tier intersections depend on sample stability across runs, and the 200→300 widening already deepened coverage by 50%.

### Phase C — source firming (harness live; adoptions measured, none guessed)
- Harness: `pipeline/survival.py` (exact-key survival from GitHub commit history or local timestamped snapshots; adoption bar ≥85% @24h measured).
- Baselines by the harness: Eternity 0.80 @24h over 96 snapshots/48 days (incumbent keep; the audit's binned estimate was 0.88 — the weekly job tracks the harness series from here).
- **EternityAir (mahdibland sibling): REJECTED** — survival 0.018 @6h, 0.0 @24h (48 snapshots): an airport-merge firehose, not an Eternity-class file.
- **PulseProxy githubmirror/1.txt: NOT ADOPTED** — 0 parse-valid keys in current snapshots (shard appears empty/retired); the registry keeps 30.txt only.
- **Observing (windows complete 2026-11-21 ~07:41Z):** FlareFeed fastest.txt (endpoint-class; 200, small), KvRuVPN (GitVerse 429 at snapshot time — rate-limit is itself a finding), Surfboard preview snapshots (its pinned sub endpoint could not be extracted from the public preview — no external links present; conversion stays pending the endpoint itself). Pawdroid: hand-curated, garnish-class; observation via the weekly job's watchlist when its feed is re-confirmed.
- No candidate joins the keep set on reputation — only on measured survival.

### Phase D — weekly survival audit (LIVE)
- A weekly job (Mondays ~06:25 UTC, local cron `meridian-survival-weekly`) recomputes per-source survival with the harness, appends the dated result to `docs/survival-log.md` via the usual branch + PR flow, and flags any keep source below the bar. Quiet by default: it writes records, posts nothing.

### :17 schedule flakiness — CLOSED / mitigated
- Evidence: of the last 12 verify runs before close-out, exactly ONE came from the `schedule` event; the rest were composer `workflow_dispatch` — and every run succeeded hourly. The composer's dispatch fallback (dispatch + wait + compose in the same tick when the newest run is >50 min old) is proven working in production, including three consecutive dispatch-only ticks on 2026-11-20 that each recovered on the next tick. The system no longer depends on GitHub's schedule reliability.

### Architect autonomy (wolf, 2026-11-20)
Wolf granted Rick architect-level autonomy for MeridianFeed: within the locked invariants (verification strictness, CF naming/risk rule, CF-light/Actions-heavy split, hourly :33 Rich post of ≤5 with quote footer, hourly sub refresh, VIP cap 48 quality-only, English public text, secrets hygiene, pinning privacy, ≥85% @24h adoption bar), design choices are Rick's to make and record — as done throughout this close-out.

### Field iteration 2 — survival classes v2, variant multiplication, country ceiling (2026-11-20)
Wolf's second field test of the recomposed VIP 44: **6 worked from Iran**, set again 91% US. Audit of the 6 (all confirmed in the served sub by pass-key): 3× one CF-fronted VMess WS+TLS service via three anycast IPs (443) + 3× plain SS on direct IPs (8443/443/19999). Dead 38 included 13 REALITY (0 survived), 3 Hysteria2 (0), 20 plain SS (3 — a mixed class; per-server IP blocking, so feedback discriminates within it) and 1 CF-fronted VMess of a different origin.
- **Ranking v2:** survival classes `cf-ip-ws-tls → domain-ws-tls → plain-ss → reality-sni → reality → other` (the field-measured survival order), plus a field-verified tier (works ≥ 3, seeded for the 6 proven keys) that leads ranking and selection regardless of class/port. Gates/floors/pinning unchanged.
- **Variant multiplication:** `collector.expand_cf_variants` presents CF-fronted WS+TLS configs via up to 4 curated anycast IPs (address-only swap); variants are ordinary candidates, independently gated and pin-mapped. Per-service caps: VIP 4, channel 2.
- **Anti-monoculture ceiling:** ≤50% of any served set per country, both pools, enforced constructively (non-majority supply first, majority admitted up to parity) + logged trim net. Eligible VIP supply today is US 41 / non-US 4, so the first v2 VIP is **8** (US 4 = 50%; profile share 0.625; 5/6 proven keys in) and the channel **4** (NL 2, RU 1, SE 1). Supply growth (variant passes, Phase C sources) is what raises these numbers — never weaker admission.

## Amendment 2026-11-20 (later) — post time :33 Tehran, VIP floor of 8, field feedback #5 (Agent: Rick)

- **Post time:** the locked "hourly :33" rule means :33 TEHRAN. `meridian-pub`'s trigger is now `3 * * * *` UTC (= :33 Tehran; the original `33 * * * *` UTC landed posts at :03 Tehran). The composer cron `meridian-compose-hourly` was phase-shifted to :55 UTC (:25 Tehran), keeping the 8-minute compose→post gap; exactly one composer job exists. The pub Worker's 90-minute staleness guard is unchanged and still fits: the pool is minutes old at post time and the guard still absorbs one missed cycle.
- **VIP composition — floor of 8 (wolf's directive, amending the VIP composition rule; verification gates unchanged):** Tier 1 = strict triple-pass VIP-eligible, served first, ranked v2 as before. Tier 2 (only if Tier 1 < 8) = persisted members of the PREVIOUS served VIP set that are (a) not quarantined, (b) carry no dead feedback, (c) pass the Hysteria2 rule (excluded unless field-verified), and (d) hold a Gate-3 pass within the last 3 verify runs. Tier 3 (still < 8) = double-pass keys that met the VIP floors (≤500 ms / ≥2.5 Mbps) in their qualifying runs, ranked v2, same exclusions. The 50% anti-monoculture country ceiling applies across the whole filled set. Fill URIs come from snapshot pinning exactly as tested (served = tested for all tiers). If total supply after all tiers is still < 8, the composer serves what honestly exists and logs the shortfall (`vip_floor_shortfall`; tier composition reported as `vip_tiers: {t1, t2, t3}`) — quarantined keys are never resurrected to fill.
- **Field feedback #5 (wolf, ADSL, 2026-11-20):** CA SS 149.22.95.183:443 works on ADSL at ~2000 ms (degraded vs 392 ms in test #3, alive — works report recorded in KV feedback, field-verified status kept). VMess via 188.114.99.137:443 failed on ADSL — recorded as an ADSL-failure observation (`obs` entry on its feedback record; counters untouched), NOT quarantined (single-network rule). Variant lesson: within the proven guanwang service, 172.64.145.x is the ADSL-strong variant (326 ms, test #3) and 188.114.99.x the ADSL-weak one — variant composition inside VIP matters per network; carry more than one variant of a proven service when eligible.
