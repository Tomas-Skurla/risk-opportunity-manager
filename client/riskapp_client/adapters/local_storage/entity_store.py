"""Local edits to risks, opportunities, actions, assessments and tickets."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any, TypeVar, cast

from riskapp_client.adapters.local_storage.sqlite_base import (
    SqliteStoreBase,
    assert_scored_table,
    norm_scored_meta,
    norm_text,
    utc_iso,
)
from riskapp_client.adapters.mappers.action_assessment_mapper import (
    action_from_mapping,
    assessment_from_mapping,
)
from riskapp_client.adapters.mappers.scored_entity_mapper import (
    scored_entity_from_mapping,
)
from riskapp_client.domain.domain_models import (
    Action,
    Assessment,
    HelpDeskTicket,
    Opportunity,
    Risk,
)
from riskapp_client.domain.scored_entity_fields import SCORED_ENTITY_DB_COLUMNS

ModelT = TypeVar("ModelT")


def _value_or_existing[ValueT](
    value: ValueT | None,
    existing: sqlite3.Row | None,
    key: str,
    default: ValueT,
) -> ValueT:
    """Prefer an explicit value, then an existing SQLite value, then a default."""
    if value is not None:
        return value
    if existing is None:
        return default
    # Quoted so the type parameter is not evaluated at runtime.
    return cast("ValueT", existing[key])


class EntityStoreMixin(SqliteStoreBase):
    """Read and write the user's local copy of each project item."""

    def list_actions(self, project_id: str) -> list[Action]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM actions
            WHERE project_id=? AND is_deleted=0
            ORDER BY updated_at DESC, title ASC
            """,
            (project_id,),
        ).fetchall()
        return [action_from_mapping(r) for r in rows]

    def _get_action_row(self, action_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM actions WHERE id=?;", (action_id,)
        ).fetchone()

    def get_action_project_and_version(self, action_id: str) -> tuple[str, int]:
        r = self._get_action_row(action_id)
        if not r:
            raise KeyError("action not found in local store")
        return str(r["project_id"]), int(r["version"])

    def upsert_local_action(
        self,
        *,
        action_id: str,
        project_id: str,
        risk_id: str | None,
        opportunity_id: str | None,
        kind: str,
        title: str,
        description: str,
        status: str,
        owner_user_id: str | None,
        version: int | None = None,
        is_deleted: bool | None = None,
        updated_at: str | None = None,
        dirty: int = 1,
    ) -> None:
        existing = self._get_action_row(action_id)

        self._upsert_row(
            "actions",
            {
                "id": action_id,
                "project_id": project_id,
                "risk_id": risk_id,
                "opportunity_id": opportunity_id,
                "kind": kind,
                "title": title,
                "description": description or "",
                "status": status or "open",
                "owner_user_id": owner_user_id,
                "version": int(_value_or_existing(version, existing, "version", 0)),
                "is_deleted": int(
                    _value_or_existing(is_deleted, existing, "is_deleted", False)
                ),
                "updated_at": str(
                    _value_or_existing(updated_at, existing, "updated_at", "")
                ),
                "dirty": int(dirty),
            },
        )
        self._commit_if_needed()

    def _next_code(self, project_id: str, *, table: str, prefix: str) -> str:
        """Local code generator (for example R-001 or O-001)."""
        assert_scored_table(table)
        like = f"{prefix}-%"
        rows = self.conn.execute(
            f"SELECT code FROM {table} WHERE project_id=? AND code LIKE ? AND code IS NOT NULL;",  # noqa: S608
            (project_id, like),
        ).fetchall()
        max_n = 0
        for r in rows:
            c = norm_text(r["code"])
            if not c:
                continue
            parts = c.split("-", 2)
            if len(parts) < 2:
                continue
            if parts[0].strip().upper() != prefix.upper():
                continue
            num_part = parts[1].strip()
            if num_part.isdigit():
                max_n = max(max_n, int(num_part))
        return f"{prefix}-{max_n + 1:03d}"

    def next_risk_code(self, project_id: str) -> str:
        return self._next_code(project_id, table="risks", prefix="R")

    def next_opportunity_code(self, project_id: str) -> str:
        return self._next_code(project_id, table="opportunities", prefix="O")

    def _list_scored_entities(
        self, project_id: str, *, table: str, model_cls: type[ModelT]
    ) -> list[ModelT]:
        assert_scored_table(table)
        cols = ", ".join(SCORED_ENTITY_DB_COLUMNS)
        rows = self.conn.execute(
            f"""
            SELECT {cols}
            FROM {table}
            WHERE project_id=? AND is_deleted=0
            ORDER BY (probability*impact) DESC, title ASC
            """,  # noqa: S608
            (project_id,),
        ).fetchall()
        return [scored_entity_from_mapping(r, model_cls=model_cls) for r in rows]

    def _get_scored_row(self, table: str, entity_id: str) -> sqlite3.Row | None:
        assert_scored_table(table)
        return self.conn.execute(
            f"SELECT * FROM {table} WHERE id=?;",  # noqa: S608
            (entity_id,),
        ).fetchone()

    def _get_scored_project_and_version(
        self, table: str, entity_id: str, *, label: str
    ) -> tuple[str, int]:
        row = self._get_scored_row(table, entity_id)
        if not row:
            raise KeyError(f"{label} not found in local store")
        return str(row["project_id"]), int(row["version"])

    def _soft_delete_scored(
        self, table: str, entity_id: str, *, label: str
    ) -> tuple[str, int]:
        row = self._get_scored_row(table, entity_id)
        if not row:
            raise KeyError(f"{label} not found in local store")
        project_id = str(row["project_id"])
        version = int(row["version"] or 0)
        self.conn.execute(
            f"UPDATE {table} SET is_deleted=1, dirty=1, updated_at=? WHERE id=?;",  # noqa: S608
            (utc_iso(), entity_id),
        )
        self._commit_if_needed()
        return project_id, version

    def _upsert_local_scored(
        self,
        *,
        table: str,
        entity_id: str,
        project_id: str,
        title: str,
        probability: int,
        impact: int,
        meta: dict[str, Any],
        version: int | None,
        is_deleted: bool | None,
        updated_at: str | None,
        dirty: int,
    ) -> None:
        existing = self._get_scored_row(table, entity_id)

        v = int(_value_or_existing(version, existing, "version", 0))
        is_del = int(_value_or_existing(is_deleted, existing, "is_deleted", False))
        upd = str(_value_or_existing(updated_at, existing, "updated_at", ""))

        m = norm_scored_meta(meta)
        if not m.get("status"):
            m["status"] = "concept"
        dims = [
            m.get("impact_cost"),
            m.get("impact_time"),
            m.get("impact_scope"),
            m.get("impact_quality"),
        ]
        valid_dims = [int(x) for x in dims if x is not None]
        if valid_dims:
            impact = max(valid_dims)
        record: dict[str, Any] = {
            "id": entity_id,
            "project_id": project_id,
            "title": str(title or ""),
            "probability": int(probability),
            "impact": int(impact),
            **m,
            "version": v,
            "is_deleted": is_del,
            "updated_at": upd,
            "dirty": int(dirty),
        }
        self._upsert_row(table, record)
        self._commit_if_needed()

    def list_risks(self, project_id: str) -> list[Risk]:
        return self._list_scored_entities(project_id, table="risks", model_cls=Risk)

    def get_risk_row(self, risk_id: str) -> sqlite3.Row | None:
        return self._get_scored_row("risks", risk_id)

    def get_risk_project_and_version(self, risk_id: str) -> tuple[str, int]:
        return self._get_scored_project_and_version("risks", risk_id, label="risk")

    def upsert_local_risk(
        self,
        *,
        risk_id: str,
        project_id: str,
        title: str,
        probability: int,
        impact: int,
        version: int | None = None,
        is_deleted: bool | None = None,
        updated_at: str | None = None,
        dirty: int = 1,
        **meta: Any,
    ) -> None:
        self._upsert_local_scored(
            table="risks",
            entity_id=risk_id,
            project_id=project_id,
            title=title,
            probability=probability,
            impact=impact,
            meta=meta,
            version=version,
            is_deleted=is_deleted,
            updated_at=updated_at,
            dirty=dirty,
        )

    def soft_delete_risk(self, risk_id: str) -> tuple[str, int]:
        return self._soft_delete_scored("risks", risk_id, label="risk")

    def list_opportunities(self, project_id: str) -> list[Opportunity]:
        return self._list_scored_entities(
            project_id, table="opportunities", model_cls=Opportunity
        )

    def get_opportunity_row(self, opportunity_id: str) -> sqlite3.Row | None:
        return self._get_scored_row("opportunities", opportunity_id)

    def get_opportunity_project_and_version(
        self, opportunity_id: str
    ) -> tuple[str, int]:
        return self._get_scored_project_and_version(
            "opportunities", opportunity_id, label="opportunity"
        )

    def upsert_local_opportunity(
        self,
        *,
        opportunity_id: str,
        project_id: str,
        title: str,
        probability: int,
        impact: int,
        version: int | None = None,
        is_deleted: bool | None = None,
        updated_at: str | None = None,
        dirty: int = 1,
        **meta: Any,
    ) -> None:
        self._upsert_local_scored(
            table="opportunities",
            entity_id=opportunity_id,
            project_id=project_id,
            title=title,
            probability=probability,
            impact=impact,
            meta=meta,
            version=version,
            is_deleted=is_deleted,
            updated_at=updated_at,
            dirty=dirty,
        )

    def soft_delete_opportunity(self, opportunity_id: str) -> tuple[str, int]:
        return self._soft_delete_scored(
            "opportunities", opportunity_id, label="opportunity"
        )

    def list_assessments(
        self, project_id: str, item_type: str, item_id: str
    ) -> list[Assessment]:
        rows = self.conn.execute(
            """
            SELECT * FROM assessments
            WHERE project_id=? AND is_deleted=0 AND item_type=?
                AND (item_id=? OR risk_id=? OR opportunity_id=?)
            ORDER BY updated_at DESC
            """,
            (project_id, item_type, item_id, item_id, item_id),
        ).fetchall()
        return [assessment_from_mapping(r) for r in rows]

    def get_assessment_project_and_version(self, assessment_id: str) -> tuple[str, int]:
        row = self.conn.execute(
            "SELECT project_id, version FROM assessments WHERE id=?;",
            (assessment_id,),
        ).fetchone()
        if not row:
            raise KeyError("assessment not found in local store")
        return (str(row["project_id"]), int(row["version"]))

    def upsert_local_assessment(
        self,
        *,
        assessment_id: str,
        project_id: str,
        item_type: str,
        item_id: str,
        assessor_user_id: str,
        probability: int,
        impact: int,
        notes: str | None,
        version: int,
        is_deleted: bool,
        updated_at: str,
        dirty: int,
    ) -> None:
        score = int(probability) * int(impact)
        itype = str(item_type or "risk").strip().lower() or "risk"
        risk_id = item_id if itype == "risk" else None
        opp_id = item_id if itype == "opportunity" else None
        self._upsert_row(
            "assessments",
            {
                "id": assessment_id,
                "project_id": project_id,
                # Backward-compat fields; nullable (no FK).
                "risk_id": risk_id,
                "opportunity_id": opp_id,
                "item_id": item_id,
                "item_type": itype,
                "assessor_user_id": assessor_user_id,
                "probability": int(probability),
                "impact": int(impact),
                "score": score,
                "notes": notes or "",
                "version": int(version),
                "is_deleted": 1 if is_deleted else 0,
                "updated_at": updated_at,
                "dirty": int(dirty),
            },
        )
        self._commit_if_needed()

    def get_helpdesk_ticket_project_id(self, ticket_id: str) -> str | None:
        """Return the project_id for a ticket, or None if not found."""
        row = self.conn.execute(
            "SELECT project_id FROM helpdesk_tickets WHERE id = ?;", (ticket_id,)
        ).fetchone()
        return str(row["project_id"]) if row else None

    def get_helpdesk_ticket_project_and_version(
        self, ticket_id: str
    ) -> tuple[str, int]:
        """Return (project_id, version) for a help-desk ticket."""
        row = self.conn.execute(
            "SELECT project_id, version FROM helpdesk_tickets WHERE id = ?;",
            (ticket_id,),
        ).fetchone()
        if not row:
            raise KeyError("helpdesk ticket not found in local store")
        return str(row["project_id"]), int(row["version"] or 0)

    def _row_to_ticket(self, row: sqlite3.Row) -> HelpDeskTicket:
        """Convert a sqlite3.Row to a HelpDeskTicket dataclass."""
        return HelpDeskTicket(
            id=str(row["id"]),
            project_id=str(row["project_id"]),
            title=str(row["title"]),
            description=str(row["description"] or ""),
            category=str(row["category"] or "other"),
            priority=str(row["priority"] or "medium"),
            status=str(row["status"] or "open"),
            reporter_email=str(row["reporter_email"] or ""),
            created_at=str(row["created_at"] or ""),
            updated_at=str(row["updated_at"] or ""),
            version=int(row["version"] or 0),
            is_deleted=bool(row["is_deleted"]),
        )

    def list_helpdesk_tickets(self, project_id: str) -> list[HelpDeskTicket]:
        """Return all help-desk tickets for a project, newest first."""
        rows = self.conn.execute(
            "SELECT * FROM helpdesk_tickets WHERE project_id = ? AND is_deleted = 0 ORDER BY updated_at DESC, created_at DESC;",
            (project_id,),
        ).fetchall()
        return [self._row_to_ticket(r) for r in rows]

    def create_helpdesk_ticket(
        self,
        project_id: str,
        *,
        title: str,
        description: str = "",
        category: str = "other",
        priority: str = "medium",
        reporter_email: str = "",
    ) -> HelpDeskTicket:
        """Create a new help-desk ticket locally and mark it dirty for sync."""
        ticket_id = str(uuid.uuid4())
        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        self.conn.execute(
            """
            INSERT INTO helpdesk_tickets
                (id, project_id, title, description, category, priority, status,
                 reporter_email, version, is_deleted, dirty, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'open', ?, 0, 0, 1, ?, ?);
            """,
            (
                ticket_id,
                project_id,
                title,
                description,
                category,
                priority,
                reporter_email,
                now,
                now,
            ),
        )
        self._commit_if_needed()
        row = self.conn.execute(
            "SELECT * FROM helpdesk_tickets WHERE id = ?;", (ticket_id,)
        ).fetchone()
        return self._row_to_ticket(row)

    def update_helpdesk_ticket(
        self,
        ticket_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        category: str | None = None,
        priority: str | None = None,
        status: str | None = None,
    ) -> HelpDeskTicket:
        """Update fields on an existing help-desk ticket."""
        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        row = self.conn.execute(
            "SELECT * FROM helpdesk_tickets WHERE id = ?;", (ticket_id,)
        ).fetchone()
        if not row:
            raise KeyError("helpdesk ticket not found in local store")

        sets: list[str] = ["updated_at = ?", "dirty = 1"]
        params: list[Any] = [now]
        if title is not None:
            sets.append("title = ?")
            params.append(title)
        if description is not None:
            sets.append("description = ?")
            params.append(description)
        if category is not None:
            sets.append("category = ?")
            params.append(category)
        if priority is not None:
            sets.append("priority = ?")
            params.append(priority)
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        params.append(ticket_id)
        self.conn.execute(
            f"UPDATE helpdesk_tickets SET {', '.join(sets)} WHERE id = ?;",  # noqa: S608
            params,
        )
        self._commit_if_needed()
        row = self.conn.execute(
            "SELECT * FROM helpdesk_tickets WHERE id = ?;", (ticket_id,)
        ).fetchone()
        return self._row_to_ticket(row)

    def delete_helpdesk_ticket(self, ticket_id: str) -> None:
        """Permanently delete a help-desk ticket."""
        self.conn.execute("DELETE FROM helpdesk_tickets WHERE id = ?;", (ticket_id,))
        self._commit_if_needed()

    def soft_delete_helpdesk_ticket(self, ticket_id: str) -> tuple[str, int]:
        """Soft-delete a synced help-desk ticket and mark it dirty for sync."""
        project_id, version = self.get_helpdesk_ticket_project_and_version(ticket_id)
        self.conn.execute(
            "UPDATE helpdesk_tickets SET is_deleted = 1, dirty = 1, updated_at = ? WHERE id = ?;",
            (utc_iso(), ticket_id),
        )
        self._commit_if_needed()
        return project_id, version
