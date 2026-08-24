from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from riskapp_server.auth.service import get_current_user
from riskapp_server.core.permissions import ensure_member, require_min_role
from riskapp_server.db.session import Role, User, get_db
from riskapp_server.schemas.models import (
    SyncPullRequest,
    SyncPullResponse,
    SyncPushRequest,
    SyncPushResponse,
)
from riskapp_server.sync.engine import pull_since, push_changes

router = APIRouter(tags=["sync"])


@router.post(
    "/projects/{project_id}/sync/pull",
    response_model=SyncPullResponse,
    response_model_exclude_none=True,
)
def sync_pull(
    project_id: uuid.UUID,
    payload: SyncPullRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    ensure_member(db, project_id, user.id)
    if payload.project_id != project_id:
        raise HTTPException(status_code=400, detail="project_id mismatch")
    return pull_since(
        db,
        project_id=project_id,
        since=payload.since,
        limit_per_entity=payload.limit_per_entity,
        cursors=payload.cursors,
    )


@router.post("/projects/{project_id}/sync/push", response_model=SyncPushResponse)
def sync_push(
    project_id: uuid.UUID,
    payload: SyncPushRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    require_min_role(db, project_id, user.id, min_role=Role.member)
    if payload.project_id != project_id:
        raise HTTPException(status_code=400, detail="project_id mismatch")
    return push_changes(
        db=db, user_id=user.id, project_id=project_id, changes=payload.changes
    )
