import os
import tomllib
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir, user_data_dir


DEFAULT_CONFIG = """\
# koto configuration
# Precedence (highest first): CLI flag > environment variable > this file > built-in default
#
# Environment variable equivalents:
#   server: KOTO_TOKEN, KOTO_HOST, KOTO_PORT, KOTO_DB_PATH
#   tui:    KOTO_TUI_SERVER_URL, KOTO_TUI_TOKEN, KOTO_TUI_THEME

[server]
# Required: shared secret clients must present
# token = "change-me"

host = "0.0.0.0"
port = 28080

# Database file location. Defaults to the platform user-data dir.
# db_path = "/var/lib/koto/koto.db"

[tui]
# URL of the koto server the TUI should connect to
server_url = "http://localhost:28080"

# Token for the TUI to authenticate with
# token = "change-me"

# Color theme. One of: textual-dark, textual-light, nord, gruvbox,
# catppuccin-mocha, catppuccin-latte, catppuccin-frappe, catppuccin-macchiato,
# dracula, tokyo-night, monokai, flexoki, solarized-light, solarized-dark,
# rose-pine, rose-pine-moon, rose-pine-dawn, atom-one-dark, atom-one-light,
# ansi-dark, ansi-light.
theme = "textual-dark"

# Show clock in the header bar.
show_clock = true

# Skip the confirmation modal when deleting workspaces/todos. Off by default.
confirm_delete = true

# Workspace id to auto-open on startup. Leave unset to use the first one.
# default_workspace_id = 1
"""


def _config_file_path() -> Path:
    custom = os.environ.get("KOTO_CONFIG")
    if custom:
        return Path(custom).expanduser()
    return Path(user_config_dir("koto")) / "config.toml"


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise RuntimeError(f"Invalid TOML in {path}: {e}") from e


def _ensure_config_file(path: Path) -> None:
    if path.exists():
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_CONFIG)
    except OSError:
        # Read-only filesystem or permission issue — not fatal.
        pass


class Settings:
    def __init__(self):
        self.config_path = _config_file_path()
        _ensure_config_file(self.config_path)
        cfg = _load_toml(self.config_path)

        server = cfg.get("server", {})
        tui = cfg.get("tui", {})

        # Server
        self.token: str = (
            os.environ.get("KOTO_TOKEN") or server.get("token") or ""
        )
        self.host: str = (
            os.environ.get("KOTO_HOST") or server.get("host") or "0.0.0.0"
        )
        self.port: int = int(
            os.environ.get("KOTO_PORT") or server.get("port") or 28080
        )

        db_dir = Path(user_data_dir("koto"))
        db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path: str = (
            os.environ.get("KOTO_DB_PATH")
            or server.get("db_path")
            or str(db_dir / "koto.db")
        )

        # TUI (consumed by the TUI client when implemented)
        self.tui_server_url: str = (
            os.environ.get("KOTO_TUI_SERVER_URL")
            or tui.get("server_url")
            or "http://localhost:28080"
        )
        self.tui_token: str = (
            os.environ.get("KOTO_TUI_TOKEN") or tui.get("token") or ""
        )
        self.tui_theme: str = (
            os.environ.get("KOTO_TUI_THEME")
            or tui.get("theme")
            or "textual-dark"
        )
        self.tui_show_clock: bool = bool(tui.get("show_clock", True))
        self.tui_confirm_delete: bool = bool(tui.get("confirm_delete", True))
        default_ws = tui.get("default_workspace_id")
        self.tui_default_workspace_id: int | None = (
            int(default_ws) if default_ws is not None else None
        )


settings = Settings()
