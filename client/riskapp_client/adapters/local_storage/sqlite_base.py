"""SQLite connection, transactions and helpers shared by the LocalStore parts."""

from __future__ import annotations

import contextlib
import os
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Self

from riskapp_client.adapters.local_storage.schema import check_identifier, ensure_schema
from riskapp_client.domain.scored_entity_fields import (
    SCORED_ENTITY_META_KEYS,
    SCORED_ENTITY_META_SQLITE_COLUMNS,
)

_VALID_TABLES: set[str] = {
    "risks",
    "opportunities",
    "actions",
    "assessments",
    "projects",
    "outbox",
    "sync_state",
    "meta",
    "helpdesk_tickets",
}

_VALID_SCORED_TABLES: set[str] = {"risks", "opportunities"}

_TEXT_META_KEYS: set[str] = {
    name
    for name, col_type in SCORED_ENTITY_META_SQLITE_COLUMNS
    if str(col_type).upper().startswith("TEXT")
}
_INT_META_KEYS: set[str] = {
    name
    for name, col_type in SCORED_ENTITY_META_SQLITE_COLUMNS
    if str(col_type).upper().startswith("INTEGER")
}


# sqlite3 can bind values but not identifiers. Dynamic identifiers in this
# package are allow-listed or checked; every user value remains a parameter.


def check_table(table: str) -> str:
    """Validate a table name."""
    if table not in _VALID_TABLES:
        raise ValueError(f"Unknown table name: {table!r}")
    return table


def utc_iso() -> str:
    """Return a naive UTC ISO timestamp."""
    return datetime.now(UTC).replace(tzinfo=None).isoformat()


def norm_text(v: str | None) -> str | None:
    """Strip text and convert empty strings to None."""
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def assert_scored_table(table: str) -> None:
    """Reject any table except the two scored-entity tables."""
    if table not in _VALID_SCORED_TABLES:
        raise ValueError(f"Invalid scored-entity table: {table!r}")


def norm_scored_meta(meta: dict[str, Any]) -> dict[str, Any]:
    """Return every optional risk/opportunity field, trimmed or converted to int."""
    out: dict[str, Any] = {}
    for k in SCORED_ENTITY_META_KEYS:
        v = meta.get(k)
        if k in _TEXT_META_KEYS:
            out[k] = norm_text(v)
        elif k in _INT_META_KEYS:
            out[k] = int(v) if v is not None else None
        else:
            out[k] = v
    return out


class SqliteStoreBase:
    """Own one SQLite connection and the nest-aware write transaction."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
            with contextlib.suppress(OSError):
                os.chmod(db_dir, 0o700)
        # Reduce transient "database is locked" errors in WAL mode.
        self.conn = sqlite3.connect(self.db_path, timeout=5.0)
        self.conn.row_factory = sqlite3.Row
        self._write_depth = 0
        self._rollback_only = False
        # Cached project data should remain private even when opening a DB that
        # was created by an older version with permissive mode bits.
        if os.path.exists(db_path):
            with contextlib.suppress(OSError):
                os.chmod(db_path, 0o600)
        self._init_schema()

    def close(self) -> None:
        with contextlib.suppress(OSError, sqlite3.Error):
            self.conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        """Release resources when leaving the context manager."""
        self.close()

    def _init_schema(self) -> None:
        ensure_schema(self.conn)

    @contextlib.contextmanager
    def write_transaction(self) -> Iterator[sqlite3.Connection]:
        """Run local writes in one nest-aware SQLite transaction.

        Service methods own the outer transaction. Lower-level store and outbox
        methods may safely join it; their normal commits are deferred until the
        outermost context exits. A failed nested operation marks the whole unit
        of work for rollback, even if an intermediate caller catches the error.
        """
        outermost = self._write_depth == 0
        if outermost:
            if self.conn.in_transaction:
                raise RuntimeError(
                    "SQLite transaction was started outside LocalStore.write_transaction"
                )
            self.conn.execute("BEGIN IMMEDIATE;")
            self._rollback_only = False

        self._write_depth += 1
        try:
            yield self.conn
        except BaseException:
            self._rollback_only = True
            if outermost:
                self.conn.rollback()
            raise
        else:
            if outermost:
                if self._rollback_only:
                    self.conn.rollback()
                    raise RuntimeError(
                        "Nested local write failed; transaction rolled back"
                    )
                try:
                    self.conn.commit()
                except BaseException:
                    self.conn.rollback()
                    raise
        finally:
            self._write_depth -= 1
            if outermost:
                self._rollback_only = False

    def _commit_if_needed(self) -> None:
        """Commit a standalone write, or defer to the active service transaction."""
        if self._write_depth == 0:
            self.conn.commit()

    def _upsert_row(
        self, table: str, record: dict[str, Any], cur: Any = None, pk: str = "id"
    ) -> None:
        """Insert or update a row."""
        check_table(table)
        cols = list(record.keys())
        for identifier in (*cols, pk):
            check_identifier(identifier)
        placeholders = ", ".join(["?"] * len(cols))
        set_clause = ", ".join([f"{c}=excluded.{c}" for c in cols if c != pk])
        if set_clause:
            sql = (
                f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders}) "  # noqa: S608
                f"ON CONFLICT({pk}) DO UPDATE SET {set_clause}"
            )
        else:
            sql = (
                f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders}) "  # noqa: S608
                f"ON CONFLICT({pk}) DO NOTHING"
            )
        (cur or self.conn).execute(sql, tuple(record[c] for c in cols))
