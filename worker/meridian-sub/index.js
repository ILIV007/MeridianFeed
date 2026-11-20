// meridian-sub — serves the ONE VIP subscription (MeridianFeed).
// GET /sub/<secret> returns the current VIP pool (base64) with standard
// subscription headers. Wrong or missing secret = 404. The secret and
// the content both live in KV (MERIDIAN_STORE: sub_secret, vip_sub).
function b64Utf8(s) {
  const bytes = new TextEncoder().encode(s);
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/health") {
      return Response.json({ ok: true, service: "meridian-sub" });
    }
    const m = url.pathname.match(/^\/sub\/([A-Za-z0-9_-]{16,128})$/);
    if (!m) return new Response("not found", { status: 404 });
    const secret = await env.MERIDIAN_STORE.get("sub_secret");
    if (!secret || m[1] !== secret) return new Response("not found", { status: 404 });
    const body = await env.MERIDIAN_STORE.get("vip_sub");
    if (!body) return new Response("subscription not ready", { status: 503 });
    return new Response(body, {
      headers: {
        "content-type": "text/plain; charset=utf-8",
        "profile-title": "base64:" + b64Utf8("\u{1FABC} PROXIV3 VIP"),
        "profile-update-interval": "1",
        "cache-control": "no-store"
      }
    });
  }
}