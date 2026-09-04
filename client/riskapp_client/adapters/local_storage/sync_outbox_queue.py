"""SQLite outbox operations for offline-first sync."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore, utc_iso
from riskapp_client.domain.scored_entity_fields import SCORED_ENTITY_OUTBOX_ALLOWED_KEYS

STATUS_PENDING = "pending"
STATUS_BLOCKED = "blocked"


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
            f"SELECT COUNT(*) AS c FROM outbox WHERE {where};", params
        ).fetchone()
        return int(row["c"]) if row else 0

    def pending_count(self, project_id: str | None = None) -> int:
        return self._count_by_status(STATUS_PENDING, project_id)

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
            f"SELECT COUNT(*) AS c FROM outbox WHERE {where};", params
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
        except (KeyError, TypeError, ValueError):
            return {"detail": str(raw)}
        return parsed if isinstance(parsed, dict) else {"detail": str(parsed)}

    def get_blocked_changes(
        self, project_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return blocked changes with user-facing conflict/error details."""
        limit = max(1, min(int(limit), 1000))
        if project_id:
            rows = self.conn.execute(
                """
                SELECT change_id, entity, op, entity_id, base_version, record_json,
                       last_error, failure_kind
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
                SELECT change_id, entity, op, entity_id, base_version, record_json,
                       last_error, failure_kind
                FROM outbox
                WHERE status=?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (STATUS_BLOCKED, int(limit)),
            ).fetchall()

        out: list[dict[str, Any]] = []
        for row in rows:
            record = self._safe_json_loads(row["record_json"])
            err = self._safe_json_loads(row["last_error"])
            title = (
                record.get("title")
                or record.get("name")
                or err.get("title")
                or err.get("name")
                or row["entity_id"]
            )
            out.append(
                {
                    "change_id": row["change_id"],
                    "entity": row["entity"],
                    "op": row["op"],
                    "entity_id": row["entity_id"],
                    "base_version": row["base_version"],
                    "record": record,
                    "title": str(title),
                    "reason": str(
                        err.get("reason")
                        or err.get("message")
                        or err.get("detail")
                        or row["last_error"]
                        or "Blocked by sync error"
                    ),
                    "server_version": err.get("server_version"),
                    "failure_kind": str(row["failure_kind"] or "error"),
                    "detail": err,
                }
            )
        return out

    def _replace_outbox_entry(
        self,
        *,
        project_id: str,
        entity: str,
        op: str,
        entity_id: str,
        base_version: int | None,
        record: dict[str, Any],
    ) -> str:
        change_id = str(uuid.uuid4())
        record_json = json.dumps(record)
        # Squash and replacement are one transaction. If serialization or insert
        # fails, the existing offline change remains intact.
        with self.conn:
            cur = self.conn.cursor()
            cur.execute(
                "DELETE FROM outbox "
                "WHERE project_id=? AND entity=? AND entity_id=? "
                "AND status IN (?, ?);",
                (project_id, entity, entity_id, STATUS_PENDING, STATUS_BLOCKED),
            )
            cur.execute(
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
        except (TypeError, ValueError):
            return
        bv: int | None = bv_raw if bv_raw >= 1 else None

        self.conn.execute(
            "UPDATE outbox SET base_version=? WHERE project_id=? AND entity=? AND entity_id=? AND status IN (?, ?);",
            (bv, project_id, entity, str(entity_id), STATUS_PENDING, STATUS_BLOCKED),
        )
        self.conn.commit()

    def discard_entity_changes(
        self, project_id: str, *, entity: str, entity_id: str
    ) -> None:
        """Drop queued pending/blocked changes for one entity.

        Used when an entity was created locally and deleted before first sync:
        the correct remote net effect is no-op.
        """
        self.conn.execute(
            """
            DELETE FROM outbox
            WHERE project_id=? AND entity=? AND entity_id=? AND status IN (?, ?);
            """,
            (project_id, entity, str(entity_id), STATUS_PENDING, STATUS_BLOCKED),
        )
        self.conn.commit()

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
        base_v = ver if ver >= 1 else None
        self._replace_outbox_entry(
            project_id=project_id,
            entity=entity,
            op="delete",
            entity_id=entity_id,
            base_version=base_v,
            record={"id": entity_id},
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
        self, project_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        rows = self.conn.execute(
            """
            SELECT change_id, entity, op, base_version, record_json
            FROM outbox
            WHERE project_id=? AND status=?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (project_id, STATUS_PENDING, int(limit)),
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

    def delete_outbox_ids(self, change_ids: list[str]) -> None:
        if not change_ids:
            return
        q = ",".join(["?"] * len(change_ids))
        self.conn.execute(f"DELETE FROM outbox WHERE change_id IN ({q});", change_ids)
        self.conn.commit()

    def block_outbox_id(
        self, change_id: str, err: str, *, failure_kind: str = "error"
    ) -> None:
        if failure_kind not in {"conflict", "error"}:
            raise ValueError(f"Unknown outbox failure kind: {failure_kind!r}")
        self.conn.execute(
            "UPDATE outbox SET status=?, last_error=?, failure_kind=? "
            "WHERE change_id=?;",
            (STATUS_BLOCKED, err[:500], failure_kind, change_id),
        )
        self.conn.commit()

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
        )
