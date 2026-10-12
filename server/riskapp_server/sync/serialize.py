"""Turn ORM rows into the JSON records the sync protocol sends to clients."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.inspection import inspect as sa_inspect
from sqlalchemy.orm import Session

from riskapp_server.db.models import Item
from riskapp_server.schemas.models import ActionOut


def model_to_dict(obj: Any) -> dict[str, Any]:
    """Serialize a model to JSON-safe values."""
    out: dict[str, Any] = {}
    for attr in sa_inspect(obj).mapper.column_attrs:
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


def _with_item_aliases(record: dict[str, Any], item_type: str | None) -> dict[str, Any]:
    """Expose ``item_id`` as exactly one of ``risk_id``/``opportunity_id``."""
    item_id = record.get("item_id")
    record["risk_id"] = item_id if item_type == "risk" else None
    record["opportunity_id"] = item_id if item_type == "opportunity" else None
    return record


def model_to_sync_dict(db: Session, entity: str, obj: Any) -> dict[str, Any]:
    """Serialize one entity with unambiguous parent aliases for the client."""
    out = model_to_dict(obj)
    if entity not in {"action", "assessment"}:
        return out
    item_type = (
        db.execute(select(Item.type).where(Item.id == obj.item_id)).scalar()
        if out.get("item_id")
        else None
    )
    return _with_item_aliases(out, item_type)


def serialize_action_rows(rows: list[Any]) -> list[dict[str, Any]]:
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


def serialize_assessment_rows(rows: list[Any]) -> list[dict[str, Any]]:
    return [
        _with_item_aliases(model_to_dict(assessment), item_type)
        for assessment, item_type in rows
    ]
