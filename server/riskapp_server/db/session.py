"""Database engine, session factory, and request-scoped sessions.

ORM models live in ``riskapp_server.db.models``; they are re-exported here so
existing ``from riskapp_server.db.session import Item`` imports keep working.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from riskapp_server.core.config import (
    AUTO_CREATE_SCHEMA,
    DATABASE_URL,
    DB_MAX_OVERFLOW,
    DB_POOL_RECYCLE,
    DB_POOL_SIZE,
    DB_STATEMENT_TIMEOUT_MS,
)
from riskapp_server.db.models import (
    Action,
    ActionKind,
    ActionStatus,
    Assessment,
    AuditLog,
    Base,
    HelpDeskCategory,
    HelpDeskPriority,
    HelpDeskStatus,
    HelpDeskTicket,
    Item,
    PasswordResetToken,
    Project,
    ProjectMember,
    RefreshToken,
    RiskStatus,
    Role,
    ScoreSnapshot,
    SyncProjectState,
    SyncReceipt,
    User,
    utcnow,
)

__all__ = [
    "Action",
    "ActionKind",
    "ActionStatus",
    "Assessment",
    "AuditLog",
    "Base",
    "HelpDeskCategory",
    "HelpDeskPriority",
    "HelpDeskStatus",
    "HelpDeskTicket",
    "Item",
    "PasswordResetToken",
    "Project",
    "ProjectMember",
    "RefreshToken",
    "RiskStatus",
    "Role",
    "ScoreSnapshot",
    "SyncProjectState",
    "SyncReceipt",
    "User",
    "utcnow",
    "SessionLocal",
    "create_db_engine",
    "engine",
    "get_db",
    "init_db",
]


def _enable_sqlite_foreign_keys(dbapi_conn: Any, _: Any) -> None:
    """Enable SQLite foreign-key enforcement for each connection."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _set_statement_timeout(dbapi_conn: Any, _: Any) -> None:
    """Apply the PostgreSQL statement timeout to each new connection."""
    cur = dbapi_conn.cursor()
    cur.execute("SET statement_timeout = %s", (int(DB_STATEMENT_TIMEOUT_MS),))
    cur.close()


def create_db_engine(url: str) -> Engine:
    """Create the engine for ``url`` with RiskApp's connection settings."""
    kwargs: dict[str, Any] = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        # SQLite needs this with the FastAPI/Uvicorn threading model.
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs.update(
            {
                "pool_recycle": DB_POOL_RECYCLE,
                "pool_size": DB_POOL_SIZE,
                "max_overflow": DB_MAX_OVERFLOW,
            }
        )
        if DB_STATEMENT_TIMEOUT_MS and "postgresql" in url:
            kwargs.setdefault("connect_args", {})
            kwargs["connect_args"].update(
                {"options": f"-c statement_timeout={DB_STATEMENT_TIMEOUT_MS}"}
            )

    new_engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        event.listen(new_engine, "connect", _enable_sqlite_foreign_keys)
    if "postgresql" in url and DB_STATEMENT_TIMEOUT_MS:
        event.listen(new_engine, "connect", _set_statement_timeout)
    return new_engine


engine = create_db_engine(DATABASE_URL)


# Keep ORM objects usable after commit in request handlers.
SessionLocal = sessionmaker(  # pylint: disable=invalid-name
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    # Handy for local runs; deployments should use migrations instead.
    if AUTO_CREATE_SCHEMA:
        Base.metadata.create_all(bind=engine)
