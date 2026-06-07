"""Pytest fixtures: per-test in-memory SQLite DB + FastAPI TestClient."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

# Set env BEFORE importing the app so settings pick it up.
TEST_TOKEN = "test-token"
os.environ.setdefault("KOTO_TOKEN", TEST_TOKEN)


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Iterator[str]:
    """A fresh on-disk SQLite file per test (in-memory doesn't play nice
    across separate engine connections)."""
    db = tmp_path / "koto-test.db"
    yield str(db)


@pytest.fixture
def configured_settings(tmp_db_path: str, monkeypatch: pytest.MonkeyPatch):
    """Force settings.token / db_path before app import or re-init."""
    monkeypatch.setenv("KOTO_TOKEN", TEST_TOKEN)
    monkeypatch.setenv("KOTO_DB_PATH", tmp_db_path)
    monkeypatch.setenv("KOTO_CONFIG", str(Path(tempfile.mkdtemp()) / "no-config.toml"))

    # Reload config and every module that imported `settings` eagerly,
    # so the new singleton is the one actually used at runtime.
    import importlib

    from koto import config as config_mod

    importlib.reload(config_mod)

    from koto import database as db_mod, auth as auth_mod, app as app_mod
    from koto.routes import workspaces as routes_ws, todos as routes_todos

    for mod in (db_mod, auth_mod, app_mod, routes_ws, routes_todos):
        if hasattr(mod, "settings"):
            mod.settings = config_mod.settings

    # Reset the engine so init_db picks up the new path.
    db_mod._engine = None
    db_mod._SessionLocal = None

    return config_mod.settings


@pytest.fixture
def client(configured_settings) -> Iterator[TestClient]:
    """A TestClient with the test DB initialized via the lifespan manager."""
    # Reset module-level engine/session.
    from koto import database as db_mod

    db_mod._engine = None
    db_mod._SessionLocal = None

    from koto.app import create_app

    app = create_app()
    with TestClient(app) as c:
        c.headers.update({"Authorization": f"Bearer {TEST_TOKEN}"})
        yield c


@pytest.fixture
def session(configured_settings):
    """Direct SQLAlchemy session for tests that touch models without HTTP."""
    from koto import database as db_mod
    from koto.database import init_db

    # Reset engine and re-init to fresh DB.
    db_mod._engine = None
    db_mod._SessionLocal = None
    init_db()
    sess = db_mod._SessionLocal()
    try:
        yield sess
    finally:
        sess.close()
