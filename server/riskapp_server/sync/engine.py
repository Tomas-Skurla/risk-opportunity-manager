from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.inspection import inspect as sa_inspect
from sqlalchemy.orm import Session

from riskapp_server.core.config import MAX_SYNC_PULL_PER_ENTITY, SYNC_PUSH_EXUNGE_EVERY
from riskapp_server.core.permissions import ensure_member, ensure_role_at_least
from riskapp_server.core.scoring import recalculate_item_scores
from riskapp_server.db.session import (
    Action,
    ActionStatus,
    Assessment,
    AuditLog,
    HelpDeskCategory,
    HelpDeskPriority,
    HelpDeskStatus,
    HelpDeskTicket,
    Item,
    RiskStatus,
    SyncReceipt,
    utcnow,
)
from riskapp_server.schemas.models import (
    ActionOut,
    HelpDeskTicketOut,
    SyncActionRecord,
    SyncAssessmentRecord,
    SyncChange,
    SyncHelpDeskTicketRecord,
    SyncItemRecord,
)

ENTITY_REGISTRY = {
    "risk": {
        "model": Item,
        "schema": SyncItemRecord,
        "manager_delete": True,
        "defaults": {
            "title": "Untitled",
            "probability": 1,
            "impact": 1,
            "type": "risk",
        },
    },
    "opportunity": {
        "model": Item,
        "schema": SyncItemRecord,
        "manager_delete": True,
        "defaults": {
            "title": "Untitled",
            "probability": 1,
            "impact": 1,
            "type": "opportunity",
        },
    },
    "action": {
        "model": Action,
        "schema": SyncActionRecord,
        "manager_delete": True,
        "defaults": {
            "title": "Untitled action",
            "kind": "mitigation",
            "status": ActionStatus.open.value,
        },
    },
    "assessment": {
        "model": Assessment,
        "schema": SyncAssessmentRecord,
        "manager_delete": False,
        "defaults": {"probability": 1, "impact": 1},
        "parent_model": Item,
        "parent_field": "item_id",
    },
    "helpdesk_ticket": {
        "model": HelpDeskTicket,
        "schema": SyncHelpDeskTicketRecord,
        "manager_delete": False,
        "defaults": {
            "title": "Untitled ticket",
            "category": HelpDeskCategory.other.value,
            "priority": HelpDeskPriority.medium.value,
            "status": HelpDeskStatus.open.value,
        },
    },
}

ENTITY_MODELS = {k: v["model"] for k, v in ENTITY_REGISTRY.items()}
OPS = {"upsert", "delete"}


def parse_uuid(value: Any, field: str) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid UUID for {field}"
        ) from exc


def model_to_dict(obj: Any) -> dict[str, Any]:
    """Serialize a model to JSON-safe values."""

    out: dict[str, Any] = {}
    insp = sa_inspect(obj)
    for attr in insp.mapper.column_attrs:
        k = attr.key
        v = getattr(obj, k)
        if isinstance(v, uuid.UUID):
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        else:
            out[k] = v
    if hasattr(obj, "item_id") and "item_id" in out:
        out.setdefault("risk_id", out["item_id"])
        out.setdefault("opportunity_id", out["item_id"])
    return out


def model_to_sync_dict(db: Session, entity: str, obj: Any) -> dict[str, Any]:
    """Serialize one entity with unambiguous parent aliases for the client."""
    out = model_to_dict(obj)
    if entity not in {"action", "assessment"}:
        return out
    item_id = out.get("item_id")
    item_type = (
        db.execute(select(Item.type).where(Item.id == obj.item_id)).scalar()
        if item_id
        else None
    )
    out["risk_id"] = item_id if item_type == "risk" else None
    out["opportunity_id"] = item_id if item_type == "opportunity" else None
    return out


def _maybe_recalculate_scores(obj: Any) -> None:

    if all(hasattr(obj, a) for a in ("probability", "impact", "score")):
        recalculate_item_scores(obj)


def _min_role_for_change(entity: str, op: str) -> str:
    return (
        "manager"
        if op == "delete" and ENTITY_REGISTRY[entity]["manager_delete"]
        else "member"
    )


def _naive_utc(dt: datetime) -> datetime:
    return (
        dt.astimezone(UTC).replace(tzinfo=None)
        if getattr(dt, "tzinfo", None) is not None
        else dt
    )


def _parse_cursor(
    cur: str | None, *, default_since: datetime, snapshot_time: datetime
) -> tuple[datetime, uuid.UUID]:
    if not cur:
        return default_since, uuid.UUID(int=0)
    try:
        ts_s, id_s = cur.split("|", 1)
        ts = datetime.fromisoformat(ts_s)
        if getattr(ts, "tzinfo", None) is not None:
            ts = ts.astimezone(UTC).replace(tzinfo=None)
        if ts > snapshot_time:
            raise ValueError("cursor is beyond snapshot")
        return ts, uuid.UUID(id_s)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid cursor") from exc


def _encode_cursor(ts: datetime, entity_id: uuid.UUID) -> str:
    return f"{_naive_utc(ts).isoformat()}|{entity_id}"


def pull_since(
    db: Session,
    project_id: uuid.UUID,
    since: datetime,
    *,
    limit_per_entity: int | None = None,
    cursors: dict[str, str] | None = None,
    snapshot_time: datetime | None = None,
) -> dict[str, Any]:

    request_time = _naive_utc(utcnow())
    since = _naive_utc(since)
    snapshot_time = (
        _naive_utc(snapshot_time) if snapshot_time is not None else request_time
    )
    if snapshot_time < since:
        raise HTTPException(status_code=400, detail="snapshot_time precedes since")
    if snapshot_time > request_time:
        raise HTTPException(status_code=400, detail="snapshot_time is in the future")

    # Cap the response size unless paginating.
    if limit_per_entity is None:
        hard_cap: int | None = MAX_SYNC_PULL_PER_ENTITY
        lim: int | None = hard_cap
    else:
        hard_cap = None
        lim = limit_per_entity  # enables cursor pagination when set

    cursors = cursors or {}

    def item_page(item_type: str, key: str):
        ts, last_id = _parse_cursor(
            cursors.get(key), default_since=since, snapshot_time=snapshot_time
        )
        base_cur = _encode_cursor(ts, last_id)
        q = (
            select(Item)
            .where(
                Item.project_id == project_id,
                Item.type == item_type,
                Item.updated_at <= snapshot_time,
                or_(
                    Item.updated_at > ts,
                    (Item.updated_at == ts) & (Item.id > last_id),
                ),
            )
            .order_by(Item.updated_at.asc(), Item.id.asc())
        )

        rows = db.execute(q.limit(lim + 1) if lim else q).scalars().all()
        more = bool(lim and len(rows) > lim)
        if more:
            rows = rows[:lim]
        next_cur = (
            _encode_cursor(rows[-1].updated_at, rows[-1].id) if rows else base_cur
        )
        return rows, more, next_cur

    risks, more_risks, cur_risks = item_page("risk", "risks")
    opportunities, more_opps, cur_opps = item_page("opportunity", "opportunities")

    def _paginate_joined(
        Model: Any, cursor_key: str, project_filter: Any
    ) -> tuple[list, bool, str]:
        ts, last_id = _parse_cursor(
            cursors.get(cursor_key),
            default_since=since,
            snapshot_time=snapshot_time,
        )
        base_cur = _encode_cursor(ts, last_id)
        q = (
            select(Model, Item.type)
            .join(Item, Model.item_id == Item.id)
            .where(
                project_filter,
                Model.updated_at <= snapshot_time,
                or_(
                    Model.updated_at > ts,
                    (Model.updated_at == ts) & (Model.id > last_id),
                ),
            )
            .order_by(Model.updated_at.asc(), Model.id.asc())
        )
        rows = db.execute(q.limit(lim + 1) if lim else q).all()
        more = bool(lim and len(rows) > lim)
        if more:
            rows = rows[:lim]
        next_cur = (
            _encode_cursor(rows[-1][0].updated_at, rows[-1][0].id) if rows else base_cur
        )
        return rows, more, next_cur

    # Actions.
    action_rows, more_actions, cur_actions = _paginate_joined(
        Action, "actions", Action.project_id == project_id
    )
    actions_out = [
        ActionOut(
            id=a.id,
            project_id=a.project_id,
            risk_id=a.item_id if t == "risk" else None,
            opportunity_id=a.item_id if t == "opportunity" else None,
            kind=a.kind,
            title=a.title,
            description=a.description,
            status=a.status,
            owner_user_id=a.owner_user_id,
            updated_at=a.updated_at,
            version=a.version,
            is_deleted=a.is_deleted,
        ).model_dump(mode="json")
        for a, t in action_rows
    ]

    # Assessments.
    assessment_rows, more_assessments, cur_assessments = _paginate_joined(
        Assessment, "assessments", Item.project_id == project_id
    )

    # Help Desk tickets.
    def _paginate_simple(
        Model: Any, cursor_key: str, project_filter: Any
    ) -> tuple[list, bool, str]:
        ts, last_id = _parse_cursor(
            cursors.get(cursor_key),
            default_since=since,
            snapshot_time=snapshot_time,
        )
        base_cur = _encode_cursor(ts, last_id)
        q = (
            select(Model)
            .where(
                project_filter,
                Model.updated_at <= snapshot_time,
                or_(
                    Model.updated_at > ts,
                    (Model.updated_at == ts) & (Model.id > last_id),
                ),
            )
            .order_by(Model.updated_at.asc(), Model.id.asc())
        )
        rows = db.execute(q.limit(lim + 1) if lim else q).scalars().all()
        more = bool(lim and len(rows) > lim)
        if more:
            rows = rows[:lim]
        next_cur = (
            _encode_cursor(rows[-1].updated_at, rows[-1].id) if rows else base_cur
        )
        return rows, more, next_cur

    helpdesk_rows, more_helpdesk, cur_helpdesk = _paginate_simple(
        HelpDeskTicket, "helpdesk_tickets", HelpDeskTicket.project_id == project_id
    )

    has_more = {
        "risks": more_risks,
        "opportunities": more_opps,
        "actions": more_actions,
        "assessments": more_assessments,
        "helpdesk_tickets": more_helpdesk,
    }

    # Keep the payload JSON-safe and add legacy aliases.
    assessments_out: list[dict[str, Any]] = []
    for a, t in assessment_rows:
        d = model_to_dict(a)
        # Ensure item_id is present.
        if "item_id" not in d and "risk_id" in d:
            d["item_id"] = d["risk_id"]
        item_id = d.get("item_id")
        d["risk_id"] = item_id if t == "risk" else None
        d["opportunity_id"] = item_id if t == "opportunity" else None
        assessments_out.append(d)

    out: dict[str, Any] = {
        "server_time": snapshot_time,
        "risks": [model_to_dict(r) for r in risks],
        "opportunities": [model_to_dict(o) for o in opportunities],
        "actions": actions_out,
        "assessments": assessments_out,
        "helpdesk_tickets": [
            HelpDeskTicketOut.model_validate(t).model_dump(mode="json")
            for t in helpdesk_rows
        ],
    }

    if hard_cap and any(has_more.values()):
        raise HTTPException(
            status_code=413,
            detail=("Sync pull too large. Paginate using limit_per_entity + cursors."),
        )

    if limit_per_entity is not None:
        out["has_more"] = has_more
        out["cursors"] = {
            "risks": cur_risks,
            "opportunities": cur_opps,
            "actions": cur_actions,
            "assessments": cur_assessments,
            "helpdesk_tickets": cur_helpdesk,
        }
    return out


class ConflictError(Exception):
    def __init__(
        self,
        reason: str,
        entity_id: uuid.UUID | None,
        server_version: int | None,
        server_record: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.entity_id = entity_id
        self.server_version = server_version
        self.server_record = server_record
        self.server_updated_at = (
            str(server_record.get("updated_at"))
            if server_record and server_record.get("updated_at") is not None
            else None
        )


def _begin_push_transaction(db: Session) -> None:
    """Acquire SQLite's writer reservation before reading entity versions.

    PostgreSQL conditional updates lock and re-check matching rows naturally.
    SQLite WAL transactions need to begin as writers to avoid a stale read
    transaction failing later with SQLITE_BUSY_SNAPSHOT instead of producing a
    deterministic version conflict.
    """
    get_bind = getattr(db, "get_bind", None)
    if not callable(get_bind):
        return
    bind = get_bind()
    if getattr(getattr(bind, "dialect", None), "name", None) != "sqlite":
        return
    if db.in_transaction():
        # Authentication/authorization may already have opened a read-only
        # transaction. No mutations occur before push_changes is entered.
        db.rollback()
    db.connection().exec_driver_sql("BEGIN IMMEDIATE")


def _change_result(
    *,
    change_id: uuid.UUID,
    status: str,
    entity: str,
    op: str,
    entity_id: uuid.UUID | str | None,
    response: dict[str, Any] | None = None,
    replayed: bool = False,
) -> dict[str, Any]:
    """Build the stable per-change result returned for new and replayed work."""
    payload = response if isinstance(response, dict) else {}
    stored_entity_id = payload.get("entity_id") or entity_id
    result: dict[str, Any] = {
        "change_id": str(change_id),
        "status": status,
        "replayed": bool(replayed),
        "entity": entity,
        "op": op,
        "entity_id": str(stored_entity_id) if stored_entity_id else None,
    }
    for key in (
        "reason",
        "detail",
        "server_version",
        "server_record",
        "server_updated_at",
        "failure_kind",
        "retryable",
    ):
        if key in payload:
            result[key] = payload[key]
    return result


def _receipt_result(receipt: SyncReceipt) -> dict[str, Any]:
    return _change_result(
        change_id=receipt.change_id,
        status=receipt.status,
        entity=receipt.entity,
        op=receipt.op,
        entity_id=receipt.entity_id,
        response=receipt.response,
        replayed=True,
    )


def _append_legacy_outcome(
    result: dict[str, Any],
    conflicts: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> None:
    """Populate the original aggregate fields for backwards compatibility."""
    status = result.get("status")
    if status == "conflict":
        conflict = {
            "change_id": result["change_id"],
            "entity": result.get("entity"),
            "id": result.get("entity_id"),
            "reason": result.get("reason"),
            "server_version": result.get("server_version"),
            "server_record": result.get("server_record"),
            "server_updated_at": result.get("server_updated_at"),
            "failure_kind": result.get("failure_kind") or "conflict",
            "retryable": bool(result.get("retryable")),
        }
        if result.get("replayed"):
            conflict["replayed"] = True
        conflicts.append(conflict)
    elif status == "error":
        error = {
            "change_id": result["change_id"],
            "entity": result.get("entity"),
            "op": result.get("op"),
            "reason": result.get("reason"),
            "failure_kind": result.get("failure_kind") or "error",
            "retryable": bool(result.get("retryable")),
        }
        if result.get("detail") is not None:
            error["detail"] = result["detail"]
        if result.get("replayed"):
            error["replayed"] = True
        errors.append(error)


def push_changes(
    db: Session, user_id: uuid.UUID, project_id: uuid.UUID, changes: list[SyncChange]
) -> dict[str, Any]:
    if changes:
        _begin_push_transaction(db)
    role = ensure_member(db, project_id, user_id)

    accepted = duplicates = 0
    dup_ids: list[str] = []
    conflicts: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    batch_results: dict[uuid.UUID, dict[str, Any]] = {}
    wrote = 0

    def _evict_if_needed() -> None:
        nonlocal wrote
        if SYNC_PUSH_EXUNGE_EVERY and wrote and wrote % SYNC_PUSH_EXUNGE_EVERY == 0:
            # Keep the transaction atomic and limit identity-map growth.
            db.flush()
            db.expunge_all()

    ids = [c.change_id for c in changes]
    if ids:
        receipt_rows = (
            db.execute(
                select(SyncReceipt).where(
                    SyncReceipt.change_id.in_(ids),
                    SyncReceipt.project_id == project_id,
                    SyncReceipt.user_id == user_id,
                )
            )
            .scalars()
            .all()
        )
        existing_receipts = {
            receipt.change_id: receipt for receipt in receipt_rows
        }
    else:
        existing_receipts = {}

    seen_change_ids = set(existing_receipts)

    for ch in changes:
        if ch.change_id in seen_change_ids:
            duplicates += 1
            dup_ids.append(str(ch.change_id))
            if ch.change_id in existing_receipts:
                replay = _receipt_result(existing_receipts[ch.change_id])
            else:
                replay = {**batch_results[ch.change_id], "replayed": True}
            results.append(replay)
            _append_legacy_outcome(replay, conflicts, errors)
            continue
        # A receipt is not visible to the query above until this transaction is
        # flushed. Track IDs from the current request as well so a malformed
        # batch cannot apply the same logical change twice.
        seen_change_ids.add(ch.change_id)

        entity, op, record = (
            (ch.entity or "").strip().lower(),
            (ch.op or "").strip().lower(),
            (ch.record or {}),
        )
        if entity not in ENTITY_MODELS:
            result = _receipt_err(
                db,
                errors,
                ch,
                user_id,
                project_id,
                "unknown_entity",
                failure_kind="validation",
            )
            results.append(result)
            batch_results[ch.change_id] = result
            wrote += 1
            _evict_if_needed()
            continue
        if op not in OPS:
            result = _receipt_err(
                db,
                errors,
                ch,
                user_id,
                project_id,
                "unknown_op",
                failure_kind="validation",
            )
            results.append(result)
            batch_results[ch.change_id] = result
            wrote += 1
            _evict_if_needed()
            continue

        # Treat 'deleted' as a privileged soft-delete on upsert.
        if entity in {"risk", "opportunity"} and op == "upsert":
            st = str((record or {}).get("status") or "").lower().strip()
            if st == RiskStatus.deleted.value or bool((record or {}).get("is_deleted")):
                try:
                    ensure_role_at_least(role, "manager")
                except HTTPException:
                    result = _receipt_err(
                        db,
                        errors,
                        ch,
                        user_id,
                        project_id,
                        "insufficient_permissions",
                        failure_kind="permission",
                    )
                    results.append(result)
                    batch_results[ch.change_id] = result
                    wrote += 1
                    _evict_if_needed()
                    continue

        try:
            ensure_role_at_least(role, _min_role_for_change(entity, op))
        except HTTPException:
            result = _receipt_err(
                db,
                errors,
                ch,
                user_id,
                project_id,
                "insufficient_permissions",
                failure_kind="permission",
            )
            results.append(result)
            batch_results[ch.change_id] = result
            wrote += 1
            _evict_if_needed()
            continue

        try:
            with db.begin_nested():
                eid = (
                    _apply_upsert(
                        db,
                        user_id,
                        project_id,
                        entity,
                        ch.base_version,
                        record,
                        ch.change_id,
                    )
                    if op == "upsert"
                    else _apply_delete(
                        db,
                        user_id,
                        project_id,
                        entity,
                        ch.base_version,
                        record,
                        ch.change_id,
                    )
                )
                _store_receipt(
                    db,
                    ch.change_id,
                    user_id,
                    project_id,
                    entity,
                    eid,
                    op,
                    "accepted",
                    {"entity_id": str(eid)},
                )
                db.flush()
            accepted += 1
            result = _change_result(
                change_id=ch.change_id,
                status="accepted",
                entity=entity,
                op=op,
                entity_id=eid,
                response={"entity_id": str(eid)},
            )
            results.append(result)
            batch_results[ch.change_id] = result
            wrote += 1
            _evict_if_needed()

        except ConflictError as exc:
            conflict_response = {
                "reason": exc.reason,
                "server_version": exc.server_version,
                "server_record": exc.server_record,
                "server_updated_at": exc.server_updated_at,
                "failure_kind": "conflict",
                "retryable": False,
            }
            _store_receipt(
                db,
                ch.change_id,
                user_id,
                project_id,
                entity,
                exc.entity_id,
                op,
                "conflict",
                conflict_response,
            )
            result = _change_result(
                change_id=ch.change_id,
                status="conflict",
                entity=entity,
                op=op,
                entity_id=exc.entity_id,
                response=conflict_response,
            )
            results.append(result)
            batch_results[ch.change_id] = result
            _append_legacy_outcome(result, conflicts, errors)
            wrote += 1
            _evict_if_needed()

        except HTTPException as exc:
            failure_kind, retryable = _classify_http_failure(exc.status_code)
            result = _receipt_err(
                db,
                errors,
                ch,
                user_id,
                project_id,
                "http_error",
                str(exc.detail),
                failure_kind=failure_kind,
                retryable=retryable,
                store_receipt=not retryable,
            )
            results.append(result)
            batch_results[ch.change_id] = result
            if not retryable:
                wrote += 1
                _evict_if_needed()

        except Exception:
            logging.getLogger("riskapp_server.sync").exception(
                "Unexpected error processing sync change %s", ch.change_id
            )
            result = _receipt_err(
                db,
                errors,
                ch,
                user_id,
                project_id,
                "internal_error",
                failure_kind="transient",
                retryable=True,
                store_receipt=False,
            )
            results.append(result)
            batch_results[ch.change_id] = result

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logging.getLogger("riskapp_server.sync").exception("Failed to commit sync push")
        raise HTTPException(status_code=500, detail="Sync push commit failed") from exc

    return {
        "accepted": accepted,
        "duplicates": duplicates,
        "duplicate_change_ids": dup_ids,
        "conflicts": conflicts,
        "errors": errors,
        "results": results,
        "server_time": utcnow(),
    }


def _store_receipt(
    db: Session,
    change_id: uuid.UUID,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    entity: str,
    entity_id: uuid.UUID | None,
    op: str,
    status: str,
    response: dict[str, Any],
) -> None:
    db.add(
        SyncReceipt(
            change_id=change_id,
            user_id=user_id,
            project_id=project_id,
            entity=entity,
            entity_id=entity_id,
            op=op,
            status=status,
            response=response or {},
            processed_at=utcnow(),
        )
    )


def _classify_http_failure(status_code: int) -> tuple[str, bool]:
    """Map an operation-level HTTP failure to a stable client action."""
    status = int(status_code or 0)
    if status == 401:
        return "authentication", False
    if status == 403:
        return "permission", False
    if status in {408, 425, 429} or status >= 500:
        return "transient", True
    return "validation", False


def _receipt_err(
    db: Session,
    errors: list[dict[str, Any]],
    ch: SyncChange,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    reason: str,
    detail: str | None = None,
    *,
    failure_kind: str = "error",
    retryable: bool = False,
    store_receipt: bool = True,
) -> dict[str, Any]:
    entity = (ch.entity or "").strip().lower()
    op = (ch.op or "").strip().lower()
    entity_id = _maybe_entity_id(ch.record or {})
    resp: dict[str, Any] = {
        "reason": reason,
        "failure_kind": failure_kind,
        "retryable": bool(retryable),
    }
    if detail:
        resp["detail"] = detail

    if store_receipt:
        with db.begin_nested():
            _store_receipt(
                db,
                ch.change_id,
                user_id,
                project_id,
                entity,
                entity_id,
                op,
                "error",
                resp,
            )
            db.flush()

    result = _change_result(
        change_id=ch.change_id,
        status="error",
        entity=entity,
        op=op,
        entity_id=entity_id,
        response=resp,
    )
    _append_legacy_outcome(result, [], errors)
    return result


def _maybe_entity_id(record: dict[str, Any]) -> uuid.UUID | None:
    rid = record.get("id")
    try:
        return uuid.UUID(str(rid)) if rid else None
    except (ValueError, TypeError):
        logging.getLogger(__name__).debug("UUID conversion failed", exc_info=True)
        return None


def _parse_record(entity: str, record: dict) -> dict:
    try:
        Schema = ENTITY_REGISTRY[entity]["schema"]
        val = Schema(**record).model_dump(exclude_unset=True)

        if entity in {"action", "assessment"}:
            rid, oid = val.pop("risk_id", None), val.pop("opportunity_id", None)
            if entity == "action" and not val.get("item_id") and bool(rid) == bool(oid):
                raise HTTPException(
                    status_code=400,
                    detail="Action must have exactly one of risk_id/opportunity_id",
                )
            if not val.get("item_id"):
                val["item_id"] = rid or oid
            # If the client sets a target field, enforce the item type.
            val["_target_type"] = "risk" if rid else ("opportunity" if oid else None)
        # Normalize status=deleted into a soft-delete flag.
        if entity in {"risk", "opportunity"}:
            st = val.get("status")
            st_s = str(getattr(st, "value", st) or "").lower().strip()
            if st_s == RiskStatus.deleted.value:
                val["is_deleted"] = True

        return val
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Validation error: {exc}") from exc


def _validate_relationships(
    db: Session, project_id: uuid.UUID, entity: str, val: dict, obj: Any = None
) -> None:
    """Validate parent/child relationships."""
    config = ENTITY_REGISTRY[entity]
    if "parent_model" in config:
        parent_field = config["parent_field"]
        target_parent = (
            val.get(parent_field)
            if obj is None
            else (val.get(parent_field) or getattr(obj, parent_field))
        )

        if not target_parent and obj is None:
            raise HTTPException(status_code=400, detail=f"{parent_field} is required")

        if target_parent:
            _ensure_item_in_project(
                db,
                project_id,
                parse_uuid(target_parent, parent_field),
                expected_type=val.get("_target_type"),
            )

    if entity == "action" and val.get("item_id"):
        _ensure_item_in_project(
            db,
            project_id,
            parse_uuid(val["item_id"], "item_id"),
            expected_type=val.get("_target_type"),
        )


def _ensure_item_in_project(
    db: Session,
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    *,
    expected_type: str | None = None,
) -> None:
    t = db.execute(
        select(Item.type).where(
            Item.project_id == project_id,
            Item.id == item_id,
        )
    ).scalar()
    if not t or (expected_type and t != expected_type):
        raise HTTPException(status_code=400, detail="Target not found in project")


def _fetch_obj(db: Session, entity: str, entity_id: uuid.UUID, project_id: uuid.UUID):
    Model = ENTITY_MODELS[entity]
    config = ENTITY_REGISTRY[entity]

    if "parent_model" not in config:
        return (
            db.execute(
                select(Model).where(
                    Model.id == entity_id, Model.project_id == project_id
                )
            )
            .scalars()
            .first()
        )

    # Parent-scoped entity.
    return (
        db.execute(
            select(Model)
            .join(Item, Model.item_id == Item.id)
            .where(Model.id == entity_id, Item.project_id == project_id)
        )
        .scalars()
        .first()
    )


def _check_base_version(
    obj: Any,
    base_version: Any,
    entity_id: uuid.UUID,
    server_record: dict[str, Any],
) -> int:
    server_version = getattr(obj, "version", None)
    if base_version is None:
        raise ConflictError(
            "base_version_required", entity_id, server_version, server_record
        )
    try:
        bv = int(base_version)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="base_version must be int") from exc
    if bv < 1:
        raise ConflictError(
            "base_version_required", entity_id, server_version, server_record
        )
    if server_version != bv:
        raise ConflictError(
            "version_mismatch", entity_id, server_version, server_record
        )
    return bv


def _version_scope(
    entity: str,
    entity_id: uuid.UUID,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
) -> tuple[Any, list[Any]]:
    Model = ENTITY_MODELS[entity]
    where: list[Any] = [Model.id == entity_id]
    if entity in {"risk", "opportunity"}:
        where.extend((Model.project_id == project_id, Model.type == entity))
    elif entity == "assessment":
        where.extend(
            (
                Model.assessor_user_id == user_id,
                Model.item_id.in_(
                    select(Item.id).where(Item.project_id == project_id)
                ),
            )
        )
    else:
        where.append(Model.project_id == project_id)
    return Model, where


def _current_server_state(
    db: Session,
    entity: str,
    entity_id: uuid.UUID,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
) -> tuple[int | None, dict[str, Any] | None]:
    Model, where = _version_scope(entity, entity_id, project_id, user_id)
    obj = (
        db.execute(
            select(Model)
            .where(*where)
            .execution_options(populate_existing=True)
        )
        .scalars()
        .first()
    )
    if obj is None:
        return None, None
    version = getattr(obj, "version", None)
    return (
        int(version) if version is not None else None,
        model_to_sync_dict(db, entity, obj),
    )


def _claim_base_version(
    db: Session,
    entity: str,
    entity_id: uuid.UUID,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    base_version: int,
) -> None:
    """Atomically advance one row only when its version still matches."""
    Model, where = _version_scope(entity, entity_id, project_id, user_id)
    result = db.execute(
        update(Model)
        .where(*where, Model.version == base_version)
        .values(version=Model.version + 1, updated_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        server_version, server_record = _current_server_state(
            db, entity, entity_id, project_id, user_id
        )
        raise ConflictError(
            "version_mismatch",
            entity_id,
            server_version,
            server_record,
        )


def _validate_existing_obj(
    db: Session,
    obj: Any,
    entity: str,
    entity_id: uuid.UUID,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    base_version: Any,
) -> int:
    """Validate access and version checks."""
    if entity in {"risk", "opportunity"} and getattr(obj, "type", None) != entity:
        raise ConflictError(
            "type_mismatch",
            entity_id,
            getattr(obj, "version", None),
            model_to_sync_dict(db, entity, obj),
        )

    if entity == "assessment" and getattr(obj, "assessor_user_id", None) != user_id:
        raise HTTPException(
            status_code=403, detail="Cannot modify another user's assessment"
        )

    return _check_base_version(
        obj,
        base_version,
        entity_id,
        model_to_sync_dict(db, entity, obj),
    )


def _apply_upsert(
    db: Session,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    entity: str,
    base_version: Any,
    record: dict[str, Any],
    change_id: uuid.UUID,
) -> uuid.UUID:
    entity_id = parse_uuid(record.get("id"), "record.id")
    obj = _fetch_obj(db, entity, entity_id, project_id)

    if obj is None:
        obj = _create_new(db, user_id, project_id, entity, entity_id, record)
        _audit(
            db,
            user_id,
            project_id,
            change_id,
            entity,
            entity_id,
            "upsert",
            None,
            model_to_dict(obj),
        )
        return entity_id

    expected_version = _validate_existing_obj(
        db, obj, entity, entity_id, project_id, user_id, base_version
    )
    before = model_to_dict(obj)
    _claim_base_version(
        db,
        entity,
        entity_id,
        project_id,
        user_id,
        expected_version,
    )
    _update_existing(db, user_id, project_id, entity, obj, record)
    _audit(
        db,
        user_id,
        project_id,
        change_id,
        entity,
        entity_id,
        "upsert",
        before,
        model_to_dict(obj),
    )
    return entity_id


def _apply_delete(
    db: Session,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    entity: str,
    base_version: Any,
    record: dict[str, Any],
    change_id: uuid.UUID,
) -> uuid.UUID:
    entity_id = parse_uuid(record.get("id"), "record.id")
    obj = _fetch_obj(db, entity, entity_id, project_id)
    if not obj:
        return entity_id

    expected_version = _validate_existing_obj(
        db, obj, entity, entity_id, project_id, user_id, base_version
    )
    before = model_to_dict(obj)
    _claim_base_version(
        db,
        entity,
        entity_id,
        project_id,
        user_id,
        expected_version,
    )
    obj.soft_delete(utcnow())
    _audit(
        db,
        user_id,
        project_id,
        change_id,
        entity,
        entity_id,
        "delete",
        before,
        model_to_dict(obj),
    )
    return entity_id


def _create_new(
    db: Session,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    entity: str,
    entity_id: uuid.UUID,
    record: dict[str, Any],
):
    now = utcnow()
    val = _parse_record(entity, record)
    Model = ENTITY_MODELS[entity]
    config = ENTITY_REGISTRY[entity]
    defaults = dict(config.get("defaults") or {})

    common = {"id": entity_id, "version": 1, "updated_at": now, "created_at": now}
    if entity != "assessment":
        common |= {"project_id": project_id, "created_by": user_id}

    # Apply defaults before record values.
    common |= defaults

    _validate_relationships(db, project_id, entity, val)

    if "parent_model" in config:
        # Assessments belong to the assessor.
        common |= {"assessor_user_id": user_id}

    obj = Model(**common)

    for k, v in val.items():
        if k.startswith("_"):
            continue
        if hasattr(obj, k) and k not in {"score", "assessor_user_id"}:
            setattr(obj, k, getattr(v, "value", v))

    _maybe_recalculate_scores(obj)
    db.add(obj)
    return obj


def _update_existing(
    db: Session,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    entity: str,
    obj: Any,
    record: dict[str, Any],
) -> None:
    now = utcnow()
    val = _parse_record(entity, record)
    _validate_relationships(db, project_id, entity, val, obj)

    for k, v in val.items():
        if k.startswith("_"):
            continue
        if hasattr(obj, k) and k not in {"score", "assessor_user_id"}:
            v = getattr(v, "value", v)
            if k == "status" and hasattr(obj, "change_status"):
                obj.change_status(v, now)
            else:
                setattr(obj, k, v)

    did_soft_delete = False
    if val.get("is_deleted") is not None:
        if bool(val.get("is_deleted")):
            obj.soft_delete(now)
            did_soft_delete = True
        else:
            obj.is_deleted = False

    _maybe_recalculate_scores(obj)
    obj.updated_at = now
    if not did_soft_delete:
        obj.version = int(getattr(obj, "version", 0)) + 1


def _audit(
    db: Session,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    change_id: uuid.UUID,
    entity: str,
    entity_id: uuid.UUID,
    op: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            project_id=project_id,
            change_id=change_id,
            entity=entity,
            entity_id=entity_id,
            op=op,
            before=before,
            after=after,
            ts=utcnow(),
        )
    )
