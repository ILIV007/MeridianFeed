// meridian-peak — Phase 4 anchor: a minimal own VLESS + WebSocket + TLS
// endpoint (MeridianFeed). The WS path and the VLESS UUID live in KV
// (node_path, anchor_uuid) and are never published in code. Anything
// else is a bland 404/ok surface. Low-volume backbone anchor only.
// cloudflare:sockets is imported lazily inside the WS branch — a static
// import made the whole module fail evaluation on this account.
//
// STATUS 2026-11-20: CLOSED — PARKED by wolf's instruction. Final
// re-test the same day: the exact source was uploaded as a throwaway
// probe Worker — it answered briefly, then returned HTTP 500 on every
// route, while a no-sockets control Worker on the same account served
// normally and meridian-pub stayed healthy. The platform block stands.
// The anchor is in no pool and the system is fully live without it;
// there is no sockets-free way to egress arbitrary TCP from a Worker.
// Reopening needs a dashboard/wrangler deploy or a CF platform change.
// See worker/README.md and docs/PLAN.md (Phase 4) for the full record.
function hexToBytes(hex) {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.substr(i * 2, 2), 16);
  return out;
}
function equal(a, b) {
  if (a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a[i] ^ b[i];
  return d === 0;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/") return new Response("ok");
    const nodePath = await env.MERIDIAN_STORE.get("node_path");
    if (!nodePath || url.pathname !== nodePath) return new Response("not found", { status: 404 });
    if (request.headers.get("Upgrade") !== "websocket") {
      return new Response("expected websocket", { status: 400 });
    }
    const uuid = await env.MERIDIAN_STORE.get("anchor_uuid");
    if (!uuid) return new Response("not ready", { status: 503 });
    const uuidBytes = hexToBytes(uuid.replace(/-/g, ""));
    const pair = new WebSocketPair();
    const client = pair[0], server = pair[1];
    server.accept();
    let writer = null, remote = null, headerDone = false;
    server.addEventListener("message", async (event) => {
      try {
        const chunk = new Uint8Array(event.data);
        if (writer) { await writer.write(chunk); return; }
        if (headerDone) return;
        const version = chunk[0];
        if (!equal(chunk.slice(1, 17), uuidBytes)) { server.close(1008, "auth"); return; }
        let idx = 17;
        idx += 1 + chunk[idx];               // addon length + addons
        const command = chunk[idx]; idx += 1;
        if (command !== 1) { server.close(1008, "cmd"); return; }  // TCP only
        const port = (chunk[idx] << 8) | chunk[idx + 1]; idx += 2;
        const atype = chunk[idx]; idx += 1;
        let host = "";
        if (atype === 1) { host = Array.from(chunk.slice(idx, idx + 4)).join("."); idx += 4; }
        else if (atype === 2) {
          const len = chunk[idx]; idx += 1;
          host = new TextDecoder().decode(chunk.slice(idx, idx + len)); idx += len;
        } else if (atype === 3) {
          const parts = [];
          for (let i = 0; i < 8; i++) parts.push(((chunk[idx + i * 2] << 8) | chunk[idx + i * 2 + 1]).toString(16));
          host = parts.join(":"); idx += 16;
        } else { server.close(1008, "atype"); return; }
        headerDone = true;
        const { connect } = await import("cloudflare:sockets");
        remote = connect({ hostname: host, port: port });
        await remote.opened;
        writer = remote.writable.getWriter();
        server.send(new Uint8Array([version, 0]));
        const rest = chunk.slice(idx);
        if (rest.length) await writer.write(rest);
        const reader = remote.readable.getReader();
        (async () => {
          try {
            for (;;) {
              const { done, value } = await reader.read();
              if (done) break;
              server.send(value);
            }
          } catch (e) {}
          try { server.close(); } catch (e) {}
        })();
      } catch (e) {
        try { server.close(1011, "err"); } catch (_) {}
      }
    });
    server.addEventListener("close", () => { try { if (remote) remote.close(); } catch (e) {} });
    return new Response(null, { status: 101, webSocket: client });
  }
};
