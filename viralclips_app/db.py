"""SQLAlchemy database setup and session management.

The database is a single local SQLite file. The worker process and the API
process share it, so the job queue survives an API restart and a browser
closing has no effect on processing.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config

config.ensure_dirs()

#: Per-thread session state. The API serves requests on a thread pool and
#: the worker runs its own thread, so the state has to be thread-local.
_state = threading.local()

engine = create_engine(
    config.DATABASE_URL,
    future=True,
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def _configure_sqlite(dbapi_connection, _record):
    """Enable WAL so the API and worker can read while one writes.

    Without this, SQLite locks the file and the worker blocks the API.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False,
                             future=True)


class Base(DeclarativeBase):
    """Declarative base for every model."""


def _sync_columns() -> None:
    """Add columns that exist in the models but not yet in the database.

    ``create_all()`` creates missing *tables* but never adds a column to
    a table that already exists. Without this, a newly added field would
    raise "no such column" on every query against an existing database.
    Only additive changes are applied; existing rows keep their data and
    the new column starts out NULL.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    # Iterate the raw table mapping rather than ``sorted_tables``: the
    # clips <-> jobs foreign keys form a cycle, so a topological sort
    # cannot be produced and SQLAlchemy emits a warning. Column
    # addition does not need an order.
    for table in Base.metadata.tables.values():
        if table.name not in existing_tables:
            continue
        present = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in present:
                continue
            ddl = column.type.compile(dialect=engine.dialect)
            statement = text(
                f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl}'
            )
            with engine.begin() as connection:
                connection.execute(statement)


def _backfill_defaults() -> None:
    """Fill in values for columns that were added to existing rows.

    ``ALTER TABLE ... ADD COLUMN`` leaves every pre-existing row with a
    NULL in the new column, even when the column has a default. The
    rows are still correct -- a NULL authorization state is read as
    "awaiting an authorised source" -- but an explicit value is clearer
    and survives a future change of default.

    Only rows whose value is NULL are touched. Nothing that was actually
    recorded is overwritten.
    """
    from sqlalchemy import text

    statements = [
        # A detected upload that predates the authorisation column was
        # never authorised, so it waits for an authorised source.
        ('UPDATE "episodes" SET "authorization_state" = \'awaiting_authorization\''
         ' WHERE "authorization_state" IS NULL'),
        ('UPDATE "episodes" SET "authorization_note" = \'\''
         ' WHERE "authorization_note" IS NULL'),
        # The intelligence columns are only meaningful for clips that were
        # analysed by the V2 layer; older clips keep a null source.
        ('UPDATE "clips" SET "score_kind" = \'estimated\''
         ' WHERE "score_kind" IS NULL'),
    ]
    for statement in statements:
        with engine.begin() as connection:
            connection.execute(text(statement))


def init_db() -> None:
    """Create any missing tables and columns. Safe to call on every startup."""
    from . import models  # noqa: F401  (import registers the models)
    Base.metadata.create_all(engine)
    _sync_columns()
    _backfill_defaults()


@contextmanager
def session_scope():
    """Session context manager that commits on success, rolls back on error.

    This is **reentrant**. When a session is already open on the current
    thread, the nested call reuses it instead of opening a second
    connection. That matters because SQLite allows only one writer at a
    time: a nested ``session_scope()`` that opened its own connection
    would block forever on the outer transaction's write lock, and the
    ``busy_timeout`` setting cannot break that deadlock because the
    outer transaction is waiting on the inner one to finish.

    Only the outermost scope commits or rolls back.
    """
    depth = getattr(_state, "depth", 0)
    if depth:
        # Nested use: share the session, do not commit yet.
        _state.depth = depth + 1
        try:
            yield _state.session
        except Exception:
            _state.failed = True
            raise
        finally:
            _state.depth -= 1
        return

    session = SessionLocal()
    _state.session = session
    _state.depth = 1
    _state.failed = False
    try:
        yield session
        if not _state.failed:
            session.commit()
        else:
            session.rollback()
    except Exception:
        session.rollback()
        raise
    finally:
        _state.depth = 0
        _state.session = None
        session.close()


def get_db():
    """FastAPI dependency yielding a database session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
