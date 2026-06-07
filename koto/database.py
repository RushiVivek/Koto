import threading
from typing import Generator

from sqlalchemy import create_engine, event as sa_event
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .models import Base

_write_lock = threading.Lock()
_engine = None
_SessionLocal = None


def init_db():
    global _engine, _SessionLocal
    _engine = create_engine(
        f"sqlite:///{settings.db_path}",
        connect_args={"check_same_thread": False},
    )

    @sa_event.listens_for(_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    Base.metadata.create_all(bind=_engine)
    _migrate_schema(_engine)
    _SessionLocal = sessionmaker(bind=_engine)

    with _SessionLocal() as session:
        from .models import Workspace

        root = session.query(Workspace).filter_by(is_root=True).first()
        if not root:
            session.add(Workspace(is_root=True, description="__root__"))
            session.commit()


def _migrate_schema(engine) -> None:
    """Apply lightweight migrations for columns added after first deploy.

    SQLAlchemy's `create_all` won't ALTER existing tables, so we add columns
    by hand if they're missing. Idempotent.
    """
    with engine.begin() as conn:
        cols = {
            row[1]
            for row in conn.exec_driver_sql("PRAGMA table_info(todo)").all()
        }
        if "recurrence_count" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE todo ADD COLUMN recurrence_count INTEGER NOT NULL DEFAULT 0"
            )


def get_session() -> Generator[Session, None, None]:
    if _SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_write_lock() -> threading.Lock:
    return _write_lock
