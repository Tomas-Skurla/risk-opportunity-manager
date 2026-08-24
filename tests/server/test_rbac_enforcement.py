"""RBAC enforcement: viewer/member/manager/admin boundaries on real endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _auth(c, email, password="Password123!"):
    r = c.post("/register", json={"email": email, "password": password})
    assert r.status_code == 201
    return r.json()["access_token"]


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_viewer_can_read_but_not_create(tmp_path, isolated_app_factory):
    """Viewer role can list risks but is forbidden from creating new ones"""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'rbac.db'}")
    with TestClient(app) as c:
        admin_token = _auth(c, "admin@test.com")
        viewer_token = _auth(c, "viewer@test.com")

        # Admin creates a project
        r = c.post("/projects", json={"name": "P"}, headers=_headers(admin_token))
        pid = r.json()["id"]

        # Admin adds viewer
        c.post(
            f"/projects/{pid}/members",
            json={"user_email": "viewer@test.com", "role": "viewer"},
            headers=_headers(admin_token),
        )

        # Viewer can list risks (read)
        r = c.get(f"/projects/{pid}/risks", headers=_headers(viewer_token))
        assert r.status_code == 200

        # Viewer cannot create a risk (write)
        r = c.post(
            f"/projects/{pid}/risks",
            json={
                "type": "risk",
                "title": "X",
                "probability": 3,
                "impact": 3,
            },
            headers=_headers(viewer_token),
        )
        assert r.status_code == 403


def test_member_can_create_but_not_delete(tmp_path, isolated_app_factory):
    """Member role can create risks but is forbidden from deleting them"""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'rbac2.db'}")
    with TestClient(app) as c:
        admin_token = _auth(c, "admin@test.com")
        member_token = _auth(c, "member@test.com")

        r = c.post("/projects", json={"name": "P"}, headers=_headers(admin_token))
        pid = r.json()["id"]

        c.post(
            f"/projects/{pid}/members",
            json={"user_email": "member@test.com", "role": "member"},
            headers=_headers(admin_token),
        )

        # Member can create
        r = c.post(
            f"/projects/{pid}/risks",
            json={
                "type": "risk",
                "title": "R1",
                "probability": 4,
                "impact": 2,
            },
            headers=_headers(member_token),
        )
        assert r.status_code == 201
        risk_id = r.json()["id"]

        # Member cannot delete (requires manager)
        r = c.delete(
            f"/projects/{pid}/risks/{risk_id}",
            headers=_headers(member_token),
        )
        assert r.status_code == 403


def test_manager_can_delete(tmp_path, isolated_app_factory):
    """Manager role can both create and delete risks"""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'rbac3.db'}")
    with TestClient(app) as c:
        admin_token = _auth(c, "admin@test.com")
        manager_token = _auth(c, "mgr@test.com")

        r = c.post("/projects", json={"name": "P"}, headers=_headers(admin_token))
        pid = r.json()["id"]

        c.post(
            f"/projects/{pid}/members",
            json={"user_email": "mgr@test.com", "role": "manager"},
            headers=_headers(admin_token),
        )

        # Manager creates a risk
        r = c.post(
            f"/projects/{pid}/risks",
            json={
                "type": "risk",
                "title": "R1",
                "probability": 3,
                "impact": 3,
            },
            headers=_headers(manager_token),
        )
        assert r.status_code == 201
        risk_id = r.json()["id"]

        # Manager can delete
        r = c.delete(
            f"/projects/{pid}/risks/{risk_id}",
            headers=_headers(manager_token),
        )
        assert r.status_code == 204
