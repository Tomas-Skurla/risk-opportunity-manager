"""Push: apply a batch of client changes in one transaction, one result each."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from riskapp_server.core.config import SYNC_PUSH_EXPUNGE_EVERY
from riskapp_server.core.permissions import ensure_member, ensure_role_at_least
from riskapp_server.db.models import RiskStatus, SyncProjectState, SyncReceipt, utcnow
from riskapp_server.schemas.models import SyncChange
from riskapp_server.sync.mutations import (
    ConflictError,
    _apply_delete,
    _apply_upsert,
    current_server_state,
    fetch_obj,
    maybe_entity_id,
    updated_at_text,
)
from riskapp_server.sync.mutations import (  # re-exported for tests
    _claim_base_version as _claim_base_version,
)
from riskapp_server.sync.pull import pull_since as pull_since
from riskapp_server.sync.receipts import (
    change_result,
    duplicate_error_reason,
    load_existing_receipts,
    payload_hash,
    receipt_result,
    refresh_accepted_replay,
    store_receipt,
)
from riskapp_server.sync.registry import ENTITY_MODELS, ENTITY_REGISTRY, OPS

logger = logging.getLogger("riskapp_server.sync")


def _dialect_name(db: Session) -> str:
    return db.get_bind().dialect.name


def _begin_push_transaction(db: Session) -> None:
    """Acquire SQLite's writer reservation before reading entity versions.

    PostgreSQL conditional updates lock and re-check matching rows naturally.
    SQLite WAL transactions need to begin as writers to avoid a stale read
    transaction failing later with SQLITE_BUSY_SNAPSHOT instead of producing a
    deterministic version conflict.
    """
    if _dialect_name(db) != "sqlite":
        return
    if db.in_transaction():
        # Authentication/authorization may already have opened a read-only
        # transaction. No mutations occur before push_changes is entered.
        db.rollback()
    db.connection().exec_driver_sql("BEGIN IMMEDIATE")


def _lock_receipt_ids(db: Session, changes: list[SyncChange]) -> None:
    """Serialize globally unique change IDs even across different projects."""
    if _dialect_name(db) != "postgresql":
        return  # SQLite already holds a global writer reservation.
    # Sorted acquisition avoids lock-order deadlocks for multi-change batches.
    for change_id in sorted({ch.change_id for ch in changes}):
        key = int.from_bytes(change_id.bytes[:8], "big", signed=True)
        db.execute(select(func.pg_advisory_xact_lock(key)))


def classify_http_failure(status_code: int) -> tuple[str, bool]:
    """Map an operation-level HTTP failure to a stable client action."""
    status = int(status_code or 0)
    if status == 401:
        return "authentication", False
    if status == 403:
        return "permission", False
    if status in {408, 425, 429} or status >= 500:
        return "transient", True
    return "validation", False


@dataclass
class _PushContext:
    db: Session
    user_id: uuid.UUID
    project_id: uuid.UUID
    role: str
    existing_receipts: dict[uuid.UUID, SyncReceipt]
    results: list[dict[str, Any]] = field(default_factory=list)
    batch_results: dict[uuid.UUID, dict[str, Any]] = field(default_factory=dict)
    batch_hashes: dict[uuid.UUID, str] = field(default_factory=dict)
    wrote: int = 0

    def seen(self, change_id: uuid.UUID) -> bool:
        return change_id in self.existing_receipts or change_id in self.batch_hashes

    def record(
        self, change: SyncChange, result: dict[str, Any], *, persisted: bool
    ) -> None:
        self.results.append(result)
        self.batch_results[change.change_id] = result
        if not persisted:
            return
        self.wrote += 1
        if self.wrote % SYNC_PUSH_EXPUNGE_EVERY == 0:
            # Keep the transaction atomic and limit identity-map growth.
            self.db.flush()
            self.db.expunge_all()


def _record_duplicate(ctx: _PushContext, change: SyncChange) -> None:
    receipt = ctx.existing_receipts.get(change.change_id)
    reason = duplicate_error_reason(
        change,
        receipt,
        ctx.batch_hashes.get(change.change_id),
        user_id=ctx.user_id,
        project_id=ctx.project_id,
    )
    if reason:
        ctx.results.append(
            change_result(
                change_id=change.change_id,
                status="error",
                entity=change.entity,
                op=change.op,
                entity_id=maybe_entity_id(change.record),
                response={
                    "reason": reason,
                    "failure_kind": "validation",
                    "retryable": False,
                },
            )
        )
        return
    replay = (
        receipt_result(receipt)
        if receipt is not None
        else {**ctx.batch_results[change.change_id], "replayed": True}
    )
    ctx.results.append(
        refresh_accepted_replay(ctx.db, ctx.project_id, ctx.user_id, replay)
    )


def _reject_push_change(
    ctx: _PushContext,
    change: SyncChange,
    reason: str,
    detail: str | None = None,
    *,
    failure_kind: str,
    retryable: bool = False,
    store: bool = True,
) -> None:
    entity = change.entity.strip().lower()
    op = change.op.strip().lower()
    entity_id = maybe_entity_id(change.record or {})
    response: dict[str, Any] = {
        "reason": reason,
        "failure_kind": failure_kind,
        "retryable": bool(retryable),
    }
    if detail:
        response["detail"] = detail
    if store:
        with ctx.db.begin_nested():
            store_receipt(
                ctx.db,
                change,
                ctx.user_id,
                ctx.project_id,
                entity=entity,
                entity_id=entity_id,
                op=op,
                status="error",
                response=response,
            )
            ctx.db.flush()
    result = change_result(
        change_id=change.change_id,
        status="error",
        entity=entity,
        op=op,
        entity_id=entity_id,
        response=response,
    )
    ctx.record(change, result, persisted=store)


def _requires_manager(
    ctx: _PushContext, entity: str, op: str, record: dict[str, Any]
) -> bool:
    """Deletes, and upserts that delete or undelete, of manager-only entities."""
    if not ENTITY_REGISTRY[entity]["manager_delete"]:
        return False
    if op == "delete":
        return True
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
    entity_id = maybe_entity_id(record)
    if entity_id is None:
        return False
    existing = fetch_obj(ctx.db, entity, entity_id, ctx.project_id)
    return bool(existing is not None and getattr(existing, "is_deleted", False))


def _authorize_push_change(
    ctx: _PushContext,
    change: SyncChange,
    entity: str,
    op: str,
    record: dict[str, Any],
) -> bool:
    required = "manager" if _requires_manager(ctx, entity, op, record) else "member"
    try:
        ensure_role_at_least(ctx.role, required)
        return True
    except HTTPException:
        _reject_push_change(
            ctx, change, "insufficient_permissions", failure_kind="permission"
        )
        return False


def _apply_push_change(
    ctx: _PushContext,
    change: SyncChange,
    entity: str,
    op: str,
    record: dict[str, Any],
) -> None:
    apply = _apply_upsert if op == "upsert" else _apply_delete
    with ctx.db.begin_nested():
        entity_id = apply(
            ctx.db,
            ctx.user_id,
            ctx.project_id,
            entity,
            change.base_version,
            record,
            change.change_id,
        )
        # Flush the mutation before reading it back so the receipt carries the
        # canonical version and any server-assigned fields (notably item code).
        ctx.db.flush()
        server_version, server_record = current_server_state(
            ctx.db, entity, entity_id, ctx.project_id, ctx.user_id
        )
        response = {
            "entity_id": str(entity_id),
            "server_version": server_version,
            "server_record": server_record,
            "server_updated_at": updated_at_text(server_record),
        }
        store_receipt(
            ctx.db,
            change,
            ctx.user_id,
            ctx.project_id,
            entity=entity,
            entity_id=entity_id,
            op=op,
            status="accepted",
            response=response,
        )
        ctx.db.flush()

    result = change_result(
        change_id=change.change_id,
        status="accepted",
        entity=entity,
        op=op,
        entity_id=entity_id,
        response=response,
    )
    ctx.record(change, result, persisted=True)


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
    store_receipt(
        ctx.db,
        change,
        ctx.user_id,
        ctx.project_id,
        entity=entity,
        entity_id=conflict.entity_id,
        op=op,
        status="conflict",
        response=response,
    )
    result = change_result(
        change_id=change.change_id,
        status="conflict",
        entity=entity,
        op=op,
        entity_id=conflict.entity_id,
        response=response,
    )
    ctx.record(change, result, persisted=True)


def _process_new_push_change(ctx: _PushContext, change: SyncChange) -> None:
    entity = change.entity.strip().lower()
    op = change.op.strip().lower()
    record = change.record or {}
    if entity not in ENTITY_MODELS:
        _reject_push_change(ctx, change, "unknown_entity", failure_kind="validation")
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
        failure_kind, retryable = classify_http_failure(exc.status_code)
        _reject_push_change(
            ctx,
            change,
            "http_error",
            str(exc.detail),
            failure_kind=failure_kind,
            retryable=retryable,
            store=not retryable,
        )
    except IntegrityError:
        logger.info(
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
        logger.exception("Unexpected error processing sync change %s", change.change_id)
        _reject_push_change(
            ctx,
            change,
            "internal_error",
            failure_kind="transient",
            retryable=True,
            store=False,
        )


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
    ctx = _PushContext(
        db=db,
        user_id=user_id,
        project_id=project_id,
        role=ensure_member(db, project_id, user_id),
        existing_receipts=load_existing_receipts(db, changes),
    )
    for change in changes:
        if ctx.seen(change.change_id):
            _record_duplicate(ctx, change)
            continue
        # The initial receipt query cannot see receipts written later in this
        # transaction, so track IDs from the request as they are encountered.
        ctx.batch_hashes[change.change_id] = payload_hash(change)
        _process_new_push_change(ctx, change)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to commit sync push")
        raise HTTPException(status_code=500, detail="Sync push commit failed") from exc
    return {"results": ctx.results, "server_time": utcnow()}
