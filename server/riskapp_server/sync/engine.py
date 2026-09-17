# pylint: disable=too-many-lines
# The sync engine is organized into helpers; further file splitting is separate work.
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, NotRequired, TypedDict, cast

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.inspection import inspect as sa_inspect
from sqlalchemy.orm import Session

from riskapp_server.core.config import MAX_SYNC_PULL_PER_ENTITY, SYNC_PUSH_EXPUNGE_EVERY
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
    SyncProjectState,
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


class EntityConfig(TypedDict):
    model: type[Any]
    schema: type[BaseModel]
    manager_delete: bool
    defaults: dict[str, Any]
    parent_model: NotRequired[type[Any]]
    parent_field: NotRequired[str]


ENTITY_REGISTRY: dict[str, EntityConfig] = {
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

ENTITY_MODELS = {
    key: config["model"] for key, config in ENTITY_REGISTRY.items()
}
OPS = {"upsert", "delete"}


# Keep the public 'field' parameter name for existing keyword callers.
# pylint: disable-next=redefined-outer-name
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
        if k == "change_sequence":
            # Feed ordering is transport metadata, not client-editable state.
            continue
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


def _parse_sequence_cursor(
    cur: str | None, *, default_since: int, snapshot_sequence: int
) -> int:
    if not cur:
        return default_since
    try:
        prefix, value = cur.split(":", 1)
        sequence = int(value)
        if prefix != "seq" or not default_since <= sequence <= snapshot_sequence:
            raise ValueError("cursor is outside the synchronization snapshot")
        return sequence
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid cursor") from exc


def _encode_sequence_cursor(sequence: int) -> str:
    return f"seq:{sequence}"


@dataclass(frozen=True)
class _PullContext:
    db: Session
    project_id: uuid.UUID
    since: datetime
    snapshot_time: datetime
    limit: int | None
    hard_cap: int | None
    cursors: dict[str, str]
    server_sequence: int
    since_sequence: int | None
    snapshot_sequence: int | None


@dataclass(frozen=True)
class _PullPage:
    rows: list[Any]
    has_more: bool
    cursor: str


def _prepare_pull_context(
    db: Session,
    project_id: uuid.UUID,
    since: datetime,
    limit_per_entity: int | None,
    cursors: dict[str, str] | None,
    snapshot_time: datetime | None,
    since_sequence: int | None,
    snapshot_sequence: int | None,
) -> _PullContext:
    request_time = _naive_utc(utcnow())
    normalized_since = _naive_utc(since)
    normalized_snapshot = (
        _naive_utc(snapshot_time) if snapshot_time is not None else request_time
    )
    if normalized_snapshot < normalized_since:
        raise HTTPException(status_code=400, detail="snapshot_time precedes since")
    if normalized_snapshot > request_time:
        raise HTTPException(status_code=400, detail="snapshot_time is in the future")

    current_sequence_value = db.execute(
        select(SyncProjectState.last_sequence).where(
            SyncProjectState.project_id == project_id
        )
    ).scalar_one_or_none()
    if current_sequence_value is None:
        raise HTTPException(
            status_code=500, detail="Project synchronization state is missing"
        )
    current_sequence = int(current_sequence_value)

    normalized_snapshot_sequence: int | None = None
    if since_sequence is None:
        if snapshot_sequence is not None:
            raise HTTPException(
                status_code=400, detail="snapshot_sequence requires since_sequence"
            )
    else:
        since_sequence = int(since_sequence)
        if since_sequence < 0:
            raise HTTPException(
                status_code=400, detail="since_sequence must be nonnegative"
            )
        normalized_snapshot_sequence = (
            current_sequence if snapshot_sequence is None else int(snapshot_sequence)
        )
        if normalized_snapshot_sequence < since_sequence:
            raise HTTPException(
                status_code=400, detail="snapshot_sequence precedes since_sequence"
            )
        if normalized_snapshot_sequence > current_sequence:
            raise HTTPException(
                status_code=400, detail="snapshot_sequence is ahead of the server"
            )

    hard_cap = MAX_SYNC_PULL_PER_ENTITY if limit_per_entity is None else None
    limit = hard_cap if limit_per_entity is None else limit_per_entity
    return _PullContext(
        db=db,
        project_id=project_id,
        since=normalized_since,
        snapshot_time=normalized_snapshot,
        limit=limit,
        hard_cap=hard_cap,
        cursors=cursors or {},
        server_sequence=current_sequence,
        since_sequence=since_sequence,
        snapshot_sequence=normalized_snapshot_sequence,
    )


def _pull_window(
    ctx: _PullContext, model: Any, key: str
) -> tuple[tuple[Any, ...], tuple[Any, ...], str]:
    if ctx.since_sequence is not None:
        if ctx.snapshot_sequence is None:  # pragma: no cover - context invariant
            raise RuntimeError("Sequence pull is missing its snapshot")
        sequence = _parse_sequence_cursor(
            ctx.cursors.get(key),
            default_since=ctx.since_sequence,
            snapshot_sequence=ctx.snapshot_sequence,
        )
        return (
            (
                model.change_sequence > sequence,
                model.change_sequence <= ctx.snapshot_sequence,
            ),
            (model.change_sequence.asc(),),
            _encode_sequence_cursor(sequence),
        )

    ts, last_id = _parse_cursor(
        ctx.cursors.get(key),
        default_since=ctx.since,
        snapshot_time=ctx.snapshot_time,
    )
    return (
        (
            model.updated_at <= ctx.snapshot_time,
            or_(
                model.updated_at > ts,
                (model.updated_at == ts) & (model.id > last_id),
            ),
        ),
        (model.updated_at.asc(), model.id.asc()),
        _encode_cursor(ts, last_id),
    )


def _finish_pull_page(
    rows: list[Any],
    *,
    ctx: _PullContext,
    limit: int | None,
    base_cursor: str,
    joined: bool = False,
) -> _PullPage:
    has_more = bool(limit and len(rows) > limit)
    if has_more:
        rows = rows[:limit]
    last = rows[-1][0] if rows and joined else (rows[-1] if rows else None)
    if last is None:
        cursor = base_cursor
    elif ctx.since_sequence is not None:
        cursor = _encode_sequence_cursor(int(last.change_sequence))
    else:
        cursor = _encode_cursor(last.updated_at, last.id)
    return _PullPage(rows=rows, has_more=has_more, cursor=cursor)


def _pull_item_page(ctx: _PullContext, item_type: str, key: str) -> _PullPage:
    window, ordering, base_cursor = _pull_window(ctx, Item, key)
    query = (
        select(Item)
        .where(
            Item.project_id == ctx.project_id,
            Item.type == item_type,
            *window,
        )
        .order_by(*ordering)
    )
    rows = ctx.db.execute(
        query.limit(ctx.limit + 1) if ctx.limit else query
    ).scalars().all()
    return _finish_pull_page(
        list(rows),
        ctx=ctx,
        limit=ctx.limit,
        base_cursor=base_cursor,
    )


def _pull_joined_page(
    ctx: _PullContext,
    model: Any,
    cursor_key: str,
    project_filter: Any,
) -> _PullPage:
    window, ordering, base_cursor = _pull_window(ctx, model, cursor_key)
    query = (
        select(model, Item.type)
        .join(Item, model.item_id == Item.id)
        .where(
            project_filter,
            *window,
        )
        .order_by(*ordering)
    )
    rows = ctx.db.execute(
        query.limit(ctx.limit + 1) if ctx.limit else query
    ).all()
    return _finish_pull_page(
        list(rows),
        ctx=ctx,
        limit=ctx.limit,
        base_cursor=base_cursor,
        joined=True,
    )


def _pull_simple_page(
    ctx: _PullContext,
    model: Any,
    cursor_key: str,
    project_filter: Any,
) -> _PullPage:
    window, ordering, base_cursor = _pull_window(ctx, model, cursor_key)
    query = (
        select(model)
        .where(
            project_filter,
            *window,
        )
        .order_by(*ordering)
    )
    rows = ctx.db.execute(
        query.limit(ctx.limit + 1) if ctx.limit else query
    ).scalars().all()
    return _finish_pull_page(
        list(rows),
        ctx=ctx,
        limit=ctx.limit,
        base_cursor=base_cursor,
    )


def _serialize_action_rows(rows: list[Any]) -> list[dict[str, Any]]:
    return [
        ActionOut(
            id=action.id,
            project_id=action.project_id,
            risk_id=action.item_id if item_type == "risk" else None,
            opportunity_id=action.item_id if item_type == "opportunity" else None,
            kind=action.kind,
            title=action.title,
            description=action.description,
            status=action.status,
            owner_user_id=action.owner_user_id,
            updated_at=action.updated_at,
            version=action.version,
            is_deleted=action.is_deleted,
        ).model_dump(mode="json")
        for action, item_type in rows
    ]


def _serialize_assessment_rows(rows: list[Any]) -> list[dict[str, Any]]:
    assessments: list[dict[str, Any]] = []
    for assessment, item_type in rows:
        record = model_to_dict(assessment)
        if "item_id" not in record and "risk_id" in record:
            record["item_id"] = record["risk_id"]
        item_id = record.get("item_id")
        record["risk_id"] = item_id if item_type == "risk" else None
        record["opportunity_id"] = item_id if item_type == "opportunity" else None
        assessments.append(record)
    return assessments


def pull_since(
    db: Session,
    project_id: uuid.UUID,
    since: datetime,
    *,
    limit_per_entity: int | None = None,
    cursors: dict[str, str] | None = None,
    snapshot_time: datetime | None = None,
    since_sequence: int | None = None,
    snapshot_sequence: int | None = None,
) -> dict[str, Any]:
    ctx = _prepare_pull_context(
        db,
        project_id,
        since,
        limit_per_entity,
        cursors,
        snapshot_time,
        since_sequence,
        snapshot_sequence,
    )
    risks = _pull_item_page(ctx, "risk", "risks")
    opportunities = _pull_item_page(ctx, "opportunity", "opportunities")
    actions = _pull_joined_page(
        ctx, Action, "actions", Action.project_id == project_id
    )
    assessments = _pull_joined_page(
        ctx, Assessment, "assessments", Item.project_id == project_id
    )
    helpdesk = _pull_simple_page(
        ctx,
        HelpDeskTicket,
        "helpdesk_tickets",
        HelpDeskTicket.project_id == project_id,
    )

    pages = {
        "risks": risks,
        "opportunities": opportunities,
        "actions": actions,
        "assessments": assessments,
        "helpdesk_tickets": helpdesk,
    }

    has_more = {key: page.has_more for key, page in pages.items()}

    out: dict[str, Any] = {
        "server_time": ctx.snapshot_time,\
        "server_sequence": (
            ctx.snapshot_sequence
            if ctx.snapshot_sequence is not None
            else ctx.server_sequence
        ),
        "risks": [model_to_dict(row) for row in risks.rows],
        "opportunities": [model_to_dict(row) for row in opportunities.rows],
        "actions": _serialize_action_rows(actions.rows),
        "assessments": _serialize_assessment_rows(assessments.rows),
        "helpdesk_tickets": [
            HelpDeskTicketOut.model_validate(row).model_dump(mode="json")
            for row in helpdesk.rows
        ],
    }

    if ctx.hard_cap and any(has_more.values()):
        raise HTTPException(
            status_code=413,
            detail=("Sync pull too large. Paginate using limit_per_entity + cursors."),
        )

    if limit_per_entity is not None:
        out["has_more"] = has_more
        out["cursors"] = {key: page.cursor for key, page in pages.items()}
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


def _lock_receipt_ids(db: Session, changes: list[SyncChange]) -> None:
    """Serialize globally unique change IDs even across different projects."""
    get_bind = getattr(db, "get_bind", None)
    if not callable(get_bind):
        return
    bind = get_bind()
    if getattr(getattr(bind, "dialect", None), "name", None) != "postgresql":
        return  # SQLite already holds a global writer reservation.
    # Sorted acquisition avoids lock-order deadlocks for multi-change batches.
    for change_id in sorted({ch.change_id for ch in changes}):
        key = int.from_bytes(change_id.bytes[:8], "big", signed=True)
        db.execute(select(func.pg_advisory_xact_lock(key)))


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


def _payload_hash(change: SyncChange) -> str:
    """Hash the parsed, key-order-independent request, excluding its receipt ID."""
    payload = change.model_dump(mode="json", exclude={"change_id"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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


@dataclass
class _PushContext:
    db: Session
    user_id: uuid.UUID
    project_id: uuid.UUID
    role: str
    existing_receipts: dict[uuid.UUID, SyncReceipt]
    seen_change_ids: set[uuid.UUID]
    accepted: int = 0
    duplicates: int = 0
    duplicate_change_ids: list[str] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    batch_results: dict[uuid.UUID, dict[str, Any]] = field(default_factory=dict)
    batch_hashes: dict[uuid.UUID, str] = field(default_factory=dict)
    wrote: int = 0


def _load_existing_receipts(
    db: Session,
    changes: list[SyncChange],
) -> dict[uuid.UUID, SyncReceipt]:
    change_ids = [change.change_id for change in changes]
    if not change_ids:
        return {}
    receipts = (
        db.execute(
            select(SyncReceipt).where(
                SyncReceipt.change_id.in_(change_ids),
            )
        )
        .scalars()
        .all()
    )
    return {receipt.change_id: receipt for receipt in receipts}


def _prepare_push_context(
    db: Session,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    role: str,
    changes: list[SyncChange],
) -> _PushContext:
    existing_receipts = _load_existing_receipts(db, changes)
    return _PushContext(
        db=db,
        user_id=user_id,
        project_id=project_id,
        role=role,
        existing_receipts=existing_receipts,
        seen_change_ids=set(existing_receipts),
    )


def _evict_push_identity_map_if_needed(ctx: _PushContext) -> None:
    if (
        SYNC_PUSH_EXPUNGE_EVERY
        and ctx.wrote
        and ctx.wrote % SYNC_PUSH_EXPUNGE_EVERY == 0
    ):
        # Keep the transaction atomic and limit identity-map growth.
        ctx.db.flush()
        ctx.db.expunge_all()


def _record_push_result(
    ctx: _PushContext,
    change: SyncChange,
    result: dict[str, Any],
    *,
    persisted: bool,
) -> None:
    ctx.results.append(result)
    ctx.batch_results[change.change_id] = result
    if persisted:
        ctx.wrote += 1
        _evict_push_identity_map_if_needed(ctx)


def _record_duplicate(ctx: _PushContext, change: SyncChange) -> None:
    receipt = ctx.existing_receipts.get(change.change_id)
    if receipt and (
        receipt.user_id != ctx.user_id or receipt.project_id != ctx.project_id
    ):
        reason = "change_id_in_use"
    elif receipt and receipt.payload_hash is None:
        reason = "receipt_unverifiable"
    elif (
        receipt.payload_hash if receipt else ctx.batch_hashes.get(change.change_id)
    ) != _payload_hash(change):
        reason = "change_id_payload_mismatch"
    else:
        reason = None
    if reason:
        result = _change_result(
            change_id=change.change_id,
            status="error",
            entity=change.entity,
            op=change.op,
            entity_id=_maybe_entity_id(change.record),
            response={
                "reason": reason, "failure_kind": "validation", "retryable": False
            },
        )
        ctx.results.append(result)
        _append_legacy_outcome(result, ctx.conflicts, ctx.errors)
        return
    ctx.duplicates += 1
    ctx.duplicate_change_ids.append(str(change.change_id))
    replay = (
        _receipt_result(receipt)
        if receipt is not None
        else {**ctx.batch_results[change.change_id], "replayed": True}
    )
    ctx.results.append(replay)
    _append_legacy_outcome(replay, ctx.conflicts, ctx.errors)


def _reject_push_change(
    ctx: _PushContext,
    change: SyncChange,
    reason: str,
    detail: str | None = None,
    *,
    failure_kind: str,
    retryable: bool = False,
    store_receipt: bool = True,
) -> None:
    result = _receipt_err(
        ctx.db,
        ctx.errors,
        change,
        ctx.user_id,
        ctx.project_id,
        reason,
        detail,
        failure_kind=failure_kind,
        retryable=retryable,
        store_receipt=store_receipt,
    )
    _record_push_result(ctx, change, result, persisted=store_receipt)


def _is_privileged_soft_delete_transition(
    ctx: _PushContext,
    entity: str,
    op: str,
    record: dict[str, Any],
) -> bool:
    if not ENTITY_REGISTRY[entity]["manager_delete"] or op != "upsert":
        return False
    if entity in {"risk", "opportunity"}:
        status = str(record.get("status") or "").lower().strip()
        if status == RiskStatus.deleted.value:
            return True
    if bool(record.get("is_deleted")):
        return True
    if "is_deleted" not in record:
        return False

    # A false value is harmless on an active row but is an undelete on a
    # tombstone. Check the persisted transition instead of treating every
    # ordinary upsert (whose payload may include false) as manager-only.
    entity_id = _maybe_entity_id(record)
    if entity_id is None:
        return False
    existing = _fetch_obj(ctx.db, entity, entity_id, ctx.project_id)
    return bool(existing is not None and getattr(existing, "is_deleted", False))


def _authorize_push_change(
    ctx: _PushContext,
    change: SyncChange,
    entity: str,
    op: str,
    record: dict[str, Any],
) -> bool:
    try:
        if _is_privileged_soft_delete_transition(ctx, entity, op, record):
            ensure_role_at_least(ctx.role, "manager")
        ensure_role_at_least(ctx.role, _min_role_for_change(entity, op))
        return True
    except HTTPException:
        _reject_push_change(
            ctx,
            change,
            "insufficient_permissions",
            failure_kind="permission",
        )
        return False


def _apply_push_change(
    ctx: _PushContext,
    change: SyncChange,
    entity: str,
    op: str,
    record: dict[str, Any],
) -> None:
    with ctx.db.begin_nested():
        entity_id = (
            _apply_upsert(
                ctx.db,
                ctx.user_id,
                ctx.project_id,
                entity,
                change.base_version,
                record,
                change.change_id,
            )
            if op == "upsert"
            else _apply_delete(
                ctx.db,
                ctx.user_id,
                ctx.project_id,
                entity,
                change.base_version,
                record,
                change.change_id,
            )
        )
        # Flush the mutation before reading it back so the receipt carries the
        # canonical version and any server-assigned fields (notably item code).
        ctx.db.flush()
        server_version, server_record = _current_server_state(
            ctx.db,
            entity,
            entity_id,
            ctx.project_id,
            ctx.user_id,
        )
        response = {
            "entity_id": str(entity_id),
            "server_version": server_version,
            "server_record": server_record,
            "server_updated_at": (
                str(server_record.get("updated_at"))
                if server_record and server_record.get("updated_at") is not None
                else None
            ),
        }
        _store_receipt(
            ctx.db,
            change.change_id,
            ctx.user_id,
            ctx.project_id,
            entity,
            entity_id,
            op,
            "accepted",
            response,
            _payload_hash(change),
        )
        ctx.db.flush()

    ctx.accepted += 1
    result = _change_result(
        change_id=change.change_id,
        status="accepted",
        entity=entity,
        op=op,
        entity_id=entity_id,
        response=response,
    )
    _record_push_result(ctx, change, result, persisted=True)


def _record_push_conflict(
    ctx: _PushContext,
    change: SyncChange,
    entity: str,
    op: str,
    conflict: ConflictError,
) -> None:
    response = {
        "reason": conflict.reason,
        "server_version": conflict.server_version,
        "server_record": conflict.server_record,
        "server_updated_at": conflict.server_updated_at,
        "failure_kind": "conflict",
        "retryable": False,
    }
    _store_receipt(
        ctx.db,
        change.change_id,
        ctx.user_id,
        ctx.project_id,
        entity,
        conflict.entity_id,
        op,
        "conflict",
        response,
        _payload_hash(change),
    )
    result = _change_result(
        change_id=change.change_id,
        status="conflict",
        entity=entity,
        op=op,
        entity_id=conflict.entity_id,
        response=response,
    )
    _append_legacy_outcome(result, ctx.conflicts, ctx.errors)
    _record_push_result(ctx, change, result, persisted=True)


def _process_new_push_change(ctx: _PushContext, change: SyncChange) -> None:
    entity = change.entity.strip().lower()
    op = change.op.strip().lower()
    record = change.record or {}
    if entity not in ENTITY_MODELS:
        _reject_push_change(
            ctx, change, "unknown_entity", failure_kind="validation"
        )
        return
    if op not in OPS:
        _reject_push_change(ctx, change, "unknown_op", failure_kind="validation")
        return
    if not _authorize_push_change(ctx, change, entity, op, record):
        return

    try:
        _apply_push_change(ctx, change, entity, op, record)
    except ConflictError as exc:
        _record_push_conflict(ctx, change, entity, op, exc)
    except HTTPException as exc:
        failure_kind, retryable = _classify_http_failure(exc.status_code)
        _reject_push_change(
            ctx,
            change,
            "http_error",
            str(exc.detail),
            failure_kind=failure_kind,
            retryable=retryable,
            store_receipt=not retryable,
        )
    except IntegrityError:
        logging.getLogger("riskapp_server.sync").info(
            "Rejected sync change %s because it violates a database constraint",
            change.change_id,
        )
        _reject_push_change(
            ctx,
            change,
            "constraint_violation",
            "Change violates a database constraint",
            failure_kind="validation",
        )
    # This boundary converts an unexpected per-change failure to a retryable result.
    # pylint: disable-next=broad-exception-caught
    except Exception:
        logging.getLogger("riskapp_server.sync").exception(
            "Unexpected error processing sync change %s", change.change_id
        )
        _reject_push_change(
            ctx,
            change,
            "internal_error",
            failure_kind="transient",
            retryable=True,
            store_receipt=False,
        )


def _process_push_change(ctx: _PushContext, change: SyncChange) -> None:
    if change.change_id in ctx.seen_change_ids:
        _record_duplicate(ctx, change)
        return
    # The initial receipt query cannot see receipts written later in this
    # transaction, so track IDs from the request as they are encountered.
    ctx.seen_change_ids.add(change.change_id)
    ctx.batch_hashes[change.change_id] = _payload_hash(change)
    _process_new_push_change(ctx, change)


def _commit_push(ctx: _PushContext) -> None:
    try:
        ctx.db.commit()
    except Exception as exc:
        ctx.db.rollback()
        logging.getLogger("riskapp_server.sync").exception("Failed to commit sync push")
        raise HTTPException(status_code=500, detail="Sync push commit failed") from exc


def _push_response(ctx: _PushContext) -> dict[str, Any]:
    return {
        "accepted": ctx.accepted,
        "duplicates": ctx.duplicates,
        "duplicate_change_ids": ctx.duplicate_change_ids,
        "conflicts": ctx.conflicts,
        "errors": ctx.errors,
        "results": ctx.results,
        "server_time": utcnow(),
    }


def push_changes(
    db: Session, user_id: uuid.UUID, project_id: uuid.UUID, changes: list[SyncChange]
) -> dict[str, Any]:
    if changes:
        _begin_push_transaction(db)
        _lock_receipt_ids(db, changes)
        # Serializes receipt lookup and insert on PostgreSQL. SQLite already
        # holds a writer reservation from _begin_push_transaction.
        state_id = db.execute(
            select(SyncProjectState.project_id)
            .where(SyncProjectState.project_id == project_id)
            .with_for_update()
        ).scalar_one_or_none()
        if state_id is None:
            raise HTTPException(status_code=500, detail="Project sync state is missing")
    role = ensure_member(db, project_id, user_id)
    ctx = _prepare_push_context(db, user_id, project_id, role, changes)
    for change in changes:
        _process_push_change(ctx, change)
    _commit_push(ctx)
    return _push_response(ctx)


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
    payload_hash: str,
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
            payload_hash=payload_hash,
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
    entity = ch.entity.strip().lower()
    op = ch.op.strip().lower()
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
                _payload_hash(ch),
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
        schema_cls = ENTITY_REGISTRY[entity]["schema"]
        val = schema_cls(**record).model_dump(exclude_unset=True)

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
    parent_field = config.get("parent_field")
    if parent_field is not None:
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


def _fetch_obj(
    db: Session, entity: str, entity_id: uuid.UUID, project_id: uuid.UUID
) -> Any | None:
    model_cls = ENTITY_MODELS[entity]
    config = ENTITY_REGISTRY[entity]

    if "parent_model" not in config:
        return (
            db.execute(
                select(model_cls).where(
                    model_cls.id == entity_id, model_cls.project_id == project_id
                )
            )
            .scalars()
            .first()
        )

    # Parent-scoped entity.
    return (
        db.execute(
            select(model_cls)
            .join(Item, model_cls.item_id == Item.id)
            .where(model_cls.id == entity_id, Item.project_id == project_id)
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
    model_cls = ENTITY_MODELS[entity]
    where: list[Any] = [model_cls.id == entity_id]
    if entity in {"risk", "opportunity"}:
        where.extend((model_cls.project_id == project_id, model_cls.type == entity))
    elif entity == "assessment":
        where.extend(
            (
                model_cls.assessor_user_id == user_id,
                model_cls.item_id.in_(
                    select(Item.id).where(Item.project_id == project_id)
                ),
            )
        )
    else:
        where.append(model_cls.project_id == project_id)
    return model_cls, where

def _current_server_state(
    db: Session,
    entity: str,
    entity_id: uuid.UUID,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
) -> tuple[int | None, dict[str, Any] | None]:
    model_cls, where = _version_scope(entity, entity_id, project_id, user_id)
    obj = (
        db.execute(
            select(model_cls)
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
    model_cls, where = _version_scope(entity, entity_id, project_id, user_id)
    # A single UPDATE returns a cursor result with the matched-row count.
    result = cast(
        CursorResult[Any],
        db.execute(
            update(model_cls)
            .where(*where, model_cls.version == base_version)
            .values(version=model_cls.version + 1, updated_at=utcnow())
            .execution_options(synchronize_session=False)
        ),
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
    project_id: uuid.UUID, # pylint: disable=unused-argument
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


def _canonical_item_code(
    db: Session,
    project_id: uuid.UUID,
    entity: str,
    requested: Any,
) -> str | None:
    """Keep an available offline code or allocate the next server-safe code."""
    code = str(requested or "").strip()
    if not code:
        return None
    collision = db.execute(
        select(Item.id).where(
            Item.project_id == project_id,
            Item.code == code,
        )
    ).scalar_one_or_none()
    if collision is None:
        return code

    prefix = "R" if entity == "risk" else "O"
    existing_codes = db.execute(
        select(Item.code).where(
            Item.project_id == project_id,
            Item.code.like(f"{prefix}-%"),
        )
    ).scalars()
    used: set[int] = set()
    for existing_code in existing_codes:
        raw = str(existing_code or "")
        head, separator, suffix = raw.partition("-")
        if separator and head.upper() == prefix and suffix.isdigit():
            used.add(int(suffix))
    number = 1
    while number in used:
        number += 1
    return f"{prefix}-{number:03d}"


def _create_new(
    db: Session,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    entity: str,
    entity_id: uuid.UUID,
    record: dict[str, Any],
) -> Any:
    now = utcnow()
    val = _parse_record(entity, record)
    model_cls = ENTITY_MODELS[entity]
    config = ENTITY_REGISTRY[entity]
    defaults = dict(config.get("defaults") or {})

    if entity in {"risk", "opportunity"} and "code" in val:
        # Offline devices may independently choose R-001/O-001. The project
        # sync-state lock serializes this allocation on PostgreSQL, while the
        # SQLite push transaction already holds the writer reservation.
        val["code"] = _canonical_item_code(
            db,
            project_id,
            entity,
            val.get("code"),
        )

    common = {"id": entity_id, "version": 1, "updated_at": now, "created_at": now}
    if entity != "assessment":
        common |= {"project_id": project_id, "created_by": user_id}

    # Apply defaults before record values.
    common |= defaults

    _validate_relationships(db, project_id, entity, val)

    if "parent_model" in config:
        # Assessments belong to the assessor.
        common |= {"assessor_user_id": user_id}

    obj = model_cls(**common)

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
    user_id: uuid.UUID, # pylint: disable=unused-argument
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
