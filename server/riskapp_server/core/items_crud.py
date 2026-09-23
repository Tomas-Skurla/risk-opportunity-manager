from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any, cast

from fastapi import HTTPException
from sqlalchemy import case, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select
from sqlalchemy.sql.functions import count

from riskapp_server.core.filters import apply_item_filters
from riskapp_server.core.scoring import recalculate_item_scores
from riskapp_server.db.session import RiskStatus, utcnow
from riskapp_server.schemas.models import ScoreReportOut


def claim_base_version(
    db: Session,
    model: type[Any],
    where: Sequence[Any],
    base_version: int,
    *,
    not_found_detail: str | None = None,
) -> Any:
    """Atomically advance and return a row at exactly ``base_version``."""
    result = cast(
        CursorResult[Any],
        db.execute(
            update(model)
            .where(*where, model.version == base_version)
            .values(version=model.version + 1)
            .execution_options(synchronize_session=False)
        ),
    )
    if result.rowcount != 1:
        server_version = db.execute(
            select(model.version)
            .where(*where)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if server_version is None and not_found_detail is not None:
            raise HTTPException(status_code=404, detail=not_found_detail)
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "version_mismatch",
                "server_version": server_version,
            },
        )

    return (
        db.execute(
            select(model)
            .where(*where)
            .execution_options(populate_existing=True)
        )
        .scalars()
        .one()
    )


def create_item(
    db: Session,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    payload: Any,
    model: type[Any],
) -> Any:
    now = utcnow()
    item_type = getattr(payload, "type", "risk").lower()
    prefix = "R" if item_type == "risk" else "O"

    raw_code = getattr(payload, "code", None)
    code = str(raw_code).strip() if raw_code is not None else ""
    if not code:
        code = f"{prefix}-{uuid.uuid4().hex[:8].upper()}"

    status = (
        str(
            getattr(
                getattr(payload, "status", None),
                "value",
                getattr(payload, "status", None),
            )
            or RiskStatus.concept.value
        )
        .lower()
        .strip()
    )
    if status == RiskStatus.deleted.value:
        raise HTTPException(
            status_code=422, detail="Cannot create an item with status=deleted"
        )
    occurred_at = payload.occurred_at or (
        now if status == RiskStatus.happened.value else None
    )

    data = payload.model_dump(exclude_unset=True)
    data.pop("base_version", None)
    if hasattr(model, "type"):
        # Route-specific schemas provide a default type. Pydantic intentionally
        # omits defaults from exclude_unset output, so persist the resolved value
        # explicitly instead of relying on the caller to repeat it in JSON.
        data["type"] = item_type
    else:
        data.pop("type", None)
    data.update(
        {
            "id": uuid.uuid4(),
            "project_id": project_id,
            "code": code,
            "score": 0,
            "status": status,
            "identified_at": payload.identified_at or now,
            "status_changed_at": now,
            "created_at": now,
            "created_by": user_id,
            "updated_at": now,
            "version": 1,
            "is_deleted": False,
            "occurred_at": occurred_at,
        }
    )

    item = model(**data)
    recalculate_item_scores(item)
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Item code already exists in this project"
        ) from exc
    db.refresh(item)
    return item


def update_item(
    db: Session,
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: Any,
    model: type[Any],
    *,
    item_type: str | None = None,
) -> Any:
    now = utcnow()
    where = [model.project_id == project_id, model.id == item_id]
    if item_type and hasattr(model, "type"):
        where.append(model.type == item_type)
    delete_requested = False
    update_data = payload.model_dump(exclude_unset=True, exclude={"base_version"})

    if "code" in update_data:
        raw = update_data.get("code")
        if raw is None:
            raise HTTPException(status_code=422, detail="code cannot be null")
        code = str(raw).strip()
        if not code:
            raise HTTPException(status_code=422, detail="code cannot be blank")
        update_data["code"] = code

    non_nullable = {
        "title",
        "probability",
        "impact",
        "status",
        "identified_at",
    }

    normalized_data: dict[str, Any] = {}
    for field, val in update_data.items():
        v = getattr(val, "value", val)
        if field in non_nullable and v is None:
            raise HTTPException(status_code=422, detail=f"{field} cannot be null")
        if field == "title" and isinstance(v, str) and not v.strip():
            raise HTTPException(status_code=422, detail="title cannot be blank")
        if field == "status":
            status_val = str(v).lower().strip()
            if status_val == RiskStatus.deleted.value:
                delete_requested = True
            normalized_data[field] = status_val
        else:
            normalized_data[field] = v

    item = claim_base_version(
        db,
        model,
        where,
        payload.base_version,
        not_found_detail="Item not found",
    )

    for field, value in normalized_data.items():
        if field == "status":
            item.change_status(value, now)
        else:
            setattr(item, field, value)

    if delete_requested:
        item.is_deleted = True
        item.updated_at = now
        db.commit()
        db.refresh(item)
        return item

    recalculate_item_scores(item)
    item.updated_at = now

    try:
        db.commit()
        db.refresh(item)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Item code already exists") from exc

    return item


def list_items(
    db: Session,
    project_id: uuid.UUID,
    model: type[Any],
    filters: Mapping[str, Any],
) -> Sequence[Any]:
    stmt = (
        apply_item_filters(
            select(model).where(model.project_id == project_id),
            model,
            search=filters.get("search"),
            item_type=filters.get("item_type"),
            min_score=filters.get("min_score"),
            max_score=filters.get("max_score"),
            status=filters.get("status"),
            category=filters.get("category"),
            owner_user_id=filters.get("owner_user_id"),
            owner_unassigned=bool(filters.get("owner_unassigned")),
            from_date=filters.get("from_date"),
            to_date=filters.get("to_date"),
        )
        .order_by(model.score.desc(), model.title.asc())
        .limit(filters.get("limit", 100))
        .offset(filters.get("offset", 0))
    )
    return db.execute(stmt).scalars().all()


def delete_item(
    db: Session,
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    model: type[Any],
    *,
    item_type: str | None = None,
) -> None:
    where = [model.project_id == project_id, model.id == item_id]
    if item_type and hasattr(model, "type"):
        where.append(model.type == item_type)
    item = db.execute(select(model).where(*where)).scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    item.soft_delete(utcnow())
    db.commit()
    return None


def generate_report(
    db: Session,
    project_id: uuid.UUID,
    model: type[Any],
    filters: Mapping[str, Any],
) -> ScoreReportOut:

    item_type = filters.get("item_type")
    status = filters.get("status")

    def _filtered_query(stmt: Select) -> Select:
        """applies standard report filters to any base SELECT statement."""
        return apply_item_filters(
            stmt.where(model.project_id == project_id),
            model,
            search=filters.get("search"),
            item_type=item_type,
            min_score=filters.get("min_score"),
            max_score=filters.get("max_score"),
            status=status,
            category=filters.get("category"),
            owner_user_id=filters.get("owner_user_id"),
            owner_unassigned=bool(filters.get("owner_unassigned")),
            from_date=filters.get("from_date"),
            to_date=filters.get("to_date"),
        )

    # "project_total" is a lightweight "how many items exist" figure
    # for the given project+type, respecting only the status/deleted filter.
    project_total = int(
        db.execute(
            apply_item_filters(
                select(count(model.id)).where(model.project_id == project_id),
                model,
                search=None,
                item_type=item_type,
                min_score=None,
                max_score=None,
                status=status,
                category=None,
                owner_user_id=None,
                owner_unassigned=False,
                from_date=None,
                to_date=None,
            )
        ).scalar_one()
        or 0
    )

    # Full filtered stats (no pagination).
    stats_row = db.execute(
        _filtered_query(
            select(
                count(model.id),
                func.min(model.score),
                func.max(model.score),
                func.avg(model.score),
            )
        )
    ).one()

    total = int(stats_row[0] or 0)
    mn = int(stats_row[1]) if stats_row[1] is not None else None
    mx = int(stats_row[2]) if stats_row[2] is not None else None
    avg = float(stats_row[3]) if stats_row[3] is not None else None

    # Group counts (still respecting the same filters).
    status_counts = {
        str(st or RiskStatus.concept.value): int(cnt or 0)
        for st, cnt in db.execute(
            _filtered_query(select(model.status, count(model.id))).group_by(
                model.status
            )
        ).all()
    }

    category_counts = {}
    for cat, cnt in db.execute(
        _filtered_query(select(model.category, count(model.id))).group_by(
            model.category
        )
    ).all():
        category_counts[cat or "(none)"] = int(cnt or 0)

    owner_counts = {}
    for owner_id, cnt in db.execute(
        _filtered_query(select(model.owner_user_id, count(model.id))).group_by(
            model.owner_user_id
        )
    ).all():
        owner_counts[str(owner_id) if owner_id else "(none)"] = int(cnt or 0)

    bucket = case(
        (model.score <= 4, "0-4"),
        (model.score <= 9, "5-9"),
        (model.score <= 14, "10-14"),
        (model.score <= 19, "15-19"),
        else_="20-25",
    )
    buckets = {"0-4": 0, "5-9": 0, "10-14": 0, "15-19": 0, "20-25": 0}
    for b, cnt in db.execute(
        _filtered_query(select(bucket, count(model.id))).group_by(bucket)
    ).all():
        buckets[str(b)] = int(cnt or 0)

    return ScoreReportOut(
        total=total,
        project_total=project_total,
        min_score=mn,
        max_score=mx,
        avg_score=avg,
        status_counts=status_counts,
        category_counts=category_counts,
        owner_counts=owner_counts,
        score_buckets=buckets,
    )
