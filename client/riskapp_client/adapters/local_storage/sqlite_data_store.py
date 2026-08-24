from __future__ import annotations

import contextlib
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any, TypeVar

from riskapp_client.adapters.local_storage.schema import ensure_schema
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
    Project,
    Risk,
)
from riskapp_client.domain.scored_entity_fields import (
    SCORED_ENTITY_DB_COLUMNS,
    SCORED_ENTITY_META_KEYS,
    SCORED_ENTITY_META_SQLITE_COLUMNS,
)

ModelT = TypeVar("ModelT")

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

_VALID_SCORED_TABLES: set[str] = {"risks", "opportunities"}

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


def _check_table(table: str) -> str:
    """Validate a table name."""
    if table not in _VALID_TABLES:
        raise ValueError(f"Unknown table name: {table!r}")
    return table


def utc_iso() -> str:
    """Return a naive UTC ISO timestamp."""
    return datetime.now(UTC).replace(tzinfo=None).isoformat()


def _norm_text(v: str | None) -> str | None:
    """Strip text and convert empty strings to None."""
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _row_get(row: sqlite3.Row, key: str, default: Any = None) -> Any:
    """Return a sqlite3.Row value by column name with a default."""
    try:
        return row[key]
    except IndexError:
        return default


class LocalStore:
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
        # Cached project data should remain private even when opening a DB that
        # was created by an older version with permissive mode bits.
        if os.path.exists(db_path):
            with contextlib.suppress(OSError):
                os.chmod(db_path, 0o600)
        self._init_schema()

    def close(self) -> None:
        with contextlib.suppress(OSError, sqlite3.Error):
            self.conn.close()

    def __enter__(self) -> LocalStore:  # noqa: PYI034
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Release resources when leaving the context manager."""
        self.close()

    def _init_schema(self) -> None:
        ensure_schema(self.conn)

    def _upsert_row(
        self, table: str, record: dict[str, Any], cur: Any = None, pk: str = "id"
    ) -> None:
        """Insert or update a row."""
        _check_table(table)
        cols = list(record.keys())
        placeholders = ", ".join(["?"] * len(cols))
        set_clause = ", ".join([f"{c}=excluded.{c}" for c in cols if c != pk])
        if set_clause:
            sql = (
                f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders}) "
                f"ON CONFLICT({pk}) DO UPDATE SET {set_clause}"
            )
        else:
            sql = (
                f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders}) "
                f"ON CONFLICT({pk}) DO NOTHING"
            )
        (cur or self.conn).execute(sql, tuple(record[c] for c in cols))

    def get_project(self, project_id: str) -> Project | None:
        row = self.conn.execute(
            "SELECT id, name, description, created_by FROM projects WHERE id=?;",
            (project_id,),
        ).fetchone()
        if not row:
            return None
        return Project(
            id=str(row["id"]),
            name=str(row["name"]),
            description=str(row["description"] or ""),
            created_by=str(_row_get(row, "created_by", "") or ""),
        )

    def create_local_project(
        self,
        *,
        name: str,
        description: str = "",
        project_id: str | None = None,
        created_by: str | None = None,
    ) -> Project:
        pid = str(project_id or f"local-{uuid.uuid4()}")
        owner = (
            created_by
            if created_by is not None
            else (self.get_meta("last_email") or "")
        )
        self._upsert_row(
            "projects",
            {
                "id": pid,
                "name": str(name or "Local Project"),
                "description": description or "",
                "created_by": owner,
            },
        )
        self.conn.commit()
        return Project(
            id=pid,
            name=str(name or "Local Project"),
            description=description or "",
            created_by=owner,
        )

    def migrate_project_id(self, *, old_project_id: str, new_project_id: str) -> None:
        """Replace a local project id with the server project id."""
        old_id = str(old_project_id)
        new_id = str(new_project_id)
        if not old_id or not new_id or old_id == new_id:
            return
        p = self.get_project(old_id)
        if not p:
            return
        # The parent id and every child reference move atomically. Deferring FK
        # checks until commit avoids the previous PRAGMA foreign_keys=OFF flow,
        # which accidentally left enforcement disabled for the connection.
        with self.conn:
            cur = self.conn.cursor()
            cur.execute("PRAGMA defer_foreign_keys=ON;")
            self._upsert_row(
                "projects",
                {
                    "id": new_id,
                    "name": p.name,
                    "description": p.description or "",
                    "created_by": p.created_by or "",
                },
                cur,
            )
            for table in (
                "risks",
                "opportunities",
                "actions",
                "assessments",
                "helpdesk_tickets",
                "sync_state",
                "outbox",
            ):
                cur.execute(
                    f"UPDATE {table} SET project_id=? WHERE project_id=?;",
                    (new_id, old_id),
                )
            cur.execute("DELETE FROM projects WHERE id=?;", (old_id,))
        if (self.get_meta("bootstrap_project_id") or "") == old_id:
            self.set_meta("bootstrap_project_id", new_id)
        if (self.get_meta("bootstrap_user_project_id") or "") == old_id:
            self.set_meta("bootstrap_user_project_id", new_id)
        if (self.get_meta("bootstrap_anon_project_id") or "") == old_id:
            self.set_meta("bootstrap_anon_project_id", new_id)

    def upsert_projects(self, projects: list[Project]) -> None:
        cur = self.conn.cursor()
        for p in projects:
            self._upsert_row(
                "projects",
                {
                    "id": p.id,
                    "name": p.name,
                    "description": p.description or "",
                    "created_by": p.created_by or "",
                },
                cur,
            )
        self.conn.commit()

    def sync_projects(self, server_projects: list[Project]) -> None:
        """Merge server project list with local cache.

        Rules:
        - local-* projects are NEVER touched (managed by offline/sync flow).
        - Projects that exist on server are upserted.
        - Projects NOT on server are only removed if they have ZERO local data
          (no risks, opportunities, actions, assessments, outbox entries).
          This prevents data loss after promotion or during transient issues.
        """
        server_ids = {p.id for p in server_projects}
        local_rows = self.conn.execute("SELECT id FROM projects;").fetchall()
        for row in local_rows:
            pid = str(row["id"])
            # Never touch local-only projects.
            if pid.startswith("local-"):
                continue
            # Don't remove if server still knows about it.
            if pid in server_ids:
                continue
            # Don't remove if there's ANY local data for this project.
            has_data = False
            for child_table in (
                "risks",
                "opportunities",
                "actions",
                "assessments",
                "helpdesk_tickets",
                "outbox",
            ):
                count = self.conn.execute(
                    f"SELECT COUNT(*) FROM {child_table} WHERE project_id = ?;", (pid,)
                ).fetchone()[0]
                if count and int(count) > 0:
                    has_data = True
                    break
            if has_data:
                continue
            # Clean up an empty project the user can no longer access.
            for child_table in ("helpdesk_tickets", "sync_state"):
                self.conn.execute(
                    f"DELETE FROM {child_table} WHERE project_id = ?;", (pid,)
                )
            self.conn.execute("DELETE FROM projects WHERE id = ?;", (pid,))
        self.upsert_projects(server_projects)
        self.conn.commit()

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

    def _pending_outbox_ids(self, project_id: str, *, entity: str) -> set[str]:
        rows = self.conn.execute(
            "SELECT entity_id FROM outbox WHERE project_id=? AND entity=? AND status='pending';",
            (project_id, entity),
        ).fetchall()
        return {str(r["entity_id"]) for r in rows}

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

        def _fallback(val, key, default):
            return val if val is not None else (existing[key] if existing else default)

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
                "version": int(_fallback(version, "version", 0)),
                "is_deleted": int(_fallback(is_deleted, "is_deleted", 0)),
                "updated_at": str(_fallback(updated_at, "updated_at", "")),
                "dirty": int(dirty),
            },
        )
        self.conn.commit()

    def _apply_pull_entities(
        self,
        project_id: str,
        server_items: list[dict[str, Any]],
        entity_name: str,
        table_name: str,
        mapper_fn: Any,
        record_builder_fn: Any,
    ) -> None:
        _check_table(table_name)
        pending_ids = self._pending_outbox_ids(project_id, entity=entity_name)
        cur = self.conn.cursor()
        for raw in server_items:
            obj = mapper_fn(raw)
            if obj.id in pending_ids:
                cur.execute(
                    f"UPDATE {table_name} SET version=?, updated_at=? WHERE id=?;",
                    (int(obj.version), str(obj.updated_at or ""), str(obj.id)),
                )
                continue
            record = record_builder_fn(obj, raw)
            record["project_id"] = project_id
            record["id"] = str(obj.id)
            record["version"] = int(obj.version)
            record["updated_at"] = str(obj.updated_at or "")
            record["dirty"] = 0
            self._upsert_row(table_name, record, cur)
        self.conn.commit()

    def apply_pull_actions(
        self, project_id: str, server_actions: list[dict[str, Any]]
    ) -> None:
        def build_record(action, _raw):
            return {
                "risk_id": action.risk_id,
                "opportunity_id": action.opportunity_id,
                "kind": str(action.kind or ""),
                "title": str(action.title or ""),
                "description": str(action.description or ""),
                "status": str(action.status or "open"),
                "owner_user_id": action.owner_user_id,
                "is_deleted": 1 if bool(action.is_deleted) else 0,
            }

        self._apply_pull_entities(
            project_id,
            server_actions,
            "action",
            "actions",
            action_from_mapping,
            build_record,
        )

    def list_projects(self) -> list[Project]:
        rows = self.conn.execute(
            "SELECT id, name, description, created_by FROM projects ORDER BY name;"
        ).fetchall()
        return [
            Project(
                id=r["id"],
                name=r["name"],
                description=r["description"],
                created_by=str(_row_get(r, "created_by", "") or ""),
            )
            for r in rows
        ]

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key=?;", (key,)
        ).fetchone()
        return str(row["value"]) if row else None

    def set_meta(self, key: str, value: str) -> None:
        self._upsert_row("meta", {"key": key, "value": value}, pk="key")
        self.conn.commit()

    def _next_code(self, project_id: str, *, table: str, prefix: str) -> str:
        """Local code generator (for example R-001 or O-001)."""
        self._assert_scored_table(table)
        like = f"{prefix}-%"
        rows = self.conn.execute(
            f"SELECT code FROM {table} WHERE project_id=? AND code LIKE ? AND code IS NOT NULL;",
            (project_id, like),
        ).fetchall()
        max_n = 0
        for r in rows:
            c = _norm_text(r["code"])
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

    def _assert_scored_table(self, table: str) -> None:
        if table not in _VALID_SCORED_TABLES:
            raise ValueError(f"Invalid scored-entity table: {table!r}")

    def _list_scored_entities(
        self, project_id: str, *, table: str, model_cls: type[ModelT]
    ) -> list[ModelT]:
        self._assert_scored_table(table)
        cols = ", ".join(SCORED_ENTITY_DB_COLUMNS)
        rows = self.conn.execute(
            f"""
            SELECT {cols}
            FROM {table}
            WHERE project_id=? AND is_deleted=0
            ORDER BY (probability*impact) DESC, title ASC
            """,
            (project_id,),
        ).fetchall()
        return [scored_entity_from_mapping(r, model_cls=model_cls) for r in rows]

    def _get_scored_row(self, table: str, entity_id: str) -> sqlite3.Row | None:
        self._assert_scored_table(table)
        return self.conn.execute(
            f"SELECT * FROM {table} WHERE id=?;", (entity_id,)
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
        self._assert_scored_table(table)
        row = self._get_scored_row(table, entity_id)
        if not row:
            raise KeyError(f"{label} not found in local store")
        project_id = str(row["project_id"])
        version = int(row["version"] or 0)
        self.conn.execute(
            f"UPDATE {table} SET is_deleted=1, dirty=1, updated_at=? WHERE id=?;",
            (utc_iso(), entity_id),
        )
        self.conn.commit()
        return project_id, version

    def _norm_scored_meta(self, meta: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k in SCORED_ENTITY_META_KEYS:
            v = meta.get(k)
            if k in _TEXT_META_KEYS:
                out[k] = _norm_text(v) if v is not None else None
            elif k in _INT_META_KEYS:
                out[k] = int(v) if v is not None else None
            else:
                out[k] = v
        return out

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
        self._assert_scored_table(table)
        existing = self._get_scored_row(table, entity_id)

        def _fallback(val, key, default):
            return val if val is not None else (existing[key] if existing else default)

        v = int(_fallback(version, "version", 0))
        is_del = int(_fallback(is_deleted, "is_deleted", 0))
        upd = str(_fallback(updated_at, "updated_at", ""))
        m = self._norm_scored_meta(meta)
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
        self.conn.commit()

    def _apply_pull_scored_entities(
        self,
        project_id: str,
        server_entities: list[dict[str, Any]],
        *,
        table: str,
        outbox_entity: str,
    ) -> None:
        self._assert_scored_table(table)
        pending_ids = {
            r["entity_id"]
            for r in self.conn.execute(
                "SELECT entity_id FROM outbox WHERE project_id=? AND entity=? AND status='pending';",
                (project_id, outbox_entity),
            ).fetchall()
        }
        cur = self.conn.cursor()
        for ent in server_entities:
            eid = str(ent["id"])
            ver = int(ent.get("version") or 0)
            upd = str(ent.get("updated_at") or "")
            if eid in pending_ids:
                cur.execute(
                    f"UPDATE {table} SET version=?, updated_at=? WHERE id=?;",
                    (ver, upd, eid),
                )
                continue
            meta = {k: ent.get(k) for k in SCORED_ENTITY_META_KEYS}
            if not meta.get("status"):
                meta["status"] = "concept"
            m = self._norm_scored_meta(meta)
            record: dict[str, Any] = {
                "id": eid,
                "project_id": project_id,
                "title": str(ent.get("title") or ""),
                "probability": int(ent.get("probability") or 1),
                "impact": int(ent.get("impact") or 1),
                **m,
                "version": ver,
                "is_deleted": 1 if bool(ent.get("is_deleted")) else 0,
                "updated_at": upd,
                "dirty": 0,
            }
            self._upsert_row(table, record, cur)
        self.conn.commit()

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

    def _mark_entity_clean(self, table: str, entity_id: str) -> None:
        _check_table(table)
        self.conn.execute(f"UPDATE {table} SET dirty=0 WHERE id=?;", (entity_id,))
        self.conn.commit()

    def mark_risk_clean(self, risk_id: str) -> None:
        self._mark_entity_clean("risks", risk_id)

    def mark_opportunity_clean(self, opportunity_id: str) -> None:
        self._mark_entity_clean("opportunities", opportunity_id)

    def mark_action_clean(self, action_id: str) -> None:
        self._mark_entity_clean("actions", action_id)

    def mark_assessment_clean(self, assessment_id: str) -> None:
        self._mark_entity_clean("assessments", assessment_id)

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

    def _infer_assessment_item_type(
        self, project_id: str, item_id: str, raw: dict[str, Any]
    ) -> str:
        """Infer whether a pulled assessment belongs to a risk or opportunity.

        Some sync responses only contain item_id. If risk_id/opportunity_id are
        missing, classify using the local parent tables instead of defaulting to
        risk, otherwise opportunity assessments disappear from the Opportunity UI.
        """
        if raw.get("opportunity_id"):
            return "opportunity"
        if raw.get("risk_id"):
            return "risk"
        if self.conn.execute(
            "SELECT 1 FROM opportunities WHERE project_id=? AND id=? LIMIT 1;",
            (project_id, item_id),
        ).fetchone():
            return "opportunity"
        if self.conn.execute(
            "SELECT 1 FROM risks WHERE project_id=? AND id=? LIMIT 1;",
            (project_id, item_id),
        ).fetchone():
            return "risk"
        return "risk"

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
        self.conn.commit()

    def get_last_server_time(self, project_id: str) -> str:
        row = self.conn.execute(
            "SELECT last_server_time FROM sync_state WHERE project_id=?;", (project_id,)
        ).fetchone()
        return str(row["last_server_time"]) if row else "1970-01-01T00:00:00"

    def set_last_server_time(self, project_id: str, server_time: str) -> None:
        self._upsert_row(
            "sync_state",
            {"project_id": project_id, "last_server_time": server_time},
            pk="project_id",
        )
        self.conn.commit()

    def apply_pull_risks(
        self, project_id: str, server_risks: list[dict[str, Any]]
    ) -> None:
        self._apply_pull_scored_entities(
            project_id,
            server_risks,
            table="risks",
            outbox_entity="risk",
        )

    def apply_pull_opportunities(
        self, project_id: str, server_opps: list[dict[str, Any]]
    ) -> None:
        self._apply_pull_scored_entities(
            project_id,
            server_opps,
            table="opportunities",
            outbox_entity="opportunity",
        )

    def apply_pull_assessments(
        self, project_id: str, server_assessments: list[dict[str, Any]]
    ) -> None:
        def build_record(assessment, raw):
            item_id = str(assessment.item_id)
            item_type = self._infer_assessment_item_type(project_id, item_id, raw)
            risk_id = item_id if item_type == "risk" else None
            opp_id = item_id if item_type == "opportunity" else None

            return {
                "risk_id": risk_id,
                "opportunity_id": opp_id,
                "item_id": item_id,
                "item_type": str(item_type),
                "assessor_user_id": str(assessment.assessor_user_id or ""),
                "probability": int(assessment.probability),
                "impact": int(assessment.impact),
                "score": int(assessment.score),
                "notes": str(assessment.notes or ""),
                "is_deleted": 1 if bool(assessment.is_deleted) else 0,
            }

        self._apply_pull_entities(
            project_id,
            server_assessments,
            "assessment",
            "assessments",
            assessment_from_mapping,
            build_record,
        )

    # ---- Help Desk -----------------------------------------------------------

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
        self.conn.commit()
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
            f"UPDATE helpdesk_tickets SET {', '.join(sets)} WHERE id = ?;",
            params,
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT * FROM helpdesk_tickets WHERE id = ?;", (ticket_id,)
        ).fetchone()
        return self._row_to_ticket(row)

    def delete_helpdesk_ticket(self, ticket_id: str) -> None:
        """Permanently delete a help-desk ticket."""
        self.conn.execute("DELETE FROM helpdesk_tickets WHERE id = ?;", (ticket_id,))
        self.conn.commit()

    def soft_delete_helpdesk_ticket(self, ticket_id: str) -> tuple[str, int]:
        """Soft-delete a synced help-desk ticket and mark it dirty for sync."""
        row = self.conn.execute(
            "SELECT project_id, version FROM helpdesk_tickets WHERE id = ?;",
            (ticket_id,),
        ).fetchone()
        if not row:
            raise KeyError("helpdesk ticket not found in local store")
        project_id = str(row["project_id"])
        version = int(row["version"] or 0)
        self.conn.execute(
            "UPDATE helpdesk_tickets SET is_deleted = 1, dirty = 1, updated_at = ? WHERE id = ?;",
            (utc_iso(), ticket_id),
        )
        self.conn.commit()
        return project_id, version

    def apply_pull_helpdesk_tickets(self, project_id: str, items: list[dict]) -> None:
        """Upsert server-sourced helpdesk tickets into the local store.

        Items arriving from the server may carry is_deleted=true; those are
        removed locally.  All other fields are written verbatim.
        """
        pending_ids = self._pending_outbox_ids(project_id, entity="helpdesk_ticket")
        for item in items:
            ticket_id = str(item.get("id") or "")
            if not ticket_id:
                continue
            if ticket_id in pending_ids:
                self.conn.execute(
                    "UPDATE helpdesk_tickets SET version = ?, updated_at = ? WHERE id = ?;",
                    (
                        int(item.get("version") or 0),
                        str(item.get("updated_at") or ""),
                        ticket_id,
                    ),
                )
                continue
            self.conn.execute(
                """
                INSERT INTO helpdesk_tickets
                    (id, project_id, title, description, category, priority, status,
                     reporter_email, version, is_deleted, dirty, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title          = excluded.title,
                    description    = excluded.description,
                    category       = excluded.category,
                    priority       = excluded.priority,
                    status         = excluded.status,
                    reporter_email = excluded.reporter_email,
                    version        = excluded.version,
                    is_deleted     = excluded.is_deleted,
                    dirty          = 0,
                    updated_at     = excluded.updated_at;
                """,
                (
                    ticket_id,
                    str(item.get("project_id") or project_id),
                    str(item.get("title") or ""),
                    str(item.get("description") or ""),
                    str(item.get("category") or "other"),
                    str(item.get("priority") or "medium"),
                    str(item.get("status") or "open"),
                    str(item.get("reporter_email") or ""),
                    int(item.get("version") or 0),
                    1 if bool(item.get("is_deleted")) else 0,
                    str(item.get("created_at") or ""),
                    str(item.get("updated_at") or ""),
                ),
            )
        self.conn.commit()
