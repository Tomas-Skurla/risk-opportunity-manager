"""Idempotency: receipts record each change_id's outcome so retries replay it."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from riskapp_server.db.models import SyncReceipt, utcnow
from riskapp_server.schemas.models import SyncChange
from riskapp_server.sync.mutations import current_server_state, updated_at_text
from riskapp_server.sync.registry import ENTITY_MODELS

# Optional keys copied from a stored response into a per-change result.
_RESULT_KEYS = (
    "reason",
    "detail",
    "server_version",
    "server_record",
    "server_updated_at",
    "failure_kind",
    "retryable",
)


def payload_hash(change: SyncChange) -> str:
    """Hash the parsed, key-order-independent request, excluding its receipt ID."""
    payload = change.model_dump(mode="json", exclude={"change_id"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def change_result(
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
    result.update((key, payload[key]) for key in _RESULT_KEYS if key in payload)
    return result


def receipt_result(receipt: SyncReceipt) -> dict[str, Any]:
    return change_result(
        change_id=receipt.change_id,
        status=receipt.status,
        entity=receipt.entity,
        op=receipt.op,
        entity_id=receipt.entity_id,
        response=receipt.response,
        replayed=True,
    )


def store_receipt(
    db: Session,
    change: SyncChange,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    *,
    entity: str,
    entity_id: uuid.UUID | None,
    op: str,
    status: str,
    response: dict[str, Any],
) -> None:
    db.add(
        SyncReceipt(
            change_id=change.change_id,
            user_id=user_id,
            project_id=project_id,
            entity=entity,
            entity_id=entity_id,
            op=op,
            status=status,
            response=response or {},
            payload_hash=payload_hash(change),
            processed_at=utcnow(),
        )
    )


def load_existing_receipts(
    db: Session, changes: list[SyncChange]
) -> dict[uuid.UUID, SyncReceipt]:
    change_ids = [change.change_id for change in changes]
    if not change_ids:
        return {}
    receipts = db.execute(
        select(SyncReceipt).where(SyncReceipt.change_id.in_(change_ids))
    ).scalars()
    return {receipt.change_id: receipt for receipt in receipts}


def duplicate_error_reason(
    change: SyncChange,
    receipt: SyncReceipt | None,
    batch_hash: str | None,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
) -> str | None:
    """Why a repeated change_id must not replay, or None when it may."""
    if receipt is None:
        return (
            None if batch_hash == payload_hash(change) else "change_id_payload_mismatch"
        )
    if receipt.user_id != user_id or receipt.project_id != project_id:
        return "change_id_in_use"
    if receipt.payload_hash is None:
        return "receipt_unverifiable"
    if receipt.payload_hash != payload_hash(change):
        return "change_id_payload_mismatch"
    return None


def refresh_accepted_replay(
    db: Session,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    replay: dict[str, Any],
) -> dict[str, Any]:
    """Return current server state for an accepted idempotency replay.

    A client can move its pull watermark past a row while the row has a local
    retry pending. Replaying the original receipt must therefore reconcile the
    current row, not restore the older snapshot stored with that receipt.
    """
    if replay.get("status") != "accepted":
        return replay
    entity = str(replay.get("entity") or "")
    raw_entity_id = replay.get("entity_id")
    if entity not in ENTITY_MODELS or not raw_entity_id:
        return replay
    try:
        entity_id = uuid.UUID(str(raw_entity_id))
    except TypeError, ValueError:
        return replay
    server_version, server_record = current_server_state(
        db, entity, entity_id, project_id, user_id
    )
    if server_record is None:
        return replay
    refreshed = dict(replay)
    receipt_server_version = refreshed.get("server_version")
    if isinstance(receipt_server_version, int) and not isinstance(
        receipt_server_version, bool
    ):
        refreshed["receipt_server_version"] = receipt_server_version
    refreshed["server_version"] = server_version
    refreshed["server_record"] = server_record
    refreshed["server_updated_at"] = updated_at_text(server_record)
    return refreshed
