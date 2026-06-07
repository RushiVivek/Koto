import os

import click
import uvicorn


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx):
    if ctx.invoked_subcommand is None:
        ctx.invoke(serve)


@main.command()
@click.option("--host", default=None, help="Bind host (overrides config)")
@click.option("--port", default=None, type=int, help="Bind port (overrides config)")
@click.option(
    "--token",
    default=None,
    envvar="KOTO_TOKEN",
    help="Auth token (or set KOTO_TOKEN, or [server].token in config)",
)
@click.option(
    "--db-path", default=None, help="Path to SQLite database (overrides config)"
)
@click.option(
    "--config",
    "config_path",
    default=None,
    envvar="KOTO_CONFIG",
    help="Path to config TOML (default: platform user config dir)",
)
def serve(
    host: str | None,
    port: int | None,
    token: str | None,
    db_path: str | None,
    config_path: str | None,
):
    if config_path:
        os.environ["KOTO_CONFIG"] = config_path
    if token:
        os.environ["KOTO_TOKEN"] = token
    if host:
        os.environ["KOTO_HOST"] = host
    if port:
        os.environ["KOTO_PORT"] = str(port)
    if db_path:
        os.environ["KOTO_DB_PATH"] = db_path

    from .config import settings

    if not settings.token:
        raise click.UsageError(
            "No token configured. Pass --token, set KOTO_TOKEN, "
            f"or set [server].token in {settings.config_path}"
        )

    uvicorn.run(
        "koto.app:create_app",
        host=settings.host,
        port=settings.port,
        factory=True,
    )


@main.command()
@click.option(
    "--server-url",
    default=None,
    envvar="KOTO_TUI_SERVER_URL",
    help="koto server URL (default: http://localhost:8080)",
)
@click.option(
    "--token",
    default=None,
    envvar="KOTO_TUI_TOKEN",
    help="Auth token (or set KOTO_TUI_TOKEN, or [tui].token in config)",
)
@click.option(
    "--config",
    "config_path",
    default=None,
    envvar="KOTO_CONFIG",
    help="Path to config TOML (default: platform user config dir)",
)
def tui(
    server_url: str | None,
    token: str | None,
    config_path: str | None,
):
    """Launch the Textual TUI client."""
    if config_path:
        os.environ["KOTO_CONFIG"] = config_path
    if server_url:
        os.environ["KOTO_TUI_SERVER_URL"] = server_url
    if token:
        os.environ["KOTO_TUI_TOKEN"] = token

    from .config import settings

    if not settings.tui_token:
        raise click.UsageError(
            "No token configured. Pass --token, set KOTO_TUI_TOKEN, "
            f"or set [tui].token in {settings.config_path}"
        )

    from .tui.app import KotoApp
    from .tui.client import KotoClient

    client = KotoClient(settings.tui_server_url, settings.tui_token)
    KotoApp(
        client=client,
        theme=settings.tui_theme,
        show_clock=settings.tui_show_clock,
        confirm_delete=settings.tui_confirm_delete,
        default_workspace_id=settings.tui_default_workspace_id,
    ).run()


if __name__ == "__main__":
    main()
