// meridian-bot — the single bot Worker for @Pool_IVbot (MeridianFeed).
// The whole V2Ray flow lives in this one bot: /start menu, the VIP
// section (/vip hands the single subscription link to admins/VIPs
// only), /help, and per-config field feedback.
//
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
  let fb = {};
  try { fb = JSON.parse(await env.MERIDIAN_STORE.get("feedback") || "{}"); } catch (e) {}
  if (typeof fb !== "object" || Array.isArray(fb)) fb = {};
  const now = Math.floor(Date.now() / 1000);
  const e = fb[key] || { works: 0, dead: 0 };
  if (kind === "works") { e.works += 1; e.works_ts = now; }
  else { e.dead += 1; e.dead_ts = now; }
  fb[key] = e;
  await env.MERIDIAN_STORE.put("feedback", JSON.stringify(fb));
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
  await send("\u{1FABC} PROXIV3 VIP\n\nYour subscription links (keep them private):\n" +
    "Primary: " + SUB_BASE + secret + "\n" +
    "Backup (mirror route, same subscription): " + SUB2_BASE + secret + "\n\n" +
    "Import either one into your v2ray client or panel — the configs refresh automatically every hour.\n\n" +
    "Self-check: Network Checker (github.com/mirarr-app/network-checker) finds clean IPs from your own ISP — note: its desktop Xray download has no checksum check and its IP lookup uses plain HTTP.");
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
    for (const it of index.items) await recordFeedback(env, it.key, "works");
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
  if (text.startsWith("/help")) {
    await send("This bot serves the \u{1FABC} PROXIV3 verified pool.\n\n" +
      "• Public configs: posted hourly in @Proxiv3\n" +
      "• /vip — your VIP subscription link + feedback list (VIP members only)\n" +
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
