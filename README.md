# koto

Todo manager with a Textual TUI and a mobile-friendly web interface.

## Features

- Workspaces with nested sub-workspaces
- Todos with description, due date, urgency, effort, recurrence
- Nested sub-todos with auto-propagating completion state (parent completes when all children do; reopens when any child reopens)
- Recurring todos: completing one marks it done for the cycle, advances `due`, bumps `recurrence_count`. Lazy re-arm on the next list call once `due` passes. Undo rolls everything back symmetrically.
- Cut / Copy / Paste (with subtree); paste-as-sibling or paste-as-child
- Sort: move completed siblings to the bottom of their scope
- REST API with token auth
- WebSocket push for real-time multi-client sync
- **Textual TUI** (arrow-key + vim-flavored keybindings, two-panel layout, themeable) — primary desktop interface
- **Mobile-first responsive web client** — for phones
- SQLite storage with WAL mode

## Install

```sh
uv sync
```

## Run

```sh
uv run koto serve --token <your-secret>
```

Then open `http://<server-ip>:28080` in a browser.

## TUI

```sh
uv run koto tui --token <your-secret> --server-url http://<server-ip>:28080
```

Or set `KOTO_TUI_TOKEN` and `KOTO_TUI_SERVER_URL` env vars (or put them in `[tui]` section of the config file).

Press `?` for the full keybindings cheatsheet.

Layout: workspace tree on the left, todo tree on the right. Each todo row has right-aligned columns for due date, urgency, effort, recurrence, and sub-task progress. Long descriptions truncate with `…`.

**Globals:** `?` help, `q` quit, `r` force refresh, `1` / `2` focus panels.

**Workspace tree:**
- `↑` / `↓` move, `→` first sub-workspace (or open todos), `←` parent
- `enter` / `space` open workspace
- `o` toggle expand/collapse
- `n` new workspace (sibling), `N` new sub-workspace
- `e` rename, `d` delete
- `shift+↓` / `shift+↑` reorder

**Todo tree:**
- `↑` / `↓` move, `→` first sub-todo, `←` parent (or back to workspaces)
- `escape` jump to workspace panel
- `o` toggle expand/collapse
- `space` toggle pending
- `n` new todo (sibling), `N` new sub-todo
- `e` edit (description, due, urgency, effort, recurrence)
- `d` delete
- `x` / `c` / `p` cut / copy / paste (with subtree), `P` paste as child
- `s` sort: completed siblings to bottom
- `shift+↓` / `shift+↑` reorder

## Configuration

A TOML config file is auto-created on first run at the platform user-config dir:

- Linux: `~/.config/koto/config.toml`
- macOS: `~/Library/Application Support/koto/config.toml`
- Windows: `%APPDATA%\koto\config.toml`

It has separate `[server]` and `[tui]` sections. Settings precedence (highest first):

1. CLI flag (e.g. `--token`)
2. Environment variable (e.g. `KOTO_TOKEN`)
3. Config file
4. Built-in default

Pass `--config /path/to/file.toml` (or set `KOTO_CONFIG`) to use a non-default location.

Server env vars: `KOTO_TOKEN`, `KOTO_HOST`, `KOTO_PORT`, `KOTO_DB_PATH`
TUI env vars: `KOTO_TUI_SERVER_URL`, `KOTO_TUI_TOKEN`, `KOTO_TUI_THEME`

`[tui]` settings:

| Key | Default | Description |
|---|---|---|
| `server_url` | `http://localhost:28080` | koto server URL |
| `token` | _(required)_ | auth token |
| `theme` | `textual-dark` | one of: `textual-dark`, `textual-light`, `nord`, `gruvbox`, `dracula`, `tokyo-night`, `monokai`, `flexoki`, `catppuccin-{mocha,latte,frappe,macchiato}`, `solarized-{light,dark}`, `rose-pine{,-moon,-dawn}`, `atom-one-{dark,light}`, `ansi-{dark,light}` |
| `show_clock` | `true` | show date+time in the header |
| `confirm_delete` | `true` | show a confirmation modal before deleting |
| `default_workspace_id` | _(unset)_ | auto-open this workspace on startup |

## API

All endpoints require `Authorization: Bearer <token>` header. Optional `X-Client-Id` header lets a client opt out of receiving its own broadcast (avoids re-fetching after every mutation).

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/workspaces` | Workspace tree |
| POST | `/api/workspaces` | Create workspace |
| PATCH | `/api/workspaces/{id}` | Update workspace |
| DELETE | `/api/workspaces/{id}` | Delete workspace |
| POST | `/api/workspaces/{id}/reorder` | Move up/down |
| GET | `/api/todos/workspace/{id}` | Todos in workspace |
| GET | `/api/todos/{id}` | Single todo |
| POST | `/api/todos` | Create todo (exactly one of `parent_workspace_id` / `parent_todo_id`) |
| PATCH | `/api/todos/{id}` | Update todo |
| DELETE | `/api/todos/{id}` | Delete todo |
| POST | `/api/todos/{id}/toggle` | Toggle pending (recurring: advance due, bump count, or roll back on undo) |
| POST | `/api/todos/{id}/reorder` | Move up/down |
| POST | `/api/todos/{id}/sort_completed` | Sort the children of this todo so completed ones go last |
| POST | `/api/todos/workspace/{id}/sort_completed` | Same, but for top-level todos in a workspace |
| WS | `/ws?token=<token>&client_id=<id>` | Real-time updates |

### Notes

- **Clearing nullable fields**: PATCH a todo with `"due": null` or `"recurrence_seconds": null` to clear that field. Omit the field entirely to leave it unchanged.
- **Field bounds**: `urgency` 0–10, `effort` 0–100, `description` ≤ 2000 chars.
- **Workspace counts** (`todo_count`, `pending_count`, `done_count`, `overdue_count`, `due_today_count`) reflect *direct* top-level todos in the workspace only — they do not aggregate sub-todos or child workspaces.
- **Timezone**: SQLite has no native timezone storage. The server stores naive datetimes interpreted as the **server's local time**, and `overdue` / `due today` are computed against `datetime.now()` in the server's TZ. Clients should send dates in the server's local time, or operate the server in UTC.

## Deploy as systemd service (Linux)

```sh
# 1. Install
sudo pip install --system /path/to/koto    # or build a wheel and install it

# 2. Create dedicated user
sudo useradd -r -s /usr/sbin/nologin koto

# 3. Create env file with your token (chmod 600 — readable only by root)
sudo install -d -m 700 /etc/koto
sudo tee /etc/koto/env >/dev/null <<'EOF'
KOTO_TOKEN=replace-me-with-a-real-token
EOF
sudo chmod 600 /etc/koto/env

# 4. Install unit and start
sudo cp koto/koto.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now koto
```

The unit creates `/var/lib/koto` automatically (via `StateDirectory=`) and runs sandboxed (`ProtectSystem=strict`, `NoNewPrivileges`, restricted syscalls, etc.). The DB lives at `/var/lib/koto/koto.db`.

## Remote access

The server only listens on a local port. To reach it from outside the LAN, use [Tailscale](https://tailscale.com/) — install on both devices, then access the server's `100.x.x.x` IP. No port forwarding or domain needed.

## Threat model

koto is designed for a **single trusted user** (or a small group sharing one token) on a **trusted network** (LAN or VPN like Tailscale). Specifically:

- **Single shared secret** auth, no per-user identity, no audit log.
- **Token rotation** requires editing config/env and restarting the server.
- **No rate limiting** on auth — pair with a VPN or fail2ban if you expose the port.
- **Token in browser localStorage** — any XSS in the client compromises it. Inputs are escaped, but treat the static UI as part of the trust boundary.
- **WS auth** uses a query-string token. If you put a reverse proxy in front, ensure it does not log full URLs.

If you need stronger guarantees (multi-tenant, untrusted network, audit), this isn't the right tool.

## Backup

The DB is a single SQLite file. With WAL mode, the safest copy is via `sqlite3 koto.db ".backup /path/to/backup.db"` rather than a raw `cp`. A daily systemd timer running `.backup` works well.
