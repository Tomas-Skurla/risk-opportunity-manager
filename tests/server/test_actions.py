"""Action router: target validation, list, RBAC delete."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _register(c, email):
    r = c.post("/register", json={"email": email, "password": "Password123!"})
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def test_action_target_type_mismatch_returns_400(tmp_path, isolated_app_factory):
    """Action create with the wrong target kind (opportunity-as-risk) returns HTTP 400"""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'actions_targets.db'}")
    with TestClient(app) as c:
        token = _register(c, "owner@test.com")
        h = _h(token)

        pid = c.post("/projects", json={"name": "P"}, headers=h).json()["id"]

        opp = c.post(
            f"/projects/{pid}/opportunities",
            json={
                "type": "opportunity",
                "title": "Reuse components",
                "probability": 2,
                "impact": 3,
            },
            headers=h,
        ).json()

        # Pass the opportunity id under risk_id → 400 (target type mismatch)
        r = c.post(
            f"/projects/{pid}/actions",
            json={
                "risk_id": opp["id"],
                "kind": "mitigation",
                "title": "Wrong target kind",
            },
            headers=h,
        )
        assert r.status_code == 400, r.text
        assert "expected risk" in r.json()["detail"]

        # Provide neither → 400 from the router ("exactly one of ...").
        r = c.post(
            f"/projects/{pid}/actions",
            json={"kind": "mitigation", "title": "No target"},
            headers=h,
        )
        assert r.status_code == 400, r.text


def test_member_creates_action_but_only_manager_deletes(tmp_path, isolated_app_factory):
    """Member can create an action but only manager+ can delete it"""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'actions_rbac.db'}")
    with TestClient(app) as c:
        admin_token = _register(c, "admin@test.com")
        member_token = _register(c, "member@test.com")
        manager_token = _register(c, "manager@test.com")

        pid = c.post("/projects", json={"name": "P"}, headers=_h(admin_token)).json()[
            "id"
        ]

        # Add member and manager.
        c.post(
            f"/projects/{pid}/members",
            json={"user_email": "member@test.com", "role": "member"},
            headers=_h(admin_token),
        )
        c.post(
            f"/projects/{pid}/members",
            json={"user_email": "manager@test.com", "role": "manager"},
            headers=_h(admin_token),
        )

        risk = c.post(
            f"/projects/{pid}/risks",
            json={
                "type": "risk",
                "title": "Outage",
                "probability": 4,
                "impact": 4,
            },
            headers=_h(admin_token),
        ).json()

        # Member creates an action.
        r = c.post(
            f"/projects/{pid}/actions",
            json={
                "risk_id": risk["id"],
                "kind": "mitigation",
                "title": "Add backup server",
            },
            headers=_h(member_token),
        )
        assert r.status_code == 201, r.text
        action_id = r.json()["id"]

        # Member is forbidden from deleting (delete requires manager+).
        r = c.delete(
            f"/projects/{pid}/actions/{action_id}",
            headers=_h(member_token),
        )
        assert r.status_code == 403

        # Manager soft-deletes.
        r = c.delete(
            f"/projects/{pid}/actions/{action_id}",
            headers=_h(manager_token),
        )
        assert r.status_code == 204

        # The action no longer appears in the list.
        r = c.get(f"/projects/{pid}/actions", headers=_h(admin_token))
        assert r.status_code == 200
        assert action_id not in [a["id"] for a in r.json()]
