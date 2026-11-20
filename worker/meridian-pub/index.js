// meridian-pub — hourly publisher for the verified pool (MeridianFeed).
// Cron 33 * * * *: read the verified public pool from KV and post ONE
// Rich Message batch to the channel. Nothing is posted when the pool is
// missing or stale (>90 min) — quality over quantity, always.
// fetch(): health only. Posting uses the TELEGRAM_TOKEN Worker secret.
const CHANNEL = "@Proxiv3";
const MAX_STALE_MS = 90 * 60 * 1000;

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function buildRich(pool) {
  let html = "<h3>\u{1FABC} PROXIV3 — Verified V2Ray Configs</h3>";
  html += "<p>✅ <b>" + pool.configs.length + " configs</b>" +
    " · double-verified end-to-end · " + esc(pool.generated_at) + "</p>";
  for (const c of pool.configs) {
    html += "<p><b>" + esc(c.remark) + "</b></p><pre>" + esc(c.uri) + "</pre>";
  }
  html += "<p>\u{1FABC} @PROXIV3</p>";
  return html;
}

async function postBatch(env) {
  const raw = await env.MERIDIAN_STORE.get("public_pool");
  if (!raw) return { posted: false, reason: "no_pool" };
  const pool = JSON.parse(raw);
  if (!pool.configs || !pool.configs.length) return { posted: false, reason: "empty_pool" };
  if (Date.now() - Date.parse(pool.generated_at) > MAX_STALE_MS) {
    return { posted: false, reason: "stale_pool" };
  }
  const resp = await fetch(
    "https://api.telegram.org/bot" + env.TELEGRAM_TOKEN + "/sendRichMessage",
    { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ chat_id: CHANNEL, rich_message: { html: buildRich(pool) } }) });
  const data = await resp.json().catch(() => ({}));
  if (data && data.ok) {
    await env.MERIDIAN_STORE.put("last_post", JSON.stringify(
      { at: new Date().toISOString(), message_id: data.result.message_id }));
    return { posted: true, message_id: data.result.message_id };
  }
  return { posted: false, reason: "telegram_error", detail: data && data.description };
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(postBatch(env));
  },
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/health") {
      const last = await env.MERIDIAN_STORE.get("last_post");
      return Response.json({ ok: true, service: "meridian-pub", last_post: last ? JSON.parse(last) : null });
    }
    return new Response("not found", { status: 404 });
  }
}