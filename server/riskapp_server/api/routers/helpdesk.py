from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from riskapp_server.auth.service import get_current_user
from riskapp_server.core.permissions import ensure_member, require_min_role
from riskapp_server.db.session import (
    HelpDeskCategory,
    HelpDeskPriority,
    HelpDeskStatus,
    HelpDeskTicket,
    Role,
    User,
    get_db,
    utcnow,
)
from riskapp_server.schemas.models import (
    HelpDeskTicketCreate,
    HelpDeskTicketOut,
    HelpDeskTicketUpdate,
)

router = APIRouter(tags=["helpdesk"])


def _out(ticket: HelpDeskTicket) -> HelpDeskTicketOut:
    return HelpDeskTicketOut.model_validate(ticket)


@router.get(
    "/projects/{project_id}/helpdesk/tickets", response_model=list[HelpDeskTicketOut]
)
def list_helpdesk_tickets(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[HelpDeskTicketOut]:
    ensure_member(db, project_id, user.id)
    rows = (
        db.execute(
            select(HelpDeskTicket)
            .where(
                HelpDeskTicket.project_id == project_id,
                HelpDeskTicket.is_deleted.is_(False),
            )
            .order_by(HelpDeskTicket.created_at.desc(), HelpDeskTicket.id.desc())
        )
        .scalars()
        .all()
    )
    return [_out(x) for x in rows]


@router.post(
    "/projects/{project_id}/helpdesk/tickets",
    response_model=HelpDeskTicketOut,
    status_code=201,
)
def create_helpdesk_ticket(
    project_id: uuid.UUID,
    payload: HelpDeskTicketCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HelpDeskTicketOut:
    require_min_role(db, project_id, user.id, min_role=Role.member)
    now = utcnow()
    ticket = HelpDeskTicket(
        id=uuid.uuid4(),
        project_id=project_id,
        title=payload.title,
        description=payload.description,
        category=(
            payload.category.value if payload.category else HelpDeskCategory.other.value
        ),
        priority=(
            payload.priority.value
            if payload.priority
            else HelpDeskPriority.medium.value
        ),
        status=HelpDeskStatus.open.value,
        reporter_email=payload.reporter_email,
        created_by=user.id,
        created_at=now,
        updated_at=now,
        version=1,
        is_deleted=False,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return _out(ticket)


@router.patch(
    "/projects/{project_id}/helpdesk/tickets/{ticket_id}",
    response_model=HelpDeskTicketOut,
)
def update_helpdesk_ticket(
    project_id: uuid.UUID,
    ticket_id: uuid.UUID,
    payload: HelpDeskTicketUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HelpDeskTicketOut:
    require_min_role(db, project_id, user.id, min_role=Role.member)
    ticket = (
        db.execute(
            select(HelpDeskTicket).where(
                HelpDeskTicket.project_id == project_id,
                HelpDeskTicket.id == ticket_id,
                HelpDeskTicket.is_deleted.is_(False),
            )
        )
        .scalars()
        .first()
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="Help Desk ticket not found")

    if payload.base_version is not None and int(ticket.version) != int(
        payload.base_version
    ):
        raise HTTPException(
            status_code=409,
            detail={"reason": "version_mismatch", "server_version": ticket.version},
        )

    data = payload.model_dump(exclude_unset=True)
    if "title" in data and data["title"] is None:
        raise HTTPException(status_code=422, detail="title cannot be null")

    for field, value in data.items():
        if field == "base_version":
            continue
        setattr(ticket, field, getattr(value, "value", value))

    ticket.updated_at = utcnow()
    ticket.version = int(ticket.version) + 1
    db.commit()
    db.refresh(ticket)
    return _out(ticket)


@router.delete(
    "/projects/{project_id}/helpdesk/tickets/{ticket_id}",
    status_code=204,
    response_class=Response,
)
def delete_helpdesk_ticket(
    project_id: uuid.UUID,
    ticket_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    require_min_role(db, project_id, user.id, min_role=Role.member)
    ticket = (
        db.execute(
            select(HelpDeskTicket).where(
                HelpDeskTicket.project_id == project_id,
                HelpDeskTicket.id == ticket_id,
                HelpDeskTicket.is_deleted.is_(False),
            )
        )
        .scalars()
        .first()
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="Help Desk ticket not found")

    ticket.soft_delete(utcnow())
    db.commit()
    return Response(status_code=204)
