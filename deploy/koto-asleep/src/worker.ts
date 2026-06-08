/// <reference types="@cloudflare/workers-types" />

// koto-asleep — fronts the koto.rushivivek.com route.
//
// Cloudflare's request pipeline runs Access BEFORE Workers, so by the time
// this Worker executes the eyeball is already authenticated. The Worker's job
// is narrow: pass through to the tunnel origin when koto is up, and serve a
// branded "napping" page (503 + Retry-After) when the origin is unreachable
// because the laptop is asleep / cloudflared is down.
//
// Same-zone subrequest rule: a Worker fetch() to its own hostname is routed to
// the ORIGIN (the tunnel CNAME), never back through this Worker — so there is
// no loop, and `fetch(request)` reaches koto directly.

interface Env {}

// Proxy/tunnel-level failures, NOT application errors:
//   530 -> Cloudflare error 1033 (Argo tunnel down / cloudflared not running)
//   502 -> cloudflared up but nothing listening on 127.0.0.1:8080 (koto down)
//   504 -> origin accepted but timed out
// koto's own uvicorn/FastAPI never emits these, so masking them is safe; a real
// koto 500 still passes through untouched so genuine app errors stay visible.
const ORIGIN_DOWN = new Set([502, 504, 530]);

const NAP_PAGE = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>koto is napping</title>
<style>
  :root {
    --bg: #1a1b26; --card: #24283b; --border: #414868;
    --fg: #c0caf5; --muted: #565f89; --accent: #7aa2f7; --moon: #e0af68;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    background: var(--bg); color: var(--fg);
    font: 16px/1.6 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    display: flex; align-items: center; justify-content: center;
    padding: 1.5rem;
  }
  .card {
    background: var(--card); border: 1px solid var(--border);
    border-radius: 16px; padding: 2.5rem 2rem; max-width: 26rem;
    width: 100%; text-align: center;
    box-shadow: 0 12px 40px rgba(0,0,0,.35);
  }
  .moon {
    width: 56px; height: 56px; margin: 0 auto 1.25rem;
    border-radius: 50%;
    background: radial-gradient(circle at 70% 35%, transparent 55%, var(--moon) 56%);
    box-shadow: inset -6px -4px 0 0 var(--moon);
    transform: rotate(-18deg);
  }
  h1 { margin: 0 0 .5rem; font-size: 1.5rem; color: var(--accent); font-weight: 650; }
  p { margin: .35rem 0; color: var(--fg); }
  .sub { color: var(--muted); font-size: .9rem; }
  code {
    background: var(--bg); border: 1px solid var(--border);
    border-radius: 6px; padding: .1rem .4rem; font-size: .85rem; color: var(--moon);
  }
</style>
</head>
<body>
  <main class="card">
    <div class="moon" aria-hidden="true"></div>
    <h1>koto is napping</h1>
    <p>The laptop's asleep, so the server isn't reachable right now.</p>
    <p class="sub">This page refreshes itself every 30 seconds — it'll come back on its own once the machine wakes.</p>
  </main>
</body>
</html>
`;

const napping = (): Response =>
  new Response(NAP_PAGE, {
    status: 503,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "retry-after": "30",
      "cache-control": "no-store",
    },
  });

export default {
  async fetch(request: Request, _env: Env, _ctx: ExecutionContext): Promise<Response> {
    // Pass the eyeball request straight to origin. For a WebSocket upgrade
    // (/ws) this returns a 101 response carrying the `webSocket` handle — we
    // MUST return that object untouched (no `new Response(...)` wrapping) or
    // the upgrade breaks. Same for normal streamed bodies.
    let originResp: Response | null = null;
    try {
      originResp = await fetch(request);
    } catch {
      // Network-level failure reaching origin — treat as asleep.
      return napping();
    }

    if (ORIGIN_DOWN.has(originResp.status)) return napping();

    return originResp;
  },
} satisfies ExportedHandler<Env>;
