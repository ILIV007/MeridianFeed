// meridian-bot — the single bot Worker for @Pool_IVbot (MeridianFeed).
// The whole V2Ray flow lives in this one bot: /start menu, the VIP
// section (/vip hands the single subscription link to admins/VIPs
// only), /help, and per-config field feedback.
//
// R6.2 (2026-11-24): /check — a token-gated browser checker page.
// Gate-IR's live numbers are ~90-100% neutral (check-host is mute
// from the runner egress), so the API stage gives almost no signal;
// this page probes the current VIP WS/TLS endpoints from the
// visitor's own browser/network in Iran (WebSocket open timing) and
// posts the verdicts back into KV `checker_verdicts`. Scope honesty:
// TCP/TLS liveness only, NOT a tunnel proof — and the browser can
// only probe WS/TLS endpoints (no raw TCP), via the SNI domain, not
// the exact edge IP. Verdicts are a ranking signal only for now —
// the composer does NOT consume them yet (follow-up once the signal
// proves reliable); the ❌/✅ feedback store stays the only
// quarantine path. Links are issued per VIP user, HMAC-signed with
// the webhook_secret, 24 h expiry.
// R5.4 (2026-11-24): /help recommends Network Checker
// (github.com/mirarr-app/network-checker) as the self-diagnostic
// companion — finds clean IPs from the user's own ISP — with both
// recorded caveats (desktop Xray download has no checksum check;
// public-IP lookup uses plain HTTP). Bot-internal surfaces only:
// the channel never promotes the bot (public-comms rule).
// Feedback v2 (2026-11-20, after wolf's Iran field test): /vip also
// sends a numbered list of the current VIP configs (from the KV
// vip_index the composer writes next to vip_sub) with a ❌ button per
// config and one "✅ All worked" button. Reports land in the KV
// `feedback` object keyed by the config's opaque pass-key hash:
// {key: {works, dead, works_ts, dead_ts}}. The composer reads it
// hourly: a dead report quarantines the key until it passes a verify
// run again; works reports add ranking weight. Text "dead N" /
// "works N" (N = list number) works too.
// Webhook requests are verified against the secret stored in KV
// (webhook_secret). Replies use the TELEGRAM_TOKEN Worker secret.
const SUB_BASE = "https://meridian-sub.ilipoolv2r.workers.dev/sub/";
// Mirror route (meridian-sub2): same KV, same secret path — the
// subscription stays reachable if the primary route is blocked.
const SUB2_BASE = "https://meridian-sub2.ilipoolv2r.workers.dev/sub/";
// Browser checker page (R6.2): the bot's own public route.
const CHECK_BASE = "https://meridian-bot.ilipoolv2r.workers.dev/check";
const CHECK_TOKEN_TTL_S = 24 * 3600;
const CHECK_TIMEOUT_MS = 10000;

async function tg(env, method, body) {
  const r = await fetch("https://api.telegram.org/bot" + env.TELEGRAM_TOKEN + "/" + method,
    { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  return r.json().catch(() => ({}));
}

function isVip(env, kvVip, uid) {
  const admins = (env.ADMIN_IDS || "").split(",").map(s => s.trim()).filter(Boolean);
  return admins.includes(uid) || (kvVip || []).map(String).includes(uid);
}

async function loadIndex(env) {
  try { return JSON.parse(await env.MERIDIAN_STORE.get("vip_index") || "null"); }
  catch (e) { return null; }
}

async function recordFeedback(env, key, kind) {
  await recordFeedbackBatch(env, [key], kind);
}

async function recordFeedbackBatch(env, keys, kind) {
  // One read-modify-write for the whole batch ("All worked" used to
  // pay one KV read + write per config and could interleave).
  let fb = {};
  try { fb = JSON.parse(await env.MERIDIAN_STORE.get("feedback") || "{}"); } catch (e) {}
  if (typeof fb !== "object" || Array.isArray(fb)) fb = {};
  const now = Math.floor(Date.now() / 1000);
  for (const key of keys) {
    const e = fb[key] || { works: 0, dead: 0 };
    if (kind === "works") { e.works += 1; e.works_ts = now; }
    else { e.dead += 1; e.dead_ts = now; }
    fb[key] = e;
  }
  await env.MERIDIAN_STORE.put("feedback", JSON.stringify(fb));
}

// --- R6.2 browser checker (pure helpers, unit-tested) ------------

async function hmacHex(secret, msg) {
  const key = await crypto.subtle.importKey("raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key,
    new TextEncoder().encode(msg));
  return [...new Uint8Array(sig)].map(b => b.toString(16)
    .padStart(2, "0")).join("");
}

async function issueCheckToken(env, uid) {
  const secret = await env.MERIDIAN_STORE.get("webhook_secret");
  if (!secret) return null;
  const exp = Math.floor(Date.now() / 1000) + CHECK_TOKEN_TTL_S;
  const payload = uid + "." + exp;
  return payload + "." + await hmacHex(secret, payload);
}

async function verifyCheckToken(env, token) {
  const secret = await env.MERIDIAN_STORE.get("webhook_secret");
  if (!secret || typeof token !== "string") return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  const [uid, exp, sig] = parts;
  if (!/^\d+$/.test(uid) || !/^\d+$/.test(exp)) return null;
  if (Number(exp) < Math.floor(Date.now() / 1000)) return null;
  const want = await hmacHex(secret, uid + "." + exp);
  if (sig.length !== want.length) return null;
  let diff = 0;
  for (let i = 0; i < want.length; i++) {
    diff |= sig.charCodeAt(i) ^ want.charCodeAt(i);
  }
  return diff === 0 ? uid : null;
}

const IPV4_RE = /^\d+\.\d+\.\d+\.\d+$/;

function probeUrl(uri) {
  // The wss:// URL a browser can probe for this config, or null when
  // it cannot be probed from a browser: non-WS/TLS protocols need
  // raw TCP, and an IP-literal host would fail the browser's TLS
  // cert check (the cert belongs to the SNI domain, not the edge
  // IP) — those endpoints are listed as not checkable instead of
  // producing false negatives.
  try {
    if (uri.startsWith("vmess://")) {
      const raw = uri.slice(8).split("#")[0].split("?")[0];
      const j = JSON.parse(atob(raw));
      if (j.tls !== "tls" || (j.net || "tcp") !== "ws") return null;
      const host = j.host || j.add;
      if (!host || IPV4_RE.test(host)) return null;
      return "wss://" + host + ":" + j.port + (j.path || "/");
    }
    const u = new URL(uri);
    if (u.protocol !== "vless:" && u.protocol !== "trojan:") return null;
    if (u.searchParams.get("security") !== "tls") return null;
    if ((u.searchParams.get("type") || "tcp") !== "ws") return null;
    const host = u.searchParams.get("host") || u.hostname;
    if (!host || IPV4_RE.test(host)) return null;
    return "wss://" + host + ":" + (u.port || "443") +
      (u.searchParams.get("path") || "/");
  } catch (e) { return null; }
}

function mergeVerdicts(existing, results, now) {
  // results: [{key (64-hex), ok, ms}] — already validated by the
  // caller. Counts per opaque key; never touches the ❌/✅ feedback
  // store (this is a ranking signal only, not a quarantine path).
  const out = existing && typeof existing === "object" ? { ...existing } : {};
  for (const r of results) {
    const e = out[r.key] || { works: 0, dead: 0 };
    if (r.ok) e.works += 1; else e.dead += 1;
    e.last_ts = now;
    e.last_ok = r.ok;
    out[r.key] = e;
  }
  return out;
}

function escHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function buildCheckPage(probes, token) {
  // probes: [{n, key, remark, url|null}]. The probe list is built
  // server-side from the current VIP sub only — never from user
  // input — so the page can only probe what we already serve.
  const data = JSON.stringify({ probes, token }).replace(/</g, "\\u003c");
  const rows = probes.map(p =>
    "<li id=\"r" + p.n + "\">" + p.n + ". " + escHtml(p.remark) +
    (p.url ? " — <span>pending…</span>" : " — <span>not checkable from a browser</span>") +
    "</li>").join("");
  return "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">" +
    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">" +
    "<title>PROXIV3 — connection check</title></head><body>" +
    "<h3>\u{1FABC} PROXIV3 — check from your network</h3>" +
    "<p>This page tries each VIP config from <b>your</b> browser and network, " +
    "then sends the results back. It checks reachability only — not whether a full tunnel works.</p>" +
    "<ol>" + rows + "</ol><p id=\"done\"></p>" +
    "<script>const D=" + data + ";" +
    "const results=[];let left=D.probes.filter(p=>p.url).length;" +
    "function finish(){if(left>0)return;" +
    "document.getElementById('done').textContent='Sending results…';" +
    "fetch('/check',{method:'POST',headers:{'content-type':'application/json'}," +
    "body:JSON.stringify({token:D.token,results})}).then(r=>r.json()).then(d=>{" +
    "document.getElementById('done').textContent=d.ok?'Done — '+d.recorded+' results recorded. Thank you!':'Could not send results.';}).catch(()=>{" +
    "document.getElementById('done').textContent='Could not send results.';});}" +
    "D.probes.forEach(p=>{if(!p.url)return;const t0=Date.now();let done=false;" +
    "const to=setTimeout(()=>{if(done)return;done=true;" +
    "document.querySelector('#r'+p.n+' span').textContent='timeout ('+" + CHECK_TIMEOUT_MS + " ms)';" +
    "results.push({key:p.key,ok:false,ms:" + CHECK_TIMEOUT_MS + "});left--;finish();}," + CHECK_TIMEOUT_MS + ");" +
    "try{const ws=new WebSocket(p.url);" +
    "ws.onopen=()=>{if(done)return;done=true;clearTimeout(to);" +
    "const ms=Date.now()-t0;" +
    "document.querySelector('#r'+p.n+' span').textContent='reachable ('+ms+' ms)';" +
    "results.push({key:p.key,ok:true,ms});ws.close();left--;finish();};" +
    "ws.onerror=()=>{if(done)return;done=true;clearTimeout(to);" +
    "const ms=Date.now()-t0;" +
    "document.querySelector('#r'+p.n+' span').textContent='unreachable ('+ms+' ms)';" +
    "results.push({key:p.key,ok:false,ms});left--;finish();};" +
    "}catch(e){if(done)return;done=true;clearTimeout(to);" +
    "document.querySelector('#r'+p.n+' span').textContent='unreachable';" +
    "results.push({key:p.key,ok:false,ms:0});left--;finish();}});" +
    "if(left===0)document.getElementById('done').textContent='No checkable configs in this VIP set.';" +
    "</script></body></html>";
}

async function handleCheckPage(request, env) {
  const url = new URL(request.url);
  if (request.method === "POST") {
    const body = await request.json().catch(() => null);
    const uid = body ? await verifyCheckToken(env, body.token) : null;
    if (!uid) return Response.json({ ok: false, error: "bad_token" }, { status: 403 });
    const results = Array.isArray(body.results) ? body.results : [];
    const clean = results.filter(r =>
      r && typeof r.key === "string" && /^[0-9a-f]{64}$/.test(r.key) &&
      typeof r.ok === "boolean" &&
      typeof r.ms === "number" && r.ms >= 0 && r.ms <= 60000)
      .slice(0, 64);
    if (!clean.length) return Response.json({ ok: true, recorded: 0 });
    let existing = {};
    try { existing = JSON.parse(await env.MERIDIAN_STORE.get("checker_verdicts") || "{}"); } catch (e) {}
    const merged = mergeVerdicts(existing, clean, Math.floor(Date.now() / 1000));
    await env.MERIDIAN_STORE.put("checker_verdicts", JSON.stringify(merged));
    return Response.json({ ok: true, recorded: clean.length });
  }
  const uid = await verifyCheckToken(env, url.searchParams.get("t"));
  if (!uid) return new Response("This check link is invalid or expired — run /check in the bot for a fresh one.", { status: 403 });
  const index = await loadIndex(env);
  const sub = await env.MERIDIAN_STORE.get("vip_sub");
  let uris = [];
  try { uris = atob(sub || "").split("\n").filter(Boolean); }
  catch (e) { uris = []; }
  const items = (index && index.items) || [];
  const probes = items.slice(0, uris.length).map((it, i) => ({
    n: it.n, key: it.key, remark: it.remark, url: probeUrl(uris[i] || "")
  }));
  return new Response(buildCheckPage(probes, url.searchParams.get("t")),
    { headers: { "content-type": "text/html; charset=utf-8" } });
}

function vipIntroText(secret) {
  return "\u{1FABC} PROXIV3 VIP\n\nYour subscription links (keep them private):\n" +
    "Primary: " + SUB_BASE + secret + "\n" +
    "Backup (mirror route, same subscription): " + SUB2_BASE + secret + "\n\n" +
    "Import either one into your v2ray client or panel — the configs refresh automatically every hour.\n\n" +
    "Browser check: /check — test this hour's VIP set from your own network in your browser.\n\n" +
    "Self-check: Network Checker (github.com/mirarr-app/network-checker) finds clean IPs from your own ISP — note: its desktop Xray download has no checksum check and its IP lookup uses plain HTTP.";
}

async function sendVip(send, env, uid, chat) {
  let kvVip = [];
  try { kvVip = JSON.parse(await env.MERIDIAN_STORE.get("vip_users") || "[]"); } catch (e) {}
  if (!isVip(env, kvVip, uid)) {
    await send("VIP is invite-only for now. Public verified configs: @Proxiv3");
    return;
  }
  const secret = await env.MERIDIAN_STORE.get("sub_secret");
  if (!secret) { await send("VIP subscription is not ready yet — please try again shortly."); return; }
  await send(vipIntroText(secret));
  const index = await loadIndex(env);
  if (index && index.items && index.items.length) {
    const lines = index.items.map(i => i.n + ". " + i.remark).join("\n");
    const rows = [];
    for (let i = 0; i < index.items.length; i += 4) {
      rows.push(index.items.slice(i, i + 4).map(it => ({
        text: "❌ " + it.n,
        callback_data: "d:" + index.tag + ":" + it.n
      })));
    }
    rows.push([{ text: "✅ All worked", callback_data: "w:" + index.tag + ":all" }]);
    await tg(env, "sendMessage", {
      chat_id: chat, text: "Field check — configs in this hour's VIP set:\n" + lines +
        "\n\nTap ❌ on any that did NOT connect for you (it gets quarantined until re-verified), or ✅ if all worked.",
      reply_markup: { inline_keyboard: rows }
    });
  }
}

async function handleCallback(cb, env) {
  const uid = String(cb.from && cb.from.id);
  const data = String(cb.data || "");
  const answer = (t) => tg(env, "answerCallbackQuery", { callback_query_id: cb.id, text: t });
  let kvVip = [];
  try { kvVip = JSON.parse(await env.MERIDIAN_STORE.get("vip_users") || "[]"); } catch (e) {}
  if (!isVip(env, kvVip, uid)) { await answer("VIP only."); return; }
  const parts = data.split(":");
  const index = await loadIndex(env);
  if (!index || parts[1] !== index.tag) {
    await answer("That list has refreshed — run /vip for the current one.");
    return;
  }
  if (parts[0] === "w" && parts[2] === "all") {
    await recordFeedbackBatch(env, index.items.map(it => it.key), "works");
    await answer("✅ Noted — all marked working. Thank you!");
    return;
  }
  const item = index.items.find(i => String(i.n) === parts[2]);
  if (!item) { await answer("Not on the current list."); return; }
  if (parts[0] === "d") {
    await recordFeedback(env, item.key, "dead");
    await answer("❌ Noted — config " + item.n + " quarantined until it re-verifies.");
  } else if (parts[0] === "w") {
    await recordFeedback(env, item.key, "works");
    await answer("✅ Noted — config " + item.n + " marked working.");
  }
}

async function handleUpdate(update, env) {
  if (update && update.callback_query) { await handleCallback(update.callback_query, env); return; }
  const msg = update && update.message;
  if (!msg || !msg.text || !msg.chat || msg.chat.type !== "private") return;
  const uid = String(msg.from && msg.from.id);
  const chat = msg.chat.id;
  const text = msg.text.trim();
  const send = (t) => tg(env, "sendMessage", { chat_id: chat, text: t });
  if (text.startsWith("/start")) {
    await send("\u{1FABC} PROXIV3 Pool\n\n" +
      "Public verified configs are posted every hour in @Proxiv3 — every config is proven working end-to-end before it is posted.\n\n" +
      "VIP members: /vip gives you the subscription link (import once, configs refresh hourly) and a one-tap field-feedback list.\n" +
      "/help — about and feedback");
    return;
  }
  if (text.startsWith("/vip")) { await sendVip(send, env, uid, chat); return; }
  if (text.startsWith("/check")) {
    let kvVip = [];
    try { kvVip = JSON.parse(await env.MERIDIAN_STORE.get("vip_users") || "[]"); } catch (e) {}
    if (!isVip(env, kvVip, uid)) { await send("VIP only."); return; }
    const token = await issueCheckToken(env, uid);
    if (!token) { await send("The checker is not ready yet — please try again shortly."); return; }
    await send("Check the current VIP configs from your own network:\n" + CHECK_BASE + "?t=" + token +
      "\n\nOpen the link in your browser — it tries each config from your network and sends the results back. The link works for 24 hours and only for you.");
    return;
  }
  if (text.startsWith("/help")) {
    await send("This bot serves the \u{1FABC} PROXIV3 verified pool.\n\n" +
      "• Public configs: posted hourly in @Proxiv3\n" +
      "• /vip — your VIP subscription link + feedback list (VIP members only)\n" +
      "• /check — test the current VIP configs from your own network in your browser (VIP members only)\n" +
      "• Feedback: tap ❌/✅ under /vip, or reply \"dead N\" / \"works N\" with the config's number from the list. A dead report quarantines that config until it passes verification again.\n" +
      "• Self-check: if configs keep failing from your network, Network Checker (github.com/mirarr-app/network-checker) finds clean IPs from your own ISP and tests them — a useful companion before reporting a config dead.\n" +
      "  Two caveats: its desktop Xray download has no checksum verification, and its public-IP lookup uses plain HTTP.");
    return;
  }
  const m = text.match(/^(works|dead)\s+(\d+)\s*$/i);
  if (m) {
    let kvVip = [];
    try { kvVip = JSON.parse(await env.MERIDIAN_STORE.get("vip_users") || "[]"); } catch (e) {}
    if (!isVip(env, kvVip, uid)) { await send("VIP only."); return; }
    const index = await loadIndex(env);
    const item = index && index.items.find(i => String(i.n) === m[2]);
    if (!item) { await send("That number is not on the current VIP list — run /vip to refresh it."); return; }
    await recordFeedback(env, item.key, m[1].toLowerCase());
    await send(m[1].toLowerCase() === "dead"
      ? "❌ Noted — quarantined until re-verified."
      : "✅ Noted — marked working.");
    return;
  }
  await send("Use /start, /vip or /help.");
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === "/health") {
      return Response.json({ ok: true, service: "meridian-bot" });
    }
    if (url.pathname === "/check") {
      return handleCheckPage(request, env);
    }
    if (url.pathname === "/webhook" && request.method === "POST") {
      const expected = await env.MERIDIAN_STORE.get("webhook_secret");
      if (!expected || request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== expected) {
        return new Response("forbidden", { status: 403 });
      }
      const update = await request.json().catch(() => null);
      if (update) ctx.waitUntil(handleUpdate(update, env));
      return new Response("ok");
    }
    return new Response("not found", { status: 404 });
  }
}
