"""Server rows pulled into the local store, push acknowledgements and watermarks."""

from __future__ import annotations

import json
from typing import Any

from riskapp_client.adapters.local_storage.schema import check_identifier
from riskapp_client.adapters.local_storage.sqlite_base import (
    SqliteStoreBase,
    assert_scored_table,
    check_table,
    norm_scored_meta,
)
from riskapp_client.adapters.mappers.action_assessment_mapper import (
    action_from_mapping,
    assessment_from_mapping,
)
from riskapp_client.domain.conflict_fields import MERGE_FIELDS
from riskapp_client.domain.domain_models import Action, Assessment
from riskapp_client.domain.scored_entity_fields import SCORED_ENTITY_META_KEYS
from riskapp_client.domain.sync_protocol import strict_int

_TABLE_BY_ENTITY = {
    "risk": "risks",
    "opportunity": "opportunities",
    "action": "actions",
    "assessment": "assessments",
    "helpdesk_ticket": "helpdesk_tickets",
}


def _sync_table(entity: str) -> str:
    """The local table that stores a synced entity."""
    table = _TABLE_BY_ENTITY.get(entity)
    if table is None:
        raise ValueError(f"Unsupported sync entity: {entity!r}")
    return table


def _check_ack_identity(
    record: dict[str, Any], *, entity_id: str, project_id: str
) -> None:
    """An acknowledged record may omit its id or project, but must not name another."""
    record_id = str(record.get("id") or "")
    if record_id and record_id != entity_id:
        raise RuntimeError("Push acknowledgement returned another entity")
    record_project = str(record.get("project_id") or "")
    if record_project and record_project != project_id:
        raise RuntimeError("Push acknowledgement returned another project")


class ServerStateMixin(SqliteStoreBase):
    """Reconcile the local copy with what the server has confirmed."""

    def _pending_outbox_ids(self, project_id: str, *, entity: str) -> set[str]:
        rows = self.conn.execute(
            "SELECT entity_id FROM outbox WHERE project_id=? AND entity=? "
            "AND status IN ('pending', 'retry', 'blocked');",
            (project_id, entity),
        ).fetchall()
        return {str(r["entity_id"]) for r in rows}

    def _remember_conflict_server_record(
        self,
        project_id: str,
        entity: str,
        entity_id: str,
        server_record: dict[str, Any],
    ) -> None:
        """Keep the newest pulled server copy separate from the dirty local row."""
        row = self.conn.execute(
            """
            SELECT change_id, result_json
            FROM outbox
            WHERE project_id=? AND entity=? AND entity_id=?
              AND status='blocked' AND failure_kind='conflict'
            LIMIT 1
            """,
            (project_id, entity, entity_id),
        ).fetchone()
        if row is None:
            return
        try:
            parsed = json.loads(str(row["result_json"] or "{}"))
        except TypeError, ValueError:
            parsed = {}
        outcome = parsed if isinstance(parsed, dict) else {}
        outcome["server_version"] = int(server_record.get("version") or 0)
        outcome["server_record"] = dict(server_record)
        outcome["server_updated_at"] = str(server_record.get("updated_at") or "")
        self.conn.execute(
            "UPDATE outbox SET result_json=? WHERE change_id=?;",
            (
                json.dumps(outcome, default=str, separators=(",", ":")),
                row["change_id"],
            ),
        )

    def _apply_pull_entities(
        self,
        project_id: str,
        server_items: list[dict[str, Any]],
        entity_name: str,
        table_name: str,
        mapper_fn: Any,
        record_builder_fn: Any,
    ) -> None:
        check_table(table_name)
        pending_ids = self._pending_outbox_ids(project_id, entity=entity_name)
        cur = self.conn.cursor()
        for raw in server_items:
            obj = mapper_fn(raw)
            if obj.id in pending_ids:
                self._remember_conflict_server_record(
                    project_id,
                    entity_name,
                    str(obj.id),
                    raw,
                )
                continue
            record = record_builder_fn(obj, raw)
            record["project_id"] = project_id
            record["id"] = str(obj.id)
            record["version"] = int(obj.version)
            record["updated_at"] = str(obj.updated_at or "")
            record["dirty"] = 0
            self._upsert_row(table_name, record, cur)
        self._commit_if_needed()

    def apply_pull_actions(
        self, project_id: str, server_actions: list[dict[str, Any]]
    ) -> None:
        def build_record(action: Action, _raw: dict[str, Any]) -> dict[str, Any]:
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

    def _apply_pull_scored_entities(
        self,
        project_id: str,
        server_entities: list[dict[str, Any]],
        *,
        table: str,
        outbox_entity: str,
    ) -> None:
        assert_scored_table(table)

        with self.write_transaction():
            pending_ids = self._pending_outbox_ids(project_id, entity=outbox_entity)
            cur = self.conn.cursor()
            for ent in server_entities:
                eid = str(ent["id"])
                ver = int(ent.get("version") or 0)
                upd = str(ent.get("updated_at") or "")
                if eid in pending_ids:
                    # Keep the last acknowledged version while a local write is
                    # pending. The server's newer version belongs in conflict
                    # metadata until the user explicitly resolves the conflict.
                    self._remember_conflict_server_record(
                        project_id,
                        outbox_entity,
                        eid,
                        ent,
                    )
                    continue
                meta = {k: ent.get(k) for k in SCORED_ENTITY_META_KEYS}
                if not meta.get("status"):
                    meta["status"] = "concept"
                m = norm_scored_meta(meta)
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
                # Codes are unique per project on the server, so another cached
                # row holding this code is stale: a provisional offline code, or
                # a record whose code has since changed on the server (codes can
                # be swapped). Release it instead of failing the pull; that
                # row's own server state brings its current code. The local row
                # and its exact outbox payload/receipt are preserved.
                cur.execute(
                    f"UPDATE {table} SET code=NULL "  # noqa: S608
                    "WHERE project_id=? AND code=? AND id<>?;",
                    (project_id, m.get("code"), eid),
                )
                self._upsert_row(table, record, cur)

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

    def apply_pull_assessments(
        self, project_id: str, server_assessments: list[dict[str, Any]]
    ) -> None:
        def build_record(assessment: Assessment, raw: dict[str, Any]) -> dict[str, Any]:
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

    def apply_pull_helpdesk_tickets(self, project_id: str, items: list[dict]) -> None:
        """Upsert server-sourced helpdesk tickets into the local store.

        Deleted tickets are kept with is_deleted=1; missing fields get defaults.
        """
        pending_ids = self._pending_outbox_ids(project_id, entity="helpdesk_ticket")
        for item in items:
            ticket_id = str(item.get("id") or "")
            if not ticket_id:
                continue
            if ticket_id in pending_ids:
                self._remember_conflict_server_record(
                    project_id,
                    "helpdesk_ticket",
                    ticket_id,
                    item,
                )
                continue
            self._upsert_row(
                "helpdesk_tickets",
                {
                    "id": ticket_id,
                    "project_id": str(item.get("project_id") or project_id),
                    "title": str(item.get("title") or ""),
                    "description": str(item.get("description") or ""),
                    "category": str(item.get("category") or "other"),
                    "priority": str(item.get("priority") or "medium"),
                    "status": str(item.get("status") or "open"),
                    "reporter_email": str(item.get("reporter_email") or ""),
                    "version": int(item.get("version") or 0),
                    "is_deleted": 1 if bool(item.get("is_deleted")) else 0,
                    "dirty": 0,
                    "created_at": str(item.get("created_at") or ""),
                    "updated_at": str(item.get("updated_at") or ""),
                },
            )
        self._commit_if_needed()

    def apply_push_acknowledgement(
        self,
        project_id: str,
        *,
        entity: str,
        entity_id: str,
        server_version: int | None,
        server_record: dict[str, Any] | None,
    ) -> None:
        """Apply the canonical row returned for one accepted outbox change."""
        if server_record is not None:
            record = dict(server_record)
            _check_ack_identity(record, entity_id=entity_id, project_id=project_id)
            record["id"] = entity_id
            record["project_id"] = project_id
            if server_version is not None:
                record_version = int(record.get("version") or 0)
                if record_version != server_version:
                    raise RuntimeError("Push acknowledgement version mismatch")

            appliers = {
                "risk": self.apply_pull_risks,
                "opportunity": self.apply_pull_opportunities,
                "action": self.apply_pull_actions,
                "assessment": self.apply_pull_assessments,
                "helpdesk_ticket": self.apply_pull_helpdesk_tickets,
            }
            apply_record = appliers.get(entity)
            if apply_record is None:
                raise ValueError(f"Unsupported sync entity: {entity!r}")
            apply_record(project_id, [record])
            return

        if server_version is None:
            # Nothing to update: the caller only removes the outbox entry for
            # accepted results that carry no server state.
            return
        table = _sync_table(entity)
        self.conn.execute(
            f"UPDATE {table} SET version=?, dirty=0 "  # noqa: S608
            "WHERE id=? AND project_id=?;",
            (server_version, entity_id, project_id),
        )
        self._commit_if_needed()

    def release_scored_codes_for_acknowledgements(
        self,
        project_id: str,
        results: list[dict[str, Any]],
    ) -> None:
        """Release local codes before applying a canonical acknowledgement batch.

        Server-assigned codes can form a local swap (for example R-001/R-002
        becoming R-002/R-003). Clearing all affected owners first prevents the
        per-project unique index from rejecting an otherwise valid batch.
        """
        grouped: dict[str, tuple[set[str], set[str]]] = {
            "risk": (set(), set()),
            "opportunity": (set(), set()),
        }
        for result in results:
            entity = str(result.get("entity") or "")
            if entity not in grouped or result.get("status") != "accepted":
                continue
            record = result.get("server_record")
            if not isinstance(record, dict):
                continue
            entity_id = str(result.get("entity_id") or record.get("id") or "")
            _check_ack_identity(record, entity_id=entity_id, project_id=project_id)
            if entity_id:
                grouped[entity][0].add(entity_id)
            code = str(record.get("code") or "").strip()
            if code:
                grouped[entity][1].add(code)

        for entity, (entity_ids, codes) in grouped.items():
            if entity_ids or codes:
                self._release_codes(_sync_table(entity), project_id, entity_ids, codes)
        self._commit_if_needed()

    def _release_codes(
        self, table: str, project_id: str, entity_ids: set[str], codes: set[str]
    ) -> None:
        """Clear the codes held by these rows and any row holding these codes."""
        clauses: list[str] = []
        params: list[object] = [project_id]
        for column, values in (("id", entity_ids), ("code", codes)):
            if values:
                clauses.append(f"{column} IN ({','.join('?' * len(values))})")
                params.extend(sorted(values))
        self.conn.execute(
            f"UPDATE {table} SET code=NULL WHERE project_id=? "  # noqa: S608
            f"AND ({' OR '.join(clauses)});",
            params,
        )

    def advance_push_acknowledgement(
        self,
        project_id: str,
        *,
        entity: str,
        entity_id: str,
        server_version: int | None,
        server_record: dict[str, Any] | None,
    ) -> None:
        """Advance server-owned metadata without overwriting a newer local edit."""
        table = _sync_table(entity)
        record = dict(server_record or {})
        _check_ack_identity(record, entity_id=entity_id, project_id=project_id)
        record_version = strict_int(record.get("version"))
        if (
            server_version is not None
            and record_version is not None
            and server_version != record_version
        ):
            raise RuntimeError("Push acknowledgement version mismatch")
        version = server_version if server_version is not None else record_version
        assignments: list[str] = []
        params: list[object] = []
        if version is not None:
            assignments.append("version=MAX(version, ?)")
            params.append(version)
        if entity in {"risk", "opportunity"} and "code" in record:
            assignments.append("code=?")
            params.append(record.get("code"))
        if not assignments:
            return
        params.extend((entity_id, project_id))
        self.conn.execute(
            f"UPDATE {table} SET {', '.join(assignments)} "  # noqa: S608
            "WHERE id=? AND project_id=?;",
            params,
        )
        self._commit_if_needed()

    def get_last_server_time(self, project_id: str) -> str:
        row = self.conn.execute(
            "SELECT last_server_time FROM sync_state WHERE project_id=?;", (project_id,)
        ).fetchone()
        return str(row["last_server_time"]) if row else "1970-01-01T00:00:00"

    def get_last_server_sequence(self, project_id: str) -> int:
        row = self.conn.execute(
            "SELECT last_server_sequence FROM sync_state WHERE project_id=?;",
            (project_id,),
        ).fetchone()
        return int(row["last_server_sequence"] or 0) if row else 0

    def set_last_server_time(self, project_id: str, server_time: str) -> None:
        """Update the display timestamp without discarding a sequence watermark."""
        self.set_sync_watermark(
            project_id,
            server_time,
            self.get_last_server_sequence(project_id),
        )

    def set_sync_watermark(
        self,
        project_id: str,
        server_time: str,
        server_sequence: int | None,
    ) -> None:
        sequence = 0 if server_sequence is None else int(server_sequence)
        if sequence < 0:
            raise ValueError("server_sequence must be nonnegative")
        self._upsert_row(
            "sync_state",
            {
                "project_id": project_id,
                "last_server_time": server_time,
                "last_server_sequence": sequence,
            },
            pk="project_id",
        )
        self._commit_if_needed()

    def reset_sync_watermark(self, project_id: str, server_time: str) -> None:
        self.set_sync_watermark(project_id, server_time, 0)

    def apply_merged_fields(
        self, entity: str, project_id: str, entity_id: str, record: dict[str, Any]
    ) -> None:
        """Mark a server-based merge dirty while preserving its version."""
        if entity not in _TABLE_BY_ENTITY:
            raise ValueError("Unsupported merge entity")
        table = _TABLE_BY_ENTITY[entity]
        names = [key for key in MERGE_FIELDS[entity] if key in record]
        for key in names:
            check_identifier(key)
        assignments = ", ".join(f"{key}=?" for key in names)
        params = [record[key] for key in names]
        if entity == "assessment":
            # Unlike scored risks, assessments persist their derived score.
            # Recompute it from the chosen values in the same atomic update.
            assignments = f"{assignments}, score=?"
            params.append(int(record["probability"]) * int(record["impact"]))
        assignments = f"{assignments}, dirty=1" if assignments else "dirty=1"
        result = self.conn.execute(
            f"UPDATE {table} SET {assignments} WHERE id=? AND project_id=?;",  # noqa: S608
            (*params, entity_id, project_id),
        )
        if result.rowcount != 1:
            raise RuntimeError("The merged local item is unavailable")
        self._commit_if_needed()
