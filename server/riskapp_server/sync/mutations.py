"""Apply one pushed upsert or delete: validate it, claim its version, write it."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from typing import Any, cast

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from riskapp_server.core.scoring import recalculate_item_scores
from riskapp_server.db.models import AuditLog, Item, RiskStatus, utcnow
from riskapp_server.sync.registry import ENTITY_MODELS, ENTITY_REGISTRY
from riskapp_server.sync.serialize import model_to_dict, model_to_sync_dict

# Fields the server derives; a client record can never set them directly.
_SERVER_OWNED_FIELDS = frozenset({"score", "assessor_user_id"})


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
        self.server_updated_at = updated_at_text(server_record)


def updated_at_text(record: dict[str, Any] | None) -> str | None:
    """The record's ``updated_at`` as the string a result carries, if any."""
    value = record.get("updated_at") if record else None
    return str(value) if value is not None else None


def parse_uuid(value: Any, name: str) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid UUID for {name}") from exc


def maybe_entity_id(record: dict[str, Any]) -> uuid.UUID | None:
    rid = record.get("id")
    try:
        return uuid.UUID(str(rid)) if rid else None
    except ValueError, TypeError:
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
    parent_field = ENTITY_REGISTRY[entity].get("parent_field")
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
        select(Item.type).where(Item.project_id == project_id, Item.id == item_id)
    ).scalar()
    if not t or (expected_type and t != expected_type):
        raise HTTPException(status_code=400, detail="Target not found in project")


def fetch_obj(
    db: Session, entity: str, entity_id: uuid.UUID, project_id: uuid.UUID
) -> Any | None:
    model_cls = ENTITY_MODELS[entity]
    if "parent_field" not in ENTITY_REGISTRY[entity]:
        query = select(model_cls).where(
            model_cls.id == entity_id, model_cls.project_id == project_id
        )
    else:
        query = (
            select(model_cls)
            .join(Item, model_cls.item_id == Item.id)
            .where(model_cls.id == entity_id, Item.project_id == project_id)
        )
    return db.execute(query).scalars().first()


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


def current_server_state(
    db: Session,
    entity: str,
    entity_id: uuid.UUID,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
) -> tuple[int | None, dict[str, Any] | None]:
    model_cls, where = _version_scope(entity, entity_id, project_id, user_id)
    obj = (
        db.execute(
            select(model_cls).where(*where).execution_options(populate_existing=True)
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
        server_version, server_record = current_server_state(
            db, entity, entity_id, project_id, user_id
        )
        raise ConflictError(
            "version_mismatch", entity_id, server_version, server_record
        )


def _claim_existing(
    db: Session,
    obj: Any,
    entity: str,
    entity_id: uuid.UUID,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    base_version: Any,
) -> dict[str, Any]:
    """Check access and version, claim the next version; return the old state."""
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
    expected_version = _check_base_version(
        obj, base_version, entity_id, model_to_sync_dict(db, entity, obj)
    )
    before = model_to_dict(obj)
    _claim_base_version(db, entity, entity_id, project_id, user_id, expected_version)
    return before


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
    obj = fetch_obj(db, entity, entity_id, project_id)
    if obj is None:
        obj = _create_new(db, user_id, project_id, entity, entity_id, record)
        before = None
    else:
        before = _claim_existing(
            db, obj, entity, entity_id, project_id, user_id, base_version
        )
        _update_existing(db, project_id, entity, obj, record)
    _audit(db, user_id, project_id, change_id, entity, entity_id, "upsert", before, obj)
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
    obj = fetch_obj(db, entity, entity_id, project_id)
    if not obj:
        return entity_id
    before = _claim_existing(
        db, obj, entity, entity_id, project_id, user_id, base_version
    )
    obj.soft_delete(utcnow())
    _audit(db, user_id, project_id, change_id, entity, entity_id, "delete", before, obj)
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
        select(Item.id).where(Item.project_id == project_id, Item.code == code)
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
        head, separator, suffix = str(existing_code or "").partition("-")
        if separator and head.upper() == prefix and suffix.isdigit():
            used.add(int(suffix))
    number = 1
    while number in used:
        number += 1
    return f"{prefix}-{number:03d}"


def _client_fields(obj: Any, val: dict[str, Any]) -> Iterator[tuple[str, Any]]:
    """Yield the parsed fields a client may set on ``obj``, enums unwrapped."""
    for k, v in val.items():
        if k.startswith("_") or k in _SERVER_OWNED_FIELDS or not hasattr(obj, k):
            continue
        yield k, getattr(v, "value", v)


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
    config = ENTITY_REGISTRY[entity]

    if entity in {"risk", "opportunity"} and "code" in val:
        # Offline devices may independently choose R-001/O-001. The project
        # sync-state lock serializes this allocation on PostgreSQL, while the
        # SQLite push transaction already holds the writer reservation.
        val["code"] = _canonical_item_code(db, project_id, entity, val.get("code"))

    common = {"id": entity_id, "version": 1, "updated_at": now, "created_at": now}
    if entity != "assessment":
        common |= {"project_id": project_id, "created_by": user_id}
    common |= config["defaults"]  # Defaults first; record values override them.

    _validate_relationships(db, project_id, entity, val)

    if "parent_field" in config:
        # Assessments belong to the assessor.
        common |= {"assessor_user_id": user_id}

    obj = config["model"](**common)
    for k, v in _client_fields(obj, val):
        setattr(obj, k, v)
    recalculate_item_scores(obj)
    db.add(obj)
    return obj


def _update_existing(
    db: Session,
    project_id: uuid.UUID,
    entity: str,
    obj: Any,
    record: dict[str, Any],
) -> None:
    now = utcnow()
    val = _parse_record(entity, record)
    _validate_relationships(db, project_id, entity, val, obj)

    for k, v in _client_fields(obj, val):
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

    recalculate_item_scores(obj)
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
    obj: Any,
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
            after=model_to_dict(obj),
            ts=utcnow(),
        )
    )
