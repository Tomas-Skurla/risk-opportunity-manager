"""Authorization helpers (used by both routers and the sync engine)."""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from riskapp_server.db.session import ProjectMember, Role, User

ROLE_RANK: dict[str, int] = {
    Role.viewer.value: 1,
    Role.member.value: 2,
    Role.manager.value: 3,
    Role.admin.value: 4,
}


def _is_superuser(db: Session, user_id: uuid.UUID, *, user: User | None = None) -> bool:
    """Check if the user has the is_superuser flag set.
    If a User object is provided, reads the flag directly without a DB query.
    """
    if user is not None:
        return bool(user.is_superuser)
    row = db.execute(select(User.is_superuser).where(User.id == user_id)).first()
    return bool(row and row[0])


def ensure_role_at_least(role: str | Role, min_role: str | Role) -> None:
    r = role.value if isinstance(role, Role) else role
    m = min_role.value if isinstance(min_role, Role) else min_role
    if ROLE_RANK.get(r, 0) < ROLE_RANK.get(m, 10_000):
        raise HTTPException(status_code=403, detail="Insufficient permissions")


def get_member_role(
    db: Session, project_id: uuid.UUID, user_id: uuid.UUID
) -> str | None:

    def _normalize_role(val) -> str | None:
        if val is None:
            return None
        if isinstance(val, Role):
            return val.value
        s = str(val)
        if s.startswith("Role."):
            candidate = s.split(".", 1)[1]
            if candidate in ROLE_RANK:
                return candidate
        return s

    row = db.execute(
        select(ProjectMember.role).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    ).first()
    if row:
        return _normalize_role(row[0])
    # Superusers implicitly have admin access to every project.
    if _is_superuser(db, user_id):
        return Role.admin.value
    return None


def require_min_role(
    db: Session,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    min_role: Role | str,
) -> str:
    role = get_member_role(db, project_id, user_id)
    if not role or role not in ROLE_RANK:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    ensure_role_at_least(role, min_role)
    return role


def ensure_member(db: Session, project_id: uuid.UUID, user_id: uuid.UUID) -> str:
    return require_min_role(db, project_id, user_id, min_role=Role.viewer)
