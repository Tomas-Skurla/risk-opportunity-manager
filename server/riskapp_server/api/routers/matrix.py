from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from riskapp_server.auth.service import get_current_user
from riskapp_server.core.permissions import ensure_member
from riskapp_server.db.session import Item, User, get_db
from riskapp_server.schemas.models import MatrixResponse

router = APIRouter(tags=["matrix"])


@router.get("/projects/{project_id}/matrix", response_model=MatrixResponse)
def matrix(
    project_id: uuid.UUID,
    kind: str = "both",  # risk|opportunity|both
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MatrixResponse:
    ensure_member(db, project_id, user.id)

    k = (kind or "").strip().lower()
    if k not in {"risk", "opportunity", "both"}:
        raise HTTPException(
            status_code=400, detail="kind must be risk|opportunity|both"
        )

    p_axis = list(range(1, 6))
    i_axis = list(range(1, 6))

    def blank() -> list[list[int]]:
        return [[0 for _ in i_axis] for __ in p_axis]

    risks = blank() if k in {"risk", "both"} else None
    opps = blank() if k in {"opportunity", "both"} else None

    def fill(item_type: str, out):
        if out is None:
            return
        for p, i, c in db.execute(
            select(Item.probability, Item.impact, func.count(Item.id))
            .where(
                Item.project_id == project_id,
                Item.is_deleted.is_(False),
                Item.type == item_type,
                # If a record is missing probability/impact (e.g. draft), don't
                # let it crash the matrix indexing.
                Item.probability.is_not(None),
                Item.impact.is_not(None),
                Item.probability.between(1, 5),
                Item.impact.between(1, 5),
            )
            .group_by(Item.probability, Item.impact)
        ).all():
            out[p - 1][i - 1] = c

    fill("risk", risks)
    fill("opportunity", opps)

    return MatrixResponse(
        kind=k,
        probability_axis=p_axis,
        impact_axis=i_axis,
        risks=risks,
        opportunities=opps,
    )
