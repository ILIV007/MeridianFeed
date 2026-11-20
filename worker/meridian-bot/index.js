// meridian-bot — the single bot Worker for @Pool_IVbot (MeridianFeed).
// The whole V2Ray flow lives in this one bot: /start menu, the VIP
// section (/vip hands the single subscription link to admins/VIPs
// only), /help, and working/dead feedback collection for the verifier.
// Webhook requests are verified against the secret stored in KV
// (webhook_secret). Replies use the TELEGRAM_TOKEN Worker secret.
const SUB_BASE = "https://meridian-sub.ilipoolv2r.workers.dev/sub/";

async function tg(env, method, body) {
  const r = await fetch("https://api.telegram.org/bot" + env.TELEGRAM_TOKEN + "/" + method,
    { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  return r.json().catch(() => ({}));
}

function isVip(env, kvVip, uid) {
  const admins = (env.ADMIN_IDS || "").split(",").map(s => s.trim()).filter(Boolean);
  return admins.includes(uid) || (kvVip || []).map(String).includes(uid);
}

async function handleUpdate(update, env) {
  const msg = update && update.message;
  if (!msg || !msg.text || !msg.chat || msg.chat.type !== "private") return;
  const uid = String(msg.from && msg.from.id);
  const chat = msg.chat.id;
  const text = msg.text.trim();
  const send = (t) => tg(env, "sendMessage", { chat_id: chat, text: t });
  if (text.startsWith("/start")) {
    await send("\u{1FABC} PROXIV3 Pool\n\n" +
      "Public verified configs are posted every hour in @Proxiv3 — every config is proven working end-to-end before it is posted.\n\n" +
      "VIP members: /vip gives you the subscription link (import once, configs refresh hourly).\n" +
      "/help — about and feedback");
    return;
  }
  if (text.startsWith("/vip")) {
    let kvVip = [];
    try { kvVip = JSON.parse(await env.MERIDIAN_STORE.get("vip_users") || "[]"); } catch (e) {}
    if (!isVip(env, kvVip, uid)) {
      await send("VIP is invite-only for now. Public verified configs: @Proxiv3");
      return;
    }
    const secret = await env.MERIDIAN_STORE.get("sub_secret");
    if (!secret) { await send("VIP subscription is not ready yet — please try again shortly."); return; }
    await send("\u{1FABC} PROXIV3 VIP\n\nYour subscription link (keep it private):\n" +
      SUB_BASE + secret + "\n\nImport it once into your v2ray client or panel — the configs refresh automatically every hour.");
    return;
  }
  if (text.startsWith("/help")) {
    await send("This bot serves the \u{1FABC} PROXIV3 verified pool.\n\n" +
      "• Public configs: posted hourly in @Proxiv3\n" +
      "• /vip — your VIP subscription link (VIP members only)\n" +
      "• Feedback: reply \"works\" or \"dead\" here and it is fed back into the verification scoring.");
    return;
  }
  if (/^(works|dead)\b/i.test(text)) {
    let list = [];
    try { list = JSON.parse(await env.MERIDIAN_STORE.get("feedback") || "[]"); } catch (e) {}
    list.push({ uid: uid, text: text.slice(0, 100), at: new Date().toISOString() });
    if (list.length > 200) list = list.slice(list.length - 200);
    await env.MERIDIAN_STORE.put("feedback", JSON.stringify(list));
    await send("Thanks — noted ✅");
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