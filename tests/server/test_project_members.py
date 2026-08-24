"""Project member admin protection and superadmin visibility filtering."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_cannot_remove_or_downgrade_last_admin(tmp_path, isolated_app_factory):
    """The last admin of a project cannot be downgraded or removed by themselves"""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'last_admin.db'}")
    with TestClient(app) as c:
        r = c.post(
            "/register",
            json={"email": "admin@test.com", "password": "Password123!"},
        )
        assert r.status_code == 201
        admin_id = r.json()["user_id"]
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        pid = c.post("/projects", json={"name": "P"}, headers=h).json()["id"]

        # Try to downgrade the only admin to viewer → 400
        r = c.post(
            f"/projects/{pid}/members",
            json={"user_email": "admin@test.com", "role": "viewer"},
            headers=h,
        )
        assert r.status_code == 400, r.text
        assert "last admin" in r.json()["detail"].lower()

        # Try to remove the only admin → 400
        r = c.delete(f"/projects/{pid}/members/{admin_id}", headers=h)
        assert r.status_code == 400, r.text
        assert "last admin" in r.json()["detail"].lower()


def test_member_list_hides_superadmin_from_non_superusers(
    tmp_path, isolated_app_factory
):
    """GET /members hides superadmin entries from non-superuser callers"""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'super_hidden.db'}")
    with TestClient(app) as c:
        admin = c.post(
            "/register",
            json={"email": "admin@test.com", "password": "Password123!"},
        ).json()
        admin_token = admin["access_token"]
        admin_h = {"Authorization": f"Bearer {admin_token}"}

        super_reg = c.post(
            "/register",
            json={"email": "super@test.com", "password": "Password123!"},
        ).json()
        super_id = super_reg["user_id"]
        super_token = super_reg["access_token"]
        super_h = {"Authorization": f"Bearer {super_token}"}

        # Promote the second user to superuser via direct DB write (same pattern
        # used elsewhere in the test suite).
        import uuid as _uuid

        import riskapp_server.db.session as session
        from riskapp_server.db.session import User
        from sqlalchemy.orm import Session

        with Session(session.engine) as db:
            u = db.get(User, _uuid.UUID(super_id))
            assert u is not None
            u.is_superuser = True
            db.add(u)
            db.commit()

        pid = c.post("/projects", json={"name": "P"}, headers=admin_h).json()["id"]
        # The superuser adds themselves to the project (they bypass non-superuser
        # restrictions and implicitly have admin access via _is_superuser).
        r = c.post(
            f"/projects/{pid}/members",
            json={"user_email": "super@test.com", "role": "member"},
            headers=super_h,
        )
        assert r.status_code == 201, r.text

        # Regular admin (non-superuser) should not see the superuser.
        r = c.get(f"/projects/{pid}/members", headers=admin_h)
        assert r.status_code == 200, r.text
        emails = [m["email"] for m in r.json()]
        assert "admin@test.com" in emails
        assert "super@test.com" not in emails

        # The superuser themselves sees both members.
        r = c.get(f"/projects/{pid}/members", headers=super_h)
        assert r.status_code == 200, r.text
        emails = [m["email"] for m in r.json()]
        assert {"admin@test.com", "super@test.com"} <= set(emails)
