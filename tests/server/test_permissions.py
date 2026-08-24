from __future__ import annotations

import uuid

import pytest


def test_ensure_role_at_least_blocks_lower_roles() -> None:
    """ensure_role_at_least raises HTTP 403 for roles below the required minimum"""
    from fastapi import HTTPException
    from riskapp_server.core.permissions import ensure_role_at_least
    from riskapp_server.db.session import Role

    with pytest.raises(HTTPException) as e:
        ensure_role_at_least(Role.viewer, Role.member)
    assert e.value.status_code == 403
    ensure_role_at_least(Role.member, Role.member)
    ensure_role_at_least(Role.admin, Role.manager)


def test_get_member_role_normalizes_role_strings(
    tmp_path, isolated_app_factory
) -> None:
    """get_member_role normalises legacy role strings like 'Role.admin' to 'admin'"""

    db_file = tmp_path / "perm_test.db"
    isolated_app_factory(f"sqlite+pysqlite:///{db_file}")
    import riskapp_server.db.session as session
    from riskapp_server.core.permissions import get_member_role
    from riskapp_server.db.session import Project, ProjectMember, User, utcnow
    from sqlalchemy.orm import Session

    with Session(session.engine) as db:
        session.Base.metadata.create_all(bind=session.engine)
        u = User(email="x@example.com", password_hash="h", is_active=True)
        db.add(u)
        db.commit()
        db.refresh(u)
        p = Project(
            id=uuid.uuid4(),
            name="P",
            description=None,
            created_at=utcnow(),
            created_by=u.id,
        )
        db.add(p)
        db.commit()
        db.add(
            ProjectMember(
                project_id=p.id, user_id=u.id, role="Role.admin", created_at=utcnow()
            )
        )
        db.commit()
        role = get_member_role(db, p.id, u.id)
        assert role == "admin"
