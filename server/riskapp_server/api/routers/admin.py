"""Global administration, reserved for superusers.

Every route here lives under ``/admin`` and the router itself requires a
superuser, so no endpoint can forget the check and a gateway can keep global
administration off the public entrance with one path rule. Project
administrators manage their own projects through the ordinary routes.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from riskapp_server.auth.service import (
    require_superuser,
    revoke_user_refresh_tokens,
    set_user_password,
)
from riskapp_server.core.config import RETENTION_DAYS, SYNC_RECEIPT_RETENTION_DAYS
from riskapp_server.db.session import (
    Action,
    Assessment,
    AuditLog,
    HelpDeskTicket,
    Item,
    Project,
    ProjectMember,
    ScoreSnapshot,
    SyncReceipt,
    User,
    get_db,
    utcnow,
)
from riskapp_server.schemas.models import AdminSetPasswordIn

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_superuser)],
)


@router.delete(
    "/projects/{project_id}",
    status_code=204,
    response_class=Response,
)
def delete_project(project_id: uuid.UUID, db: Session = Depends(get_db)) -> Response:
    """Permanently delete a project and all its data."""
    proj = db.execute(select(Project).where(Project.id == project_id)).scalars().first()
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    # Cascade delete all dependent data.
    # Assessments FK → items, so delete them first.
    item_ids = select(Item.id).where(Item.project_id == project_id).scalar_subquery()
    db.execute(delete(Assessment).where(Assessment.item_id.in_(item_ids)))
    db.execute(delete(Action).where(Action.project_id == project_id))
    db.execute(delete(Item).where(Item.project_id == project_id))
    db.execute(delete(ScoreSnapshot).where(ScoreSnapshot.project_id == project_id))
    db.execute(delete(HelpDeskTicket).where(HelpDeskTicket.project_id == project_id))
    db.execute(delete(SyncReceipt).where(SyncReceipt.project_id == project_id))
    db.execute(delete(AuditLog).where(AuditLog.project_id == project_id))
    db.execute(delete(ProjectMember).where(ProjectMember.project_id == project_id))
    db.delete(proj)
    db.commit()
    return Response(status_code=204)


@router.post("/projects/{project_id}/maintenance/prune")
def prune_project_logs(
    project_id: uuid.UUID,
    days: int | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Delete old audit/sync receipt rows for a project.

    Project administrators are part of the activity being audited, so they
    cannot shorten or erase their own project's audit history.
    """
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    d = int(days or RETENTION_DAYS)
    d = max(1, min(d, 3650))
    cutoff = utcnow() - timedelta(days=d)
    receipt_cutoff = utcnow() - timedelta(days=max(d, SYNC_RECEIPT_RETENTION_DAYS))

    r1 = db.execute(
        delete(AuditLog).where(AuditLog.project_id == project_id, AuditLog.ts < cutoff)
    )
    r2 = db.execute(
        delete(SyncReceipt).where(
            SyncReceipt.project_id == project_id,
            SyncReceipt.processed_at < receipt_cutoff,
        )
    )
    db.commit()
    return {
        "ok": True,
        "cutoff": cutoff.isoformat(),
        "receipt_cutoff": receipt_cutoff.isoformat(),
        "audit_deleted": int(getattr(r1, "rowcount", 0) or 0),
        "sync_receipts_deleted": int(getattr(r2, "rowcount", 0) or 0),
    }


@router.post("/users/{user_id}/deactivate", status_code=204)
def admin_deactivate_user(user_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_active = False
    target.deactivated_at = utcnow()
    db.add(target)
    revoke_user_refresh_tokens(db, target.id)
    db.commit()
    return None


@router.post("/users/{user_id}/activate", status_code=204)
def admin_activate_user(user_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_active = True
    target.deactivated_at = None
    db.add(target)
    db.commit()
    return None


@router.post("/users/{user_id}/set-password", status_code=204)
def admin_set_password(
    user_id: uuid.UUID,
    payload: AdminSetPasswordIn,
    db: Session = Depends(get_db),
) -> None:
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    set_user_password(db, target, payload.new_password)
    return None
