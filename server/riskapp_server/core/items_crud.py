from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any, cast

from fastapi import HTTPException
from sqlalchemy import case, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select
from sqlalchemy.sql.functions import count

from riskapp_server.core.csv_export import safe_csv_cell
from riskapp_server.core.filters import apply_filter_params
from riskapp_server.core.scoring import recalculate_item_scores
from riskapp_server.db.models import Assessment, Item, RiskStatus, utcnow
from riskapp_server.schemas.models import AssessmentIn, ScoreReportOut

_NON_NULLABLE_FIELDS = frozenset(
    {"title", "probability", "impact", "status", "identified_at"}
)
_CSV_COLUMNS = (
    "id",
    "type",
    "code",
    "title",
    "category",
    "status",
    "probability",
    "impact",
    "score",
    "owner_user_id",
    "identified_at",
    "updated_at",
    "version",
    "is_deleted",
)
_EMPTY_SCORE_BUCKETS = {"0-4": 0, "5-9": 0, "10-14": 0, "15-19": 0, "20-25": 0}


def status_value(value: Any) -> str:
    """A status given as an enum or text, as lowercase stored text."""
    return str(getattr(value, "value", value) or "").lower().strip()


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
            select(model).where(*where).execution_options(populate_existing=True)
        )
        .scalars()
        .one()
    )


def _item_where(
    model: type[Any],
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    item_type: str | None,
) -> list[Any]:
    where = [model.project_id == project_id, model.id == item_id]
    if item_type and hasattr(model, "type"):
        where.append(model.type == item_type)
    return where


def create_item(
    db: Session,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    payload: Any,
    model: type[Any],
) -> Any:
    now = utcnow()
    item_type = payload.type.lower()
    prefix = "R" if item_type == "risk" else "O"

    code = str(payload.code).strip() if payload.code is not None else ""
    if not code:
        code = f"{prefix}-{uuid.uuid4().hex[:8].upper()}"

    status = status_value(payload.status) or RiskStatus.concept.value
    if status == RiskStatus.deleted.value:
        raise HTTPException(
            status_code=422, detail="Cannot create an item with status=deleted"
        )
    occurred_at = payload.occurred_at or (
        now if status == RiskStatus.happened.value else None
    )

    data = payload.model_dump(exclude_unset=True)
    data.pop("base_version", None)
    data.update(
        {
            "id": uuid.uuid4(),
            "project_id": project_id,
            # Route schemas default the type; exclude_unset would drop it.
            "type": item_type,
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


def _validated_changes(payload: Any) -> tuple[dict[str, Any], bool]:
    """Normalize a PATCH payload; return its changes and whether it deletes."""
    update_data = payload.model_dump(exclude_unset=True, exclude={"base_version"})

    if "code" in update_data:
        if update_data["code"] is None:
            raise HTTPException(status_code=422, detail="code cannot be null")
        update_data["code"] = str(update_data["code"]).strip()
        if not update_data["code"]:
            raise HTTPException(status_code=422, detail="code cannot be blank")

    changes: dict[str, Any] = {}
    for field, val in update_data.items():
        v = getattr(val, "value", val)
        if field in _NON_NULLABLE_FIELDS and v is None:
            raise HTTPException(status_code=422, detail=f"{field} cannot be null")
        if field == "title" and isinstance(v, str) and not v.strip():
            raise HTTPException(status_code=422, detail="title cannot be blank")
        changes[field] = str(v).lower().strip() if field == "status" else v
    return changes, changes.get("status") == RiskStatus.deleted.value


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
    changes, delete_requested = _validated_changes(payload)
    item = claim_base_version(
        db,
        model,
        _item_where(model, project_id, item_id, item_type),
        payload.base_version,
        not_found_detail="Item not found",
    )

    for field, value in changes.items():
        if field == "status":
            item.change_status(value, now)
        else:
            setattr(item, field, value)
    item.updated_at = now

    if delete_requested:
        item.is_deleted = True
        db.commit()
        db.refresh(item)
        return item

    recalculate_item_scores(item)

    try:
        db.commit()
        db.refresh(item)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Item code already exists") from exc
    return item


def _list_query(
    model: type[Any], project_id: uuid.UUID, filters: Mapping[str, Any]
) -> Select:
    return (
        apply_filter_params(
            select(model).where(model.project_id == project_id), model, filters
        )
        .order_by(model.score.desc(), model.title.asc())
        .limit(filters.get("limit", 100))
        .offset(filters.get("offset", 0))
    )


def list_items(
    db: Session,
    project_id: uuid.UUID,
    model: type[Any],
    filters: Mapping[str, Any],
) -> Sequence[Any]:
    return db.execute(_list_query(model, project_id, filters)).scalars().all()


def item_csv_rows(
    db: Session, project_id: uuid.UUID, filters: Mapping[str, Any]
) -> Iterator[bytes]:
    """Stream the current filtered page of non-deleted items as CSV lines."""
    stmt = _list_query(Item, project_id, filters).where(Item.is_deleted.is_(False))
    buf = io.StringIO()
    writer = csv.writer(buf)

    def take() -> bytes:
        line = buf.getvalue().encode()
        buf.seek(0)
        buf.truncate(0)
        return line

    writer.writerow(_CSV_COLUMNS)
    yield take()
    for obj in db.execute(stmt).scalars():
        writer.writerow([safe_csv_cell(getattr(obj, c, "")) for c in _CSV_COLUMNS])
        yield take()


def delete_item(
    db: Session,
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    model: type[Any],
    *,
    item_type: str | None = None,
) -> None:
    where = _item_where(model, project_id, item_id, item_type)
    item = db.execute(select(model).where(*where)).scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    item.soft_delete(utcnow())
    db.commit()


def generate_report(
    db: Session,
    project_id: uuid.UUID,
    model: type[Any],
    filters: Mapping[str, Any],
) -> ScoreReportOut:
    def filtered(stmt: Select, active: Mapping[str, Any] = filters) -> Select:
        return apply_filter_params(
            stmt.where(model.project_id == project_id), model, active
        )

    def counts_by(column: Any, label: Callable[[Any], str]) -> dict[str, int]:
        rows = db.execute(filtered(select(column, count(model.id))).group_by(column))
        return {label(value): int(cnt or 0) for value, cnt in rows}

    # How many items exist for the project and type, honouring only status.
    project_total = int(
        db.execute(
            filtered(
                select(count(model.id)),
                {
                    "item_type": filters.get("item_type"),
                    "status": filters.get("status"),
                },
            )
        ).scalar_one()
        or 0
    )
    total, low, high, mean = db.execute(
        filtered(
            select(
                count(model.id),
                func.min(model.score),
                func.max(model.score),
                func.avg(model.score),
            )
        )
    ).one()

    bucket = case(
        (model.score <= 4, "0-4"),
        (model.score <= 9, "5-9"),
        (model.score <= 14, "10-14"),
        (model.score <= 19, "15-19"),
        else_="20-25",
    )
    return ScoreReportOut(
        total=int(total or 0),
        project_total=project_total,
        min_score=int(low) if low is not None else None,
        max_score=int(high) if high is not None else None,
        avg_score=float(mean) if mean is not None else None,
        status_counts=counts_by(
            model.status, lambda s: str(s or RiskStatus.concept.value)
        ),
        category_counts=counts_by(model.category, lambda c: c or "(none)"),
        owner_counts=counts_by(
            model.owner_user_id, lambda o: str(o) if o else "(none)"
        ),
        score_buckets={**_EMPTY_SCORE_BUCKETS, **counts_by(bucket, str)},
    )


def require_item(
    db: Session, project_id: uuid.UUID, item_id: uuid.UUID, item_type: str
) -> None:
    """404 unless a live item of ``item_type`` exists in the project."""
    found = db.execute(
        select(Item.id).where(
            Item.project_id == project_id,
            Item.id == item_id,
            Item.is_deleted.is_(False),
            Item.type == item_type,
        )
    ).first()
    if not found:
        raise HTTPException(status_code=404, detail="Item not found")


def item_assessments(db: Session, item_id: uuid.UUID) -> Sequence[Assessment]:
    return (
        db.execute(
            select(Assessment)
            .where(Assessment.item_id == item_id, Assessment.is_deleted.is_(False))
            .order_by(Assessment.updated_at.desc())
        )
        .scalars()
        .all()
    )


def upsert_assessment(
    db: Session, item_id: uuid.UUID, user_id: uuid.UUID, payload: AssessmentIn
) -> Assessment:
    """Create (base_version 0) or update the caller's assessment of an item."""
    mine = (Assessment.item_id == item_id, Assessment.assessor_user_id == user_id)
    assessment = db.execute(select(Assessment).where(*mine)).scalars().first()
    now = utcnow()
    if not assessment:
        if payload.base_version != 0:
            raise HTTPException(
                status_code=409,
                detail={"reason": "version_mismatch", "server_version": None},
            )
        assessment = Assessment(
            id=uuid.uuid4(),
            item_id=item_id,
            assessor_user_id=user_id,
            created_at=now,
            updated_at=now,
            version=1,
            is_deleted=False,
        )
        db.add(assessment)
    else:
        assessment = claim_base_version(db, Assessment, mine, payload.base_version)

    assessment.probability = payload.probability
    assessment.impact = payload.impact
    assessment.notes = payload.notes
    assessment.is_deleted = False
    assessment.updated_at = now
    recalculate_item_scores(assessment)
    db.commit()
    db.refresh(assessment)
    return assessment
