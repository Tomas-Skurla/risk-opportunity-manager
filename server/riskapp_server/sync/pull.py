"""Pull: page each entity's change feed by its transactional change_sequence."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from riskapp_server.core.config import MAX_SYNC_PULL_PER_ENTITY
from riskapp_server.db.models import (
    Action,
    Assessment,
    HelpDeskTicket,
    Item,
    SyncProjectState,
    utcnow,
)
from riskapp_server.schemas.models import HelpDeskTicketOut
from riskapp_server.sync.serialize import (
    model_to_dict,
    serialize_action_rows,
    serialize_assessment_rows,
)


@dataclass(frozen=True)
class _PullContext:
    db: Session
    server_time: datetime
    limit: int | None
    hard_cap: int | None
    cursors: dict[str, str]
    since_sequence: int
    snapshot_sequence: int


@dataclass(frozen=True)
class _PullPage:
    rows: list[Any]
    has_more: bool
    cursor: str


def _parse_sequence_cursor(
    cur: str | None, *, default_since: int, snapshot_sequence: int
) -> int:
    if not cur:
        return default_since
    try:
        prefix, value = cur.split(":", 1)
        sequence = int(value)
        if prefix != "seq" or not default_since <= sequence <= snapshot_sequence:
            raise ValueError("cursor is outside the synchronization snapshot")
        return sequence
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid cursor") from exc


def _prepare_pull_context(
    db: Session,
    project_id: uuid.UUID,
    limit_per_entity: int | None,
    cursors: dict[str, str] | None,
    since_sequence: int,
    snapshot_sequence: int | None,
) -> _PullContext:
    current_sequence_value = db.execute(
        select(SyncProjectState.last_sequence).where(
            SyncProjectState.project_id == project_id
        )
    ).scalar_one_or_none()
    if current_sequence_value is None:
        raise HTTPException(
            status_code=500, detail="Project synchronization state is missing"
        )
    current_sequence = int(current_sequence_value)

    since_sequence = int(since_sequence)
    if since_sequence < 0:
        raise HTTPException(
            status_code=400, detail="since_sequence must be nonnegative"
        )
    normalized_snapshot_sequence = (
        current_sequence if snapshot_sequence is None else int(snapshot_sequence)
    )
    if normalized_snapshot_sequence < since_sequence:
        raise HTTPException(
            status_code=400, detail="snapshot_sequence precedes since_sequence"
        )
    if normalized_snapshot_sequence > current_sequence:
        raise HTTPException(
            status_code=400, detail="snapshot_sequence is ahead of the server"
        )
    hard_cap = MAX_SYNC_PULL_PER_ENTITY if limit_per_entity is None else None
    limit = hard_cap if limit_per_entity is None else limit_per_entity
    return _PullContext(
        db=db,
        server_time=utcnow(),
        limit=limit,
        hard_cap=hard_cap,
        cursors=cursors or {},
        since_sequence=since_sequence,
        snapshot_sequence=normalized_snapshot_sequence,
    )


def _pull_page(
    ctx: _PullContext,
    cursor_key: str,
    model: Any,
    query: Select[Any] | Select[Any, str],
    *,
    joined: bool = False,
) -> _PullPage:
    """Fetch rows after this entity's cursor, up to the snapshot, one page long.

    ``joined`` queries select ``(row, Item.type)`` pairs instead of bare rows.
    """
    since = _parse_sequence_cursor(
        ctx.cursors.get(cursor_key),
        default_since=ctx.since_sequence,
        snapshot_sequence=ctx.snapshot_sequence,
    )
    query = query.where(
        model.change_sequence > since,
        model.change_sequence <= ctx.snapshot_sequence,
    ).order_by(model.change_sequence.asc())
    if ctx.limit:
        query = query.limit(ctx.limit + 1)
    result = ctx.db.execute(query)
    rows = list(result.all() if joined else result.scalars().all())

    has_more = bool(ctx.limit and len(rows) > ctx.limit)
    if has_more:
        rows = rows[: ctx.limit]
    if rows:
        last = rows[-1][0] if joined else rows[-1]
        since = int(last.change_sequence)
    return _PullPage(rows=rows, has_more=has_more, cursor=f"seq:{since}")


def pull_since(
    db: Session,
    project_id: uuid.UUID,
    *,
    since_sequence: int,
    limit_per_entity: int | None = None,
    cursors: dict[str, str] | None = None,
    snapshot_sequence: int | None = None,
) -> dict[str, Any]:
    ctx = _prepare_pull_context(
        db,
        project_id,
        limit_per_entity,
        cursors,
        since_sequence,
        snapshot_sequence,
    )

    def items(item_type: str) -> Select[Any]:
        return select(Item).where(Item.project_id == project_id, Item.type == item_type)

    def with_item_type(model: Any) -> Select[Any, str]:
        return select(model, Item.type).join(Item, model.item_id == Item.id)

    pages = {
        "risks": _pull_page(ctx, "risks", Item, items("risk")),
        "opportunities": _pull_page(ctx, "opportunities", Item, items("opportunity")),
        "actions": _pull_page(
            ctx,
            "actions",
            Action,
            with_item_type(Action).where(Action.project_id == project_id),
            joined=True,
        ),
        "assessments": _pull_page(
            ctx,
            "assessments",
            Assessment,
            with_item_type(Assessment).where(Item.project_id == project_id),
            joined=True,
        ),
        "helpdesk_tickets": _pull_page(
            ctx,
            "helpdesk_tickets",
            HelpDeskTicket,
            select(HelpDeskTicket).where(HelpDeskTicket.project_id == project_id),
        ),
    }
    has_more = {key: page.has_more for key, page in pages.items()}

    out: dict[str, Any] = {
        "server_time": ctx.server_time,
        "server_sequence": ctx.snapshot_sequence,
        "risks": [model_to_dict(row) for row in pages["risks"].rows],
        "opportunities": [model_to_dict(row) for row in pages["opportunities"].rows],
        "actions": serialize_action_rows(pages["actions"].rows),
        "assessments": serialize_assessment_rows(pages["assessments"].rows),
        "helpdesk_tickets": [
            HelpDeskTicketOut.model_validate(row).model_dump(mode="json")
            for row in pages["helpdesk_tickets"].rows
        ],
    }

    if ctx.hard_cap and any(has_more.values()):
        raise HTTPException(
            status_code=413,
            detail=("Sync pull too large. Paginate using limit_per_entity + cursors."),
        )

    if limit_per_entity is not None:
        out["has_more"] = has_more
        out["cursors"] = {key: page.cursor for key, page in pages.items()}
    return out
