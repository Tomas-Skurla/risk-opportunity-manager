"""SQLite outbox operations for offline-first sync."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore, utc_iso
from riskapp_client.domain.scored_entity_fields import SCORED_ENTITY_OUTBOX_ALLOWED_KEYS
from riskapp_client.domain.sync_protocol import (
    FailureKind,
    acknowledged_version,
    strict_int,
)

STATUS_PENDING = "pending"
STATUS_RETRY = "retry"
STATUS_BLOCKED = "blocked"
# Changes the server has not acknowledged yet.
_OPEN_STATUSES = (STATUS_PENDING, STATUS_RETRY, STATUS_BLOCKED)
RETRY_DELAYS_SECONDS = (2, 5, 15, 60, 300)
# Every kind except transient blocks a change until the user acts.
BLOCKING_FAILURE_KINDS = set(FailureKind) - {FailureKind.TRANSIENT}

# SQL fragments interpolated below are assembled only from fixed clauses or
# generated "?" placeholders. All runtime values remain bound parameters.


def _create_may_exist_remotely(entry: sqlite3.Row | None) -> bool:
    """A sent create whose response was lost may already be version 1 remotely."""
    return bool(
        entry is not None
        and entry["op"] == "upsert"
        and (entry["base_version"] is not None or entry["last_attempt_at"])
    )


def _server_record(result: dict[str, Any]) -> dict[str, Any] | None:
    raw = result.get("server_record")
    return dict(raw) if isinstance(raw, dict) else None


@dataclass(frozen=True)
class PendingChange:
    """A pending change queued for server sync."""

    change_id: str
    entity: str
    op: str
    base_version: int | None
    record: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "change_id": self.change_id,
            "entity": self.entity,
            "op": self.op,
            "base_version": self.base_version,
            "record": self.record,
        }


class OutboxStore:
    """Outbox queue for changes to be pushed to the server."""

    def __init__(self, store: LocalStore) -> None:
        self._store = store

    @property
    def conn(self) -> sqlite3.Connection:
        """Expose sqlite connection for rare advanced usage."""
        return self._store.conn

    def _count_by_status(self, status: str, project_id: str | None = None) -> int:
        where = "status=?"
        params = [status]
        if project_id:
            where += " AND project_id=?"
            params.append(project_id)
        row = self.conn.execute(
            f"SELECT COUNT(*) AS c FROM outbox WHERE {where};",  # noqa: S608
            params,
        ).fetchone()
        return int(row["c"]) if row else 0

    def pending_count(self, project_id: str | None = None) -> int:
        where = "status IN (?, ?)"
        params: list[object] = [STATUS_PENDING, STATUS_RETRY]
        if project_id:
            where += " AND project_id=?"
            params.append(project_id)
        row = self.conn.execute(
            f"SELECT COUNT(*) AS c FROM outbox WHERE {where};",  # noqa: S608
            params,
        ).fetchone()
        return int(row["c"]) if row else 0

    def deferred_count(self, project_id: str | None = None) -> int:
        """Count transient failures waiting for their next retry."""
        return self._count_by_status(STATUS_RETRY, project_id)

    def blocked_count(self, project_id: str | None = None) -> int:
        """Count changes that are blocked due to sync errors/conflicts."""
        return self._count_by_status(STATUS_BLOCKED, project_id)

    def _count_blocked_kind(
        self, failure_kind: str, project_id: str | None = None
    ) -> int:
        where = "status=?"
        params: list[object] = [STATUS_BLOCKED]
        if failure_kind == "conflict":
            where += " AND failure_kind=?"
            params.append("conflict")
        else:
            # Rows created before failure_kind was introduced are sync errors
            # unless they were explicitly classified as conflicts.
            where += " AND failure_kind<>?"
            params.append("conflict")
        if project_id:
            where += " AND project_id=?"
            params.append(project_id)
        row = self.conn.execute(
            f"SELECT COUNT(*) AS c FROM outbox WHERE {where};",  # noqa: S608
            params,
        ).fetchone()
        return int(row["c"]) if row else 0

    def conflict_count(self, project_id: str | None = None) -> int:
        """Count blocked changes that need an explicit conflict decision."""
        return self._count_blocked_kind("conflict", project_id)

    def error_count(self, project_id: str | None = None) -> int:
        """Count blocked non-conflict synchronization errors."""
        return self._count_blocked_kind("error", project_id)

    def _safe_json_loads(self, raw: str | None) -> dict[str, Any]:
        """Best-effort decode of `last_error` payloads stored in the outbox."""
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except KeyError, TypeError, ValueError:
            return {"detail": str(raw)}
        return parsed if isinstance(parsed, dict) else {"detail": str(parsed)}

    def _blocked_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        """Decode one blocked outbox row without losing its saved outcome."""
        record = self._safe_json_loads(row["record_json"])
        outcome = self._safe_json_loads(row["result_json"])
        if not outcome:
            # Backwards compatibility for rows blocked before result_json was
            # added to the local schema.
            outcome = self._safe_json_loads(row["last_error"])
        title = (
            record.get("title")
            or record.get("name")
            or outcome.get("title")
            or outcome.get("name")
            or row["entity_id"]
        )
        return {
            "change_id": row["change_id"],
            "project_id": row["project_id"],
            "entity": row["entity"],
            "op": row["op"],
            "entity_id": row["entity_id"],
            "base_version": row["base_version"],
            "record": record,
            "title": str(title),
            "reason": str(
                outcome.get("reason")
                or outcome.get("message")
                or outcome.get("detail")
                or row["last_error"]
                or "Blocked by sync error"
            ),
            "server_version": outcome.get("server_version"),
            "server_record": outcome.get("server_record"),
            "server_updated_at": outcome.get("server_updated_at"),
            "failure_kind": str(row["failure_kind"] or "error"),
            "detail": outcome,
            "created_at": row["created_at"],
        }

    def get_blocked_change(self, change_id: str) -> dict[str, Any] | None:
        """Return one blocked change by its exact receipt ID."""
        row = self.conn.execute(
            """
            SELECT change_id, project_id, entity, op, entity_id, base_version,
                   record_json, last_error, failure_kind, result_json, created_at
            FROM outbox
            WHERE change_id=? AND status=?
            """,
            (str(change_id), STATUS_BLOCKED),
        ).fetchone()
        return self._blocked_row_to_dict(row) if row else None

    def get_blocked_changes(
        self, project_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return blocked changes with user-facing conflict/error details."""
        limit = max(1, min(int(limit), 1000))
        if project_id:
            rows = self.conn.execute(
                """
                SELECT change_id, project_id, entity, op, entity_id, base_version,
                       record_json, last_error, failure_kind, result_json, created_at
                FROM outbox
                WHERE project_id=? AND status=?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (project_id, STATUS_BLOCKED, int(limit)),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT change_id, project_id, entity, op, entity_id, base_version,
                       record_json, last_error, failure_kind, result_json, created_at
                FROM outbox
                WHERE status=?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (STATUS_BLOCKED, int(limit)),
            ).fetchall()

        return [self._blocked_row_to_dict(row) for row in rows]

    def _oldest_open_entry(
        self, project_id: str, entity: str, entity_id: str
    ) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT change_id, op, base_version, status, failure_kind,
                   last_attempt_at
            FROM outbox
            WHERE project_id=? AND entity=? AND entity_id=?
              AND status IN (?, ?, ?)
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (project_id, entity, str(entity_id), *_OPEN_STATUSES),
        ).fetchone()

    def _delete_open_entries(
        self, project_id: str, entity: str, entity_id: str
    ) -> None:
        self.conn.execute(
            "DELETE FROM outbox "
            "WHERE project_id=? AND entity=? AND entity_id=? "
            "AND status IN (?, ?, ?);",
            (project_id, entity, str(entity_id), *_OPEN_STATUSES),
        )

    def _replace_outbox_entry(
        self,
        *,
        project_id: str,
        entity: str,
        op: str,
        entity_id: str,
        base_version: int | None,
        record: dict[str, Any],
        force_rebase: bool = False,
    ) -> str:
        change_id = str(uuid.uuid4())
        record_json = json.dumps(record)
        # Squash and replacement are one transaction. This joins an active
        # service transaction so the domain row and outbox row commit together.
        with self._store.write_transaction():
            existing = (
                None
                if force_rebase
                else self._oldest_open_entry(project_id, entity, entity_id)
            )
            if (
                existing is not None
                and existing["status"] == STATUS_BLOCKED
                and existing["failure_kind"] == "conflict"
            ):
                # Editing the local copy does not resolve the conflict. Keep the
                # saved server outcome and receipt ID while refreshing "mine".
                self.conn.execute(
                    "UPDATE outbox SET op=?, record_json=? WHERE change_id=?;",
                    (op, record_json, existing["change_id"]),
                )
                return str(existing["change_id"])

            if existing is not None:
                # Squashing another local edit must retain the version on which
                # the first unacknowledged edit was based.
                base_version = existing["base_version"]
                if base_version is None and _create_may_exist_remotely(existing):
                    base_version = 1
            self._delete_open_entries(project_id, entity, entity_id)
            self.conn.execute(
                """
                INSERT INTO outbox (
                    change_id, project_id, entity, op, entity_id,
                    base_version, record_json, status, last_error, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', ?)
                """,
                (
                    change_id,
                    project_id,
                    entity,
                    op,
                    entity_id,
                    base_version,
                    record_json,
                    STATUS_PENDING,
                    utc_iso(),
                ),
            )
        return change_id

    def override_base_version(
        self,
        project_id: str,
        *,
        entity: str,
        entity_id: str,
        base_version: int | None,
    ) -> None:
        """Override base_version for the current queued change.

        This is mainly useful for conflict rebasing flows where the caller already
        knows the server_version to target and wants to avoid relying on the local
        row version.
        """
        if base_version is None:
            return
        try:
            bv_raw = int(base_version)
        except TypeError, ValueError:
            return
        bv: int | None = bv_raw if bv_raw >= 1 else None

        with self._store.write_transaction():
            self.conn.execute(
                "UPDATE outbox SET base_version=? WHERE project_id=? AND entity=? "
                "AND entity_id=? AND status IN (?, ?);",
                (
                    bv,
                    project_id,
                    entity,
                    str(entity_id),
                    STATUS_PENDING,
                    STATUS_RETRY,
                ),
            )

    def discard_entity_changes(
        self, project_id: str, *, entity: str, entity_id: str
    ) -> None:
        """Drop queued pending/blocked changes for one entity.

        Used when an entity was created locally and deleted before first sync:
        the correct remote net effect is no-op.
        """
        with self._store.write_transaction():
            self._delete_open_entries(project_id, entity, entity_id)

    def remote_create_may_exist(
        self, project_id: str, *, entity: str, entity_id: str
    ) -> bool:
        """Return whether a version-zero create may already exist remotely."""

        return _create_may_exist_remotely(
            self._oldest_open_entry(project_id, entity, entity_id)
        )

    def _queue_scored_upsert(
        self,
        project_id: str,
        *,
        entity: str,
        record: dict[str, Any],
        get_project_and_version: Callable[[str], tuple[str, int]],
    ) -> None:
        entity_id = str(record["id"])
        _, ver = get_project_and_version(entity_id)
        base_v = ver if ver >= 1 else None
        clean = {
            k: record.get(k) for k in SCORED_ENTITY_OUTBOX_ALLOWED_KEYS if k in record
        }
        clean["id"] = entity_id
        clean["title"] = str(clean.get("title") or "")
        clean["probability"] = int(clean.get("probability") or 1)
        clean["impact"] = int(clean.get("impact") or 1)
        self._replace_outbox_entry(
            project_id=project_id,
            entity=entity,
            op="upsert",
            entity_id=entity_id,
            base_version=base_v,
            record=clean,
        )

    def _queue_simple_upsert(
        self,
        project_id: str,
        *,
        entity: str,
        entity_id: str,
        record: dict[str, Any],
        get_project_and_version: Callable[[str], tuple[str, int]],
    ) -> None:
        _, ver = get_project_and_version(entity_id)
        base_v = ver if ver >= 1 else None
        self._replace_outbox_entry(
            project_id=project_id,
            entity=entity,
            op="upsert",
            entity_id=entity_id,
            base_version=base_v,
            record=record,
        )

    def queue_risk_upsert(self, project_id: str, record: dict[str, Any]) -> None:
        self._queue_scored_upsert(
            project_id,
            entity="risk",
            record=record,
            get_project_and_version=self._store.get_risk_project_and_version,
        )

    def _queue_delete(
        self,
        project_id: str,
        entity: str,
        entity_id: str,
        get_project_and_version: Callable,
    ) -> None:
        _, ver = get_project_and_version(entity_id)
        force_rebase = False
        if ver >= 1:
            base_v: int | None = ver
        elif self.remote_create_may_exist(
            project_id,
            entity=entity,
            entity_id=entity_id,
        ):
            # The create request crossed the send boundary. If its response was
            # lost, deleting it must target the version-one server row instead
            # of collapsing the local create/delete pair to a no-op.
            base_v = 1
            force_rebase = True
        else:
            self.discard_entity_changes(
                project_id,
                entity=entity,
                entity_id=entity_id,
            )
            return
        self._replace_outbox_entry(
            project_id=project_id,
            entity=entity,
            op="delete",
            entity_id=entity_id,
            base_version=base_v,
            record={"id": entity_id},
            force_rebase=force_rebase,
        )

    def queue_risk_delete(self, project_id: str, risk_id: str) -> None:
        self._queue_delete(
            project_id, "risk", risk_id, self._store.get_risk_project_and_version
        )

    def queue_opportunity_upsert(self, project_id: str, record: dict[str, Any]) -> None:
        self._queue_scored_upsert(
            project_id,
            entity="opportunity",
            record=record,
            get_project_and_version=self._store.get_opportunity_project_and_version,
        )

    def queue_opportunity_delete(self, project_id: str, opportunity_id: str) -> None:
        self._queue_delete(
            project_id,
            "opportunity",
            opportunity_id,
            self._store.get_opportunity_project_and_version,
        )

    def queue_action_upsert(
        self,
        action_id: str,
        project_id: str,
        **kwargs: Any,
    ) -> None:
        kwargs["id"] = action_id
        self._queue_simple_upsert(
            project_id,
            entity="action",
            entity_id=action_id,
            record=kwargs,
            get_project_and_version=self._store.get_action_project_and_version,
        )

    def queue_assessment_upsert(
        self,
        assessment_id: str,
        project_id: str,
        **kwargs: Any,
    ) -> None:
        kwargs["id"] = assessment_id
        self._queue_simple_upsert(
            project_id,
            entity="assessment",
            entity_id=assessment_id,
            record=kwargs,
            get_project_and_version=self._store.get_assessment_project_and_version,
        )

    def queue_helpdesk_upsert(
        self,
        ticket_id: str,
        project_id: str,
        **kwargs: Any,
    ) -> None:
        """Queue a help-desk ticket create-or-update for server sync."""
        kwargs["id"] = ticket_id
        self._queue_simple_upsert(
            project_id,
            entity="helpdesk_ticket",
            entity_id=ticket_id,
            record=kwargs,
            get_project_and_version=self._store.get_helpdesk_ticket_project_and_version,
        )

    def queue_helpdesk_delete(self, ticket_id: str, project_id: str) -> None:
        """Queue a help-desk ticket deletion for server sync."""
        self._queue_delete(
            project_id,
            "helpdesk_ticket",
            ticket_id,
            self._store.get_helpdesk_ticket_project_and_version,
        )

    def get_pending_changes(
        self,
        project_id: str,
        limit: int = 100,
        *,
        now: str | None = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        ready_at = str(now or utc_iso())
        rows = self.conn.execute(
            """
            SELECT change_id, entity, op, base_version, record_json
            FROM outbox
            WHERE project_id=?
              AND (
                    status=?
                    OR (
                        status=?
                        AND (next_retry_at='' OR next_retry_at<=?)
                    )
                  )
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (project_id, STATUS_PENDING, STATUS_RETRY, ready_at, int(limit)),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                PendingChange(
                    change_id=row["change_id"],
                    entity=row["entity"],
                    op=row["op"],
                    base_version=row["base_version"],
                    record=json.loads(row["record_json"]),
                ).as_dict()
            )
        return out

    def next_retry_at(self, project_id: str | None = None) -> str | None:
        """Return the earliest scheduled transient retry, if any."""
        where = "status=? AND next_retry_at<>''"
        params: list[object] = [STATUS_RETRY]
        if project_id:
            where += " AND project_id=?"
            params.append(project_id)
        row = self.conn.execute(
            f"SELECT MIN(next_retry_at) AS ts FROM outbox WHERE {where};",  # noqa: S608
            params,
        ).fetchone()
        return str(row["ts"]) if row and row["ts"] else None

    def delete_outbox_ids(self, change_ids: list[str]) -> None:
        if not change_ids:
            return
        q = ",".join(["?"] * len(change_ids))
        with self._store.write_transaction():
            self.conn.execute(
                f"DELETE FROM outbox WHERE change_id IN ({q});",  # noqa: S608
                change_ids,
            )

    def mark_outbox_ids_attempted(
        self, change_ids: list[str], *, attempted_at: str | None = None
    ) -> None:
        """Persist the send boundary before performing the network request."""
        ids = [str(change_id) for change_id in change_ids if change_id]
        if not ids:
            return
        q = ",".join(["?"] * len(ids))
        timestamp = str(attempted_at or utc_iso())
        with self._store.write_transaction():
            self.conn.execute(
                f"UPDATE outbox SET last_attempt_at=? "  # noqa: S608
                f"WHERE change_id IN ({q});",
                [timestamp, *ids],
            )

    def acknowledge_accepted_results(
        self,
        project_id: str,
        results: list[dict[str, Any]],
    ) -> int:
        """Atomically apply accepted server rows and remove their outbox entries."""
        acknowledged = 0
        with self._store.write_transaction():
            self._store.release_scored_codes_for_acknowledgements(
                project_id,
                results,
            )
            for result in results:
                change_id = str(result.get("change_id") or "")
                if not change_id or result.get("status") != "accepted":
                    continue
                sent = self.conn.execute(
                    """
                    SELECT entity, entity_id
                    FROM outbox
                    WHERE change_id=? AND project_id=?
                    """,
                    (change_id, project_id),
                ).fetchone()
                if sent is not None:
                    self._acknowledge_sent(project_id, change_id, sent, result)
                elif not self._advance_replacement(project_id, result):
                    continue
                acknowledged += 1
        return acknowledged

    def _acknowledge_sent(
        self,
        project_id: str,
        change_id: str,
        sent: sqlite3.Row,
        result: dict[str, Any],
    ) -> None:
        """Apply the server row for a receipt that is still queued, then drop it."""
        entity = str(sent["entity"])
        entity_id = str(sent["entity_id"])
        if str(result.get("entity") or "") not in {"", entity} or str(
            result.get("entity_id") or ""
        ) not in {"", entity_id}:
            raise RuntimeError("Push acknowledgement does not match outbox")
        self.conn.execute("DELETE FROM outbox WHERE change_id=?;", (change_id,))
        self._store.apply_push_acknowledgement(
            project_id,
            entity=entity,
            entity_id=entity_id,
            server_version=strict_int(result.get("server_version")),
            server_record=_server_record(result),
        )

    def _advance_replacement(self, project_id: str, result: dict[str, Any]) -> bool:
        """Rebase the newer local edit that replaced an acknowledged receipt.

        The result still advances that replacement's base version, but must
        never overwrite its editable field values.
        """
        entity = str(result.get("entity") or "")
        entity_id = str(result.get("entity_id") or "")
        if not entity or not entity_id:
            return False
        replacement = self.conn.execute(
            """
            SELECT change_id, base_version, record_json
            FROM outbox
            WHERE project_id=? AND entity=? AND entity_id=?
              AND status IN (?, ?)
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (project_id, entity, entity_id, STATUS_PENDING, STATUS_RETRY),
        ).fetchone()
        if replacement is None:
            return False
        server_version = strict_int(result.get("server_version"))
        server_record = _server_record(result)
        version = acknowledged_version(result)
        record = self._safe_json_loads(replacement["record_json"])
        if (
            entity in {"risk", "opportunity"}
            and server_record is not None
            and "code" in server_record
        ):
            record["code"] = server_record.get("code")
        base_version = max(int(replacement["base_version"] or 0), int(version or 0))
        self.conn.execute(
            "UPDATE outbox SET base_version=?, record_json=? WHERE change_id=?;",
            (base_version or None, json.dumps(record), replacement["change_id"]),
        )
        if (
            result.get("replayed")
            and version != server_version
            and server_record is not None
        ):
            # A replay's current row may hold later edits; keep only identity.
            server_record = {
                key: server_record[key]
                for key in ("id", "project_id", "code")
                if key in server_record
            }
        self._store.advance_push_acknowledgement(
            project_id,
            entity=entity,
            entity_id=entity_id,
            server_version=version,
            server_record=server_record,
        )
        return True

    def _encode_failure(
        self, err: str | dict[str, Any]
    ) -> tuple[dict[str, Any], str, str]:
        outcome = dict(err) if isinstance(err, dict) else self._safe_json_loads(err)
        result_json = json.dumps(outcome, default=str, separators=(",", ":"))
        summary = str(
            outcome.get("reason")
            or outcome.get("message")
            or outcome.get("detail")
            or err
        )
        return outcome, result_json, summary

    def defer_outbox_id(
        self,
        change_id: str,
        err: str | dict[str, Any],
        *,
        retry_after_seconds: int | None = None,
        now: datetime | None = None,
    ) -> str | None:
        """Schedule a transient failure using bounded exponential backoff."""
        outcome, result_json, summary = self._encode_failure(err)
        now_value = now or datetime.now(UTC)
        if now_value.tzinfo is None:
            now_value = now_value.replace(tzinfo=UTC)
        now_dt = now_value.astimezone(UTC).replace(tzinfo=None)
        with self._store.write_transaction():
            row = self.conn.execute(
                "SELECT retry_count FROM outbox WHERE change_id=?;", (change_id,)
            ).fetchone()
            if not row:
                return None
            attempt = int(row["retry_count"] or 0) + 1
            if retry_after_seconds is None:
                delay = RETRY_DELAYS_SECONDS[
                    min(attempt - 1, len(RETRY_DELAYS_SECONDS) - 1)
                ]
            else:
                delay = max(0, min(int(retry_after_seconds), 86_400))
            attempted_at = now_dt.isoformat()
            retry_at = (now_dt + timedelta(seconds=delay)).isoformat()
            failure_kind = str(outcome.get("failure_kind") or "transient")
            self.conn.execute(
                """
                UPDATE outbox
                SET status=?, last_error=?, failure_kind=?, result_json=?,
                    retry_count=?, next_retry_at=?, last_attempt_at=?
                WHERE change_id=?;
                """,
                (
                    STATUS_RETRY,
                    summary[:500],
                    failure_kind,
                    result_json,
                    attempt,
                    retry_at,
                    attempted_at,
                    change_id,
                ),
            )
        return retry_at

    def release_authentication_blocks(self, project_id: str | None = None) -> int:
        """Make login-blocked writes eligible after a new authenticated session."""
        project_clause = " AND project_id=?" if project_id else ""
        params: list[object] = [STATUS_PENDING, STATUS_BLOCKED]
        if project_id:
            params.append(project_id)
        with self._store.write_transaction():
            result = self.conn.execute(
                f"""
                UPDATE outbox
                SET status=?, next_retry_at=''
                WHERE status=? AND failure_kind='authentication'{project_clause};
                """,  # noqa: S608
                params,
            )
        return int(result.rowcount or 0)

    def block_outbox_id(
        self,
        change_id: str,
        err: str | dict[str, Any],
        *,
        failure_kind: str = "error",
    ) -> None:
        if failure_kind not in BLOCKING_FAILURE_KINDS:
            raise ValueError(f"Unknown outbox failure kind: {failure_kind!r}")
        _outcome, result_json, summary = self._encode_failure(err)
        attempted_at = datetime.now(UTC).replace(tzinfo=None).isoformat()
        with self._store.write_transaction():
            self.conn.execute(
                "UPDATE outbox SET status=?, last_error=?, failure_kind=?, "
                "result_json=?, next_retry_at='', last_attempt_at=? WHERE change_id=?;",
                (
                    STATUS_BLOCKED,
                    summary[:500],
                    failure_kind,
                    result_json,
                    attempted_at,
                    change_id,
                ),
            )

    def requeue_conflict_with_new_id(
        self, change_id: str, server_version: int
    ) -> str | None:
        row = self.conn.execute(
            "SELECT * FROM outbox WHERE change_id=?;", (change_id,)
        ).fetchone()
        if not row:
            return None
        project_id = row["project_id"]
        entity = row["entity"]
        op = row["op"]
        entity_id = row["entity_id"]
        record = json.loads(row["record_json"])
        # _replace_outbox_entry deletes the old row and inserts its replacement
        # atomically, so a failed insert cannot drop the queued user change.
        return self._replace_outbox_entry(
            project_id=project_id,
            entity=entity,
            op=op,
            entity_id=entity_id,
            base_version=int(server_version),
            record=record,
            force_rebase=True,
        )

    def queue_merged_upsert(
        self,
        project_id: str,
        entity: str,
        entity_id: str,
        server_version: int,
        record: dict[str, Any],
    ) -> str:
        """Queue a new receipt ID for an explicit server-based field merge."""
        return self._replace_outbox_entry(
            project_id=project_id,
            entity=entity,
            op="upsert",
            entity_id=entity_id,
            base_version=server_version,
            record=record,
            force_rebase=True,
        )
