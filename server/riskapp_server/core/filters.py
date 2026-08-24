"""Query helpers for list and report endpoints.

This module does not use future annotations because some FastAPI/Pydantic
versions trip over uuid.UUID here when building the schema.
"""

import uuid
from datetime import date, datetime, timedelta

from fastapi import HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.sql import Select

from riskapp_server.db.session import RiskStatus


def _escape_like(value: str) -> str:
    """Escape SQL LIKE wildcards so user input is treated as literal text."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class ItemFilterParams:

    def __init__(
        self,
        search: str | None = Query(default=None, max_length=300),
        item_type: str | None = Query(default=None, max_length=20),
        min_score: int | None = Query(default=None, ge=0, le=25),
        max_score: int | None = Query(default=None, ge=0, le=25),
        status: str | None = Query(default=None, max_length=200),
        category: str | None = Query(default=None, max_length=500),
        owner_user_id: uuid.UUID | None = None,
        owner_unassigned: bool = Query(
            default=False,
            description="If true, return only records with no owner_user_id.",
        ),
        from_date: date | None = None,
        to_date: date | None = None,
        limit: int = Query(
            default=100, ge=1, le=1000, description="Maximum records to return"
        ),
        offset: int = Query(default=0, ge=0, description="Records to skip"),
    ):
        self.search = search
        self.item_type = item_type
        self.min_score = min_score
        self.max_score = max_score
        self.status = status
        self.category = category
        self.owner_user_id = owner_user_id
        self.owner_unassigned = owner_unassigned

        if self.owner_unassigned and self.owner_user_id is not None:
            raise HTTPException(
                status_code=422,
                detail="Provide only one of owner_user_id or owner_unassigned",
            )
        self.from_date = from_date
        self.to_date = to_date
        self.limit = limit
        self.offset = offset


def csv_list(value: str | None) -> list[str]:
    return [v.strip() for v in str(value or "").split(",") if v.strip()]


def apply_date_range(
    stmt: Select, field, *, from_date: date | None, to_date: date | None
) -> Select:
    if from_date is not None:
        stmt = stmt.where(field >= datetime.combine(from_date, datetime.min.time()))
    if to_date is not None:
        stmt = stmt.where(
            field < datetime.combine(to_date + timedelta(days=1), datetime.min.time())
        )
    return stmt


def normalize_score_range(
    min_score: int | None, max_score: int | None
) -> tuple[int | None, int | None]:
    return (
        (max_score, min_score)
        if min_score is not None and max_score is not None and min_score > max_score
        else (min_score, max_score)
    )


def apply_item_filters(
    stmt: Select,
    Model,
    *,
    search: str | None,
    item_type: str | None,
    min_score: int | None,
    max_score: int | None,
    status: str | None,
    category: str | None,
    owner_user_id,
    owner_unassigned: bool = False,
    from_date: date | None,
    to_date: date | None,
) -> Select:
    """Apply item filters."""
    min_score, max_score = normalize_score_range(min_score, max_score)
    status_values = [s.lower() for s in csv_list(status)]
    include_deleted = RiskStatus.deleted.value in status_values
    non_deleted = [s for s in status_values if s != RiskStatus.deleted.value]

    if include_deleted:
        cond = Model.is_deleted.is_(True)
        if non_deleted:
            cond = or_(cond, Model.status.in_(non_deleted))
        stmt = stmt.where(cond)
    else:
        stmt = stmt.where(Model.is_deleted.is_(False))
        if non_deleted:
            stmt = stmt.where(Model.status.in_(non_deleted))

    if category and category.strip():
        cats = csv_list(category)
        if cats:
            stmt = stmt.where(
                or_(
                    *[
                        Model.category.ilike(f"%{_escape_like(c)}%", escape="\\")
                        for c in cats
                    ]
                )
            )

    if item_type and hasattr(Model, "type"):
        stmt = stmt.where(Model.type == item_type.lower().strip())

    if owner_unassigned:
        stmt = stmt.where(Model.owner_user_id.is_(None))
    elif owner_user_id is not None:
        stmt = stmt.where(Model.owner_user_id == owner_user_id)

    stmt = apply_date_range(
        stmt, Model.identified_at, from_date=from_date, to_date=to_date
    )

    if search and search.strip():
        q = f"%{_escape_like(search.strip())}%"
        stmt = stmt.where(
            or_(
                Model.title.ilike(q, escape="\\"),
                Model.code.ilike(q, escape="\\"),
            )
        )

    if min_score is not None:
        stmt = stmt.where(Model.score >= int(min_score))
    if max_score is not None:
        stmt = stmt.where(Model.score <= int(max_score))

    return stmt
