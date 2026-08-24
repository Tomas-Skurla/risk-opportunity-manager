from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from riskapp_server.auth.service import get_current_user
from riskapp_server.core.config import SNAPSHOT_INSERT_CHUNK
from riskapp_server.core.permissions import ensure_member, require_min_role
from riskapp_server.db.session import Item, Role, ScoreSnapshot, User, get_db, utcnow
from riskapp_server.schemas.models import (
    SnapshotCreateOut,
    SnapshotLatestOut,
    TopBatch,
    TopItem,
)

router = APIRouter(tags=["snapshots"])


def _top_item(r: ScoreSnapshot) -> TopItem:
    return TopItem(
        item_id=r.item_id,
        title=r.title,
        probability=r.probability,
        impact=r.impact,
        score=r.score,
    )


@router.post(
    "/projects/{project_id}/snapshots",
    response_model=SnapshotCreateOut,
    status_code=201,
)
def create_snapshot(
    project_id: uuid.UUID,
    kind: str = "both",  # both|risks|opportunities
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SnapshotCreateOut:
    require_min_role(db, project_id, user.id, min_role=Role.member)

    batch_id = uuid.uuid4()
    captured_at = utcnow()
    counts = {"risk": 0, "opportunity": 0}

    chunk: list[dict] = []
    chunk_size = max(100, int(SNAPSHOT_INSERT_CHUNK or 1000))

    def flush_chunk() -> None:
        nonlocal chunk
        if chunk:
            db.execute(insert(ScoreSnapshot), chunk)
            chunk = []

    k = (kind or "both").strip().lower()
    wanted: list[str]
    if k in {"both", "all"}:
        wanted = ["risk", "opportunity"]
    elif k in {"risk", "risks"}:
        wanted = ["risk"]
    elif k in {"opportunity", "opportunities", "opp", "opps"}:
        wanted = ["opportunity"]
    else:
        raise HTTPException(
            status_code=400, detail="kind must be both|risks|opportunities"
        )

    for kind in wanted:
        rows = db.execute(
            select(
                Item.id, Item.title, Item.probability, Item.impact, Item.score
            ).where(
                Item.project_id == project_id,
                Item.is_deleted.is_(False),
                Item.type == kind,
            )
        )
        for i in rows:
            counts[kind] += 1
            chunk.append(
                {
                    "id": uuid.uuid4(),
                    "batch_id": batch_id,
                    "captured_at": captured_at,
                    "project_id": project_id,
                    "kind": kind,
                    "item_id": i.id,
                    "title": i.title,
                    "probability": i.probability,
                    "impact": i.impact,
                    "score": i.score,
                    "created_by": user.id,
                }
            )
            if len(chunk) >= chunk_size:
                flush_chunk()
    flush_chunk()
    db.commit()
    return SnapshotCreateOut(
        batch_id=batch_id,
        captured_at=captured_at,
        risks=counts["risk"],
        opportunities=counts["opportunity"],
    )


@router.get("/projects/{project_id}/snapshots/latest", response_model=SnapshotLatestOut)
def latest_snapshot(
    project_id: uuid.UUID,
    kind: str = "risks",  # risks|opportunities
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SnapshotLatestOut:
    ensure_member(db, project_id, user.id)
    k = (kind or "").strip().lower()
    snap_kind = (
        "risk"
        if k in {"risks", "risk"}
        else "opportunity" if k in {"opportunities", "opportunity"} else None
    )
    if not snap_kind:
        raise HTTPException(status_code=400, detail="kind must be risks|opportunities")

    row = db.execute(
        select(ScoreSnapshot.batch_id, ScoreSnapshot.captured_at)
        .where(ScoreSnapshot.project_id == project_id, ScoreSnapshot.kind == snap_kind)
        .order_by(ScoreSnapshot.captured_at.desc())
        .limit(1)
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="No snapshots")

    batch_id, captured_at = row
    count = int(
        db.execute(
            select(func.count(ScoreSnapshot.id)).where(
                ScoreSnapshot.project_id == project_id,
                ScoreSnapshot.batch_id == batch_id,
                ScoreSnapshot.kind == snap_kind,
            )
        ).scalar_one()
        or 0
    )
    return SnapshotLatestOut(
        batch_id=batch_id, captured_at=captured_at, kind=snap_kind, count=count
    )


@router.get("/projects/{project_id}/snapshots/{batch_id}/top", response_model=TopBatch)
def top_items(
    project_id: uuid.UUID,
    batch_id: uuid.UUID,
    kind: str = "risk",
    limit: int = 10,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TopBatch:
    ensure_member(db, project_id, user.id)
    limit = max(1, min(limit, 100))

    rows = (
        db.execute(
            select(ScoreSnapshot)
            .where(
                ScoreSnapshot.project_id == project_id,
                ScoreSnapshot.batch_id == batch_id,
                ScoreSnapshot.kind == kind,
            )
            .order_by(ScoreSnapshot.score.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    if not rows:
        raise HTTPException(
            status_code=404, detail="Snapshot batch not found (or empty)"
        )

    return TopBatch(
        batch_id=batch_id,
        captured_at=rows[0].captured_at,
        top=[_top_item(r) for r in rows],
    )


@router.get("/projects/{project_id}/top-history", response_model=list[TopBatch])
def top_history(
    project_id: uuid.UUID,
    kind: str = "risks",  # risks|opportunities|risk|opportunity
    limit: int = 10,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TopBatch]:
    ensure_member(db, project_id, user.id)
    limit = max(1, min(limit, 100))

    k = (kind or "").strip().lower()
    snap_kind = (
        "risk"
        if k in {"risks", "risk"}
        else (
            "opportunity"
            if k in {"opportunities", "opportunity", "opps", "opp"}
            else None
        )
    )
    if not snap_kind:
        raise HTTPException(status_code=400, detail="kind must be risks|opportunities")

    where = [ScoreSnapshot.project_id == project_id, ScoreSnapshot.kind == snap_kind]
    if from_ts is not None:
        where.append(ScoreSnapshot.captured_at >= from_ts)
    if to_ts is not None:
        where.append(ScoreSnapshot.captured_at <= to_ts)

    batches = db.execute(
        select(ScoreSnapshot.batch_id, ScoreSnapshot.captured_at)
        .where(*where)
        .group_by(ScoreSnapshot.batch_id, ScoreSnapshot.captured_at)
        .order_by(ScoreSnapshot.captured_at.asc())
    ).all()
    if not batches:
        return []

    batch_ids = [b[0] for b in batches]
    subq = (
        select(
            ScoreSnapshot.id,
            func.row_number()
            .over(
                partition_by=ScoreSnapshot.batch_id, order_by=ScoreSnapshot.score.desc()
            )
            .label("rn"),
        )
        .where(
            ScoreSnapshot.project_id == project_id,
            ScoreSnapshot.kind == snap_kind,
            ScoreSnapshot.batch_id.in_(batch_ids),
        )
        .subquery()
    )
    all_rows = (
        db.execute(
            select(ScoreSnapshot)
            .join(subq, ScoreSnapshot.id == subq.c.id)
            .where(subq.c.rn <= limit)
            .order_by(ScoreSnapshot.batch_id, subq.c.rn)
        )
        .scalars()
        .all()
    )
    by_batch: dict[uuid.UUID, list[ScoreSnapshot]] = {}
    for r in all_rows:
        by_batch.setdefault(r.batch_id, []).append(r)
    return [
        TopBatch(
            batch_id=b, captured_at=ts, top=[_top_item(r) for r in by_batch.get(b, [])]
        )
        for b, ts in batches
    ]
