# koto deploy — public access at `koto.rushivivek.com`

Exposes the local koto server (on this CachyOS laptop) at `koto.rushivivek.com`
without needing Tailscale on every device.

**Layering (Cloudflare's native request order):**

```
browser ──▶ Cloudflare Access (edge auth: Google / email OTP)
         ──▶ koto-asleep Worker (route owner: pass-through, or "napping" page)
         ──▶ Cloudflare Tunnel (cloudflared on the laptop)
         ──▶ koto uvicorn @ 127.0.0.1:8080
```

koto's FastAPI app is **untouched**. Everything here is infra/config.

- **Port:** koto listens on `0.0.0.0:8080` (systemd unit `ExecStart … --port 8080`;
  `KOTO_PORT` unset so the 8080 default holds). The tunnel ingress points at
  `127.0.0.1:8080` — not `localhost`, to avoid an IPv6 (`::1`) mis-resolve.
- **Bind note:** koto binds `0.0.0.0`, so it's reachable on the LAN too. That's
  the existing behaviour (Tailscale already used it). The tunnel adds public
  reach on top; it does not change koto's bind.

Directories:

- `cloudflared/config.yml` — tunnel ingress (committed, no secrets).
- `koto-asleep/` — Cloudflare Worker: transparent pass-through + branded 503
  "napping" page when the origin is down.

---

## 0. Prerequisites

- `wrangler` + Cloudflare account: already set up (boreas).
- `cloudflared`: **not yet installed.** On CachyOS:
  ```sh
  sudo pacman -S cloudflared
  ```
  (or the AUR `cloudflared-bin` if you prefer the upstream binary).

---

## 1. Cloudflare Tunnel — one-time setup

Run these yourself. **Steps marked 🌐 open a browser** for Cloudflare auth.

```sh
# 🌐 Authenticate cloudflared to your CF account + pick the rushivivek.com zone.
#    Writes ~/.cloudflared/cert.pem (a secret — git-ignored).
cloudflared tunnel login

# Create the named tunnel "koto". Prints a TUNNEL UUID and writes the tunnel
# credentials to ~/.cloudflared/<UUID>.json (a secret — git-ignored).
cloudflared tunnel create koto

# Route the hostname to this tunnel (creates the CNAME in Cloudflare DNS).
cloudflared tunnel route dns koto koto.rushivivek.com
```

Install the config + credentials to the system location and run as a service:

```sh
# Put the (non-secret) ingress config in place.
sudo install -d -m 700 /etc/cloudflared
sudo cp ~/Scripts/koto/deploy/cloudflared/config.yml /etc/cloudflared/config.yml

# Copy the tunnel credentials JSON (secret) next to it, and point
# `credentials-file:` in config.yml at its real path. Replace <UUID>.
sudo cp ~/.cloudflared/<UUID>.json /etc/cloudflared/<UUID>.json
sudo sed -i "s|<TUNNEL_UUID>|<UUID>|" /etc/cloudflared/config.yml

# Install + start the systemd service (reads /etc/cloudflared/config.yml).
sudo cloudflared service install
sudo systemctl enable --now cloudflared
systemctl status cloudflared        # expect: active (running)
```

**Sleep behaviour (accepted):** when the laptop sleeps, `cloudflared` is
suspended with it, so the tunnel drops and koto is unreachable — that's what the
Worker's napping page is for. No `WantedBy`/wake config needed; on resume,
cloudflared reconnects automatically (usually within seconds).

At this point `koto.rushivivek.com` resolves but is **wide open** to anyone with
the URL until you add Access (step 3). Do step 3 before relying on it.

---

## 2. koto-asleep Worker — deploy + bind route

```sh
cd ~/Scripts/koto/deploy/koto-asleep
npm install
npm run deploy        # wrangler deploy — binds koto.rushivivek.com/* (per wrangler.toml)
```

`wrangler.toml` binds `koto.rushivivek.com/*`. The Worker calls `fetch(request)`
to the same host; Cloudflare routes that subrequest to the **tunnel origin**
(not back through the Worker), so there's no loop. On a `502/504/530` from the
origin it serves the 503 napping page; otherwise it streams the origin response
through verbatim — including the `/ws` WebSocket 101 upgrade.

Test the Worker locally against a fake-down origin if you want, but the real
test is in step 4.

---

## 3. Cloudflare Access — gate the hostname (REQUIRED)

koto's only app auth is a single shared bearer token meant for a trusted
network. **Access is what makes public exposure acceptable** — never rely on the
bare tunnel. Dashboard steps (Zero Trust dashboard, `one.dash.cloudflare.com`):

1. **Zero Trust → Access → Applications → Add an application → Self-hosted.**
2. **Application name:** `koto`. **Session duration:** `1 month` (so you're not
   re-authing constantly on your phone).
3. **Application domain:** `koto.rushivivek.com` (subdomain `koto`, domain
   `rushivivek.com`, path blank — covers `/`, `/api/*`, **and `/ws`**).
4. **Identity providers:** enable **Google** and/or **One-time PIN** (email OTP).
   One-time PIN works with no IdP config and covers any family email; Google is
   smoother if everyone has a Google account.
5. **Policies → Add a policy:**
   - Name: `allowed humans`, Action: **Allow**.
   - Include → **Emails** → add your email + each family email explicitly
     (e.g. `rushivivek123@gmail.com`, plus family). Use **Emails** (not "Email
     domain") so it's a fixed allowlist, matching koto's small-trust model.
6. Save. Access is now enforced at the edge, before the Worker runs.

### How the web client (XHR + WebSocket) gets through Access

- After the user signs in, Access sets a **`CF_Authorization` cookie** scoped to
  `koto.rushivivek.com`. Because koto's SPA is **same-origin** (its `fetch` calls
  go to `""` + path, and the WS URL is built from `location.host` — verified in
  `koto/static/api.js`), the browser **automatically sends that cookie** on every
  XHR and on the `/ws` WebSocket handshake. So `/api/*` and `/ws` pass Access
  with no client change.
- One caveat to know: **Access cookie sessions cover browser requests only.**
  They are not a programmatic credential.

### Does the Textual TUI need an Access service token?

**Recommendation: keep the TUI on localhost / Tailscale. Do NOT point it at the
public URL.** Reasons:

- The TUI is a **non-browser HTTP client** (httpx). It can't do the interactive
  Access login, so hitting `https://koto.rushivivek.com` would just bounce off
  the Access login redirect and fail.
- You run the TUI **on the same laptop koto runs on** — so `http://localhost:8080`
  (its current default) is the correct, zero-latency, zero-auth-friction target.
  Nothing to change.
- If you ever want the TUI from *another* device, use Tailscale (still works,
  additive to the tunnel) and point `KOTO_TUI_SERVER_URL` at the tailnet host —
  again bypassing Access entirely.

**If you ever genuinely need the TUI through the public URL** (e.g. a device with
neither localhost nor Tailscale), the mechanism is an Access **service token**:

1. Zero Trust → Access → **Service Auth → Service Tokens → Create** (`koto-tui`).
   Note the Client ID + Client Secret (secret — do not commit; store in your
   password manager or a chmod-600 file).
2. Add an Access policy on the koto app: Action **Service Auth**, Include →
   **Service Token** → `koto-tui`.
3. The TUI would need to send `CF-Access-Client-Id` + `CF-Access-Client-Secret`
   headers on every request **and** the WS handshake. koto's TUI client doesn't
   send those today, so this would require a (small) code change — out of scope
   here, and unnecessary given localhost/Tailscale already cover you. Documented
   only so the path is known.

---

## 4. Verify the layering end-to-end

**A. Happy path (origin up):**
```sh
systemctl status cloudflared        # active
curl -I http://127.0.0.1:8080/       # koto answering locally (200)
```
In a browser: open `https://koto.rushivivek.com` → Access login → koto SPA loads.
Create a workspace + todo. Open it on your phone (no Tailscale) → same login →
same data. Toggle a todo on one device → the other updates within ~1s
(confirms the `/ws` WebSocket passed both Access and the Worker).

**B. Napping path (origin down) — the actual test:**
```sh
sudo systemctl stop cloudflared      # simulate the laptop being asleep
```
Then, **while still logged into Access**, reload `https://koto.rushivivek.com`.
- ✅ Expect: the tokyo-night **"koto is napping"** page, HTTP **503**,
  `Retry-After: 30`.
- ❌ Not expect: Cloudflare's default **Error 1033** / grey tunnel-down page.

Confirm the status code:
```sh
curl -sI https://koto.rushivivek.com | head -1     # HTTP/2 503
```
Restore:
```sh
sudo systemctl start cloudflared
```
Reload → the SPA returns (the page auto-refreshes every 30s, so it recovers on
its own too).

### Ordering gotchas (verified against CF's pipeline)

- **Access runs before the Worker.** So in test B you must be *already logged in*
  to see the napping page — a logged-out request gets the Access login screen
  first, never reaching the Worker. That's correct and desired (no unauth'd user
  should see anything, asleep or not).
- **The Worker's self-host subrequest hits the origin, not itself.** Cloudflare
  short-circuits same-zone Worker→origin fetches to the tunnel, so there's no
  recursion. If you ever see a loop/1019, it means the route pattern is wrong.
- **Don't mask real koto errors.** The Worker only converts `502/504/530`
  (proxy/tunnel-down signals koto never emits) into the napping page. A genuine
  koto `500` streams through so you still see real bugs.
- **530 is the asleep signal.** Cloudflare error 1033 surfaces to the Worker's
  `fetch()` as an HTTP **530** — that's why it's in the `ORIGIN_DOWN` set.

---

## Secrets — what's git-ignored (never committed)

- `cloudflared/cert.pem` — from `tunnel login`.
- `cloudflared/<UUID>.json` — tunnel credentials (private key).
- Access **service token** Client Secret (if you ever create one) — store
  externally, never in-repo.
- The koto `KOTO_TOKEN` itself stays in `/etc/koto/env` (mode 600), as before —
  unrelated to this deploy, untouched.

See `deploy/.gitignore`.
