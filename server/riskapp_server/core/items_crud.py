from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from riskapp_server.core.filters import apply_item_filters
from riskapp_server.core.scoring import recalculate_item_scores
from riskapp_server.db.session import RiskStatus, utcnow
from riskapp_server.schemas.models import ScoreReportOut


def create_item(db: Session, user_id: uuid.UUID, project_id: uuid.UUID, payload, Model):
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
    if hasattr(Model, "type"):
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

    item = Model(**data)
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
    payload,
    Model,
    *,
    item_type: str | None = None,
):
    now = utcnow()
    where = [Model.project_id == project_id, Model.id == item_id]
    if item_type and hasattr(Model, "type"):
        where.append(Model.type == item_type)
    item = db.execute(select(Model).where(*where)).scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if payload.base_version is not None and item.version != payload.base_version:
        raise HTTPException(
            status_code=409,
            detail={"reason": "version_mismatch", "server_version": item.version},
        )

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
            else:
                item.change_status(status_val, now)
        else:
            setattr(item, field, v)

    if delete_requested:
        item.soft_delete(now)
        db.commit()
        db.refresh(item)
        return item

    recalculate_item_scores(item)
    item.updated_at = now
    item.version = int(item.version) + 1

    try:
        db.commit()
        db.refresh(item)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Item code already exists") from exc

    return item


def list_items(db: Session, project_id: uuid.UUID, Model, filters: dict):
    stmt = (
        apply_item_filters(
            select(Model).where(Model.project_id == project_id),
            Model,
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
        .order_by(Model.score.desc(), Model.title.asc())
        .limit(filters.get("limit", 100))
        .offset(filters.get("offset", 0))
    )
    return db.execute(stmt).scalars().all()


def delete_item(
    db: Session,
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    Model,
    *,
    item_type: str | None = None,
):
    where = [Model.project_id == project_id, Model.id == item_id]
    if item_type and hasattr(Model, "type"):
        where.append(Model.type == item_type)
    item = db.execute(select(Model).where(*where)).scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    item.soft_delete(utcnow())
    db.commit()
    return None


def generate_report(
    db: Session, project_id: uuid.UUID, Model, filters: dict
) -> ScoreReportOut:

    item_type = filters.get("item_type")
    status = filters.get("status")

    def _filtered_query(stmt):
        """applies standard report filters to any base SELECT statement."""
        return apply_item_filters(
            stmt.where(Model.project_id == project_id),
            Model,
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
                select(func.count(Model.id)).where(Model.project_id == project_id),
                Model,
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
                func.count(Model.id),
                func.min(Model.score),
                func.max(Model.score),
                func.avg(Model.score),
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
            _filtered_query(select(Model.status, func.count(Model.id))).group_by(
                Model.status
            )
        ).all()
    }

    category_counts = {}
    for cat, cnt in db.execute(
        _filtered_query(select(Model.category, func.count(Model.id))).group_by(
            Model.category
        )
    ).all():
        category_counts[cat or "(none)"] = int(cnt or 0)

    owner_counts = {}
    for owner_id, cnt in db.execute(
        _filtered_query(select(Model.owner_user_id, func.count(Model.id))).group_by(
            Model.owner_user_id
        )
    ).all():
        owner_counts[str(owner_id) if owner_id else "(none)"] = int(cnt or 0)

    bucket = case(
        (Model.score <= 4, "0-4"),
        (Model.score <= 9, "5-9"),
        (Model.score <= 14, "10-14"),
        (Model.score <= 19, "15-19"),
        else_="20-25",
    )
    buckets = {"0-4": 0, "5-9": 0, "10-14": 0, "15-19": 0, "20-25": 0}
    for b, cnt in db.execute(
        _filtered_query(select(bucket, func.count(Model.id))).group_by(bucket)
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
