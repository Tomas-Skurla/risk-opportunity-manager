from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from riskapp_server.auth.service import get_current_user
from riskapp_server.core.items_crud import delete_item
from riskapp_server.core.permissions import ensure_member, require_min_role
from riskapp_server.db.session import (
    Action,
    ActionStatus,
    Item,
    Role,
    User,
    get_db,
    utcnow,
)
from riskapp_server.schemas.models import ActionCreate, ActionOut, ActionUpdate

router = APIRouter(tags=["actions"])


def _resolve_target(
    db: Session,
    project_id: uuid.UUID,
    *,
    risk_id: uuid.UUID | None,
    opportunity_id: uuid.UUID | None,
) -> tuple[uuid.UUID, str]:
    if bool(risk_id) == bool(opportunity_id):
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one of risk_id or opportunity_id",
        )
    item_id = risk_id or opportunity_id
    expected_type = "risk" if risk_id else "opportunity"

    item_type = db.execute(
        select(Item.type).where(
            Item.project_id == project_id,
            Item.id == item_id,
            Item.is_deleted.is_(False),
        )
    ).scalar()
    if item_type is None:
        raise HTTPException(status_code=404, detail="Target not found")
    if item_type != expected_type:
        raise HTTPException(
            status_code=400,
            detail=f"Target is a {item_type}, expected {expected_type}",
        )
    return item_id, expected_type


def _action_out(action: Action, *, target_type: str) -> dict:
    return ActionOut(
        id=action.id,
        project_id=action.project_id,
        risk_id=action.item_id if target_type == "risk" else None,
        opportunity_id=action.item_id if target_type == "opportunity" else None,
        kind=action.kind,
        title=action.title,
        description=action.description,
        status=action.status,
        owner_user_id=action.owner_user_id,
        updated_at=action.updated_at,
        version=action.version,
        is_deleted=action.is_deleted,
    ).model_dump()


@router.post(
    "/projects/{project_id}/actions", response_model=ActionOut, status_code=201
)
def create_action(
    project_id: uuid.UUID,
    payload: ActionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    require_min_role(db, project_id, user.id, min_role=Role.member)

    item_id, target_type = _resolve_target(
        db,
        project_id,
        risk_id=payload.risk_id,
        opportunity_id=payload.opportunity_id,
    )

    now = utcnow()
    action = Action(
        id=uuid.uuid4(),
        project_id=project_id,
        item_id=item_id,
        kind=(
            payload.kind.value if hasattr(payload.kind, "value") else str(payload.kind)
        ),
        title=payload.title,
        description=payload.description,
        status=(
            payload.status.value
            if getattr(payload, "status", None) is not None
            else ActionStatus.open.value
        ),
        owner_user_id=payload.owner_user_id,
        created_by=user.id,
        created_at=now,
        updated_at=now,
        version=1,
        is_deleted=False,
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    return _action_out(action, target_type=target_type)


@router.get("/projects/{project_id}/actions", response_model=list[ActionOut])
def list_actions(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    ensure_member(db, project_id, user.id)
    rows = db.execute(
        select(Action, Item.type)
        .join(Item, Item.id == Action.item_id)
        .where(Action.project_id == project_id, Action.is_deleted.is_(False))
        .order_by(Action.updated_at.desc())
    ).all()
    return [_action_out(a, target_type=t) for a, t in rows]


@router.patch("/projects/{project_id}/actions/{action_id}", response_model=ActionOut)
def update_action(
    project_id: uuid.UUID,
    action_id: uuid.UUID,
    payload: ActionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    require_min_role(db, project_id, user.id, min_role=Role.member)

    action = (
        db.execute(
            select(Action).where(
                Action.project_id == project_id,
                Action.id == action_id,
                Action.is_deleted.is_(False),
            )
        )
        .scalars()
        .first()
    )
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    data = payload.model_dump(exclude_unset=True)

    if "kind" in data and data.get("kind") is None:
        raise HTTPException(status_code=422, detail="kind cannot be null")
    if "status" in data and data.get("status") is None:
        raise HTTPException(status_code=422, detail="status cannot be null")
    if "title" in data:
        raw_title = data.get("title")
        if raw_title is None:
            raise HTTPException(status_code=422, detail="title cannot be null")
        title = str(raw_title).strip()
        if not title:
            raise HTTPException(status_code=422, detail="title cannot be blank")
        data["title"] = title

    if "risk_id" in data or "opportunity_id" in data:
        item_id, _t = _resolve_target(
            db,
            project_id,
            risk_id=data.get("risk_id"),
            opportunity_id=data.get("opportunity_id"),
        )
        action.item_id = item_id
        data.pop("risk_id", None)
        data.pop("opportunity_id", None)

    for field, val in data.items():
        setattr(action, field, getattr(val, "value", val))

    action.updated_at = utcnow()
    action.version = int(action.version) + 1
    db.commit()

    target_type = (
        db.execute(select(Item.type).where(Item.id == action.item_id)).scalar()
        or "risk"
    )
    return _action_out(action, target_type=target_type)


@router.delete(
    "/projects/{project_id}/actions/{action_id}",
    status_code=204,
    response_class=Response,
)
def delete_action(
    project_id: uuid.UUID,
    action_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    require_min_role(db, project_id, user.id, min_role=Role.manager)
    delete_item(db, project_id, action_id, Action)
    return Response(status_code=204)
