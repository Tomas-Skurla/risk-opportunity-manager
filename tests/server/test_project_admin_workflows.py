"""Project administration workflows across authorization and cleanup boundaries."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def _register(client: TestClient, email: str) -> tuple[dict, dict[str, str]]:
    response = client.post(
        "/register", json={"email": email, "password": "Password123!"}
    )
    assert response.status_code == 201, response.text
    data = response.json()
    return data, {"Authorization": f"Bearer {data['access_token']}"}


def _promote_to_superuser(user_id: str) -> None:
    import riskapp_server.db.session as session
    from riskapp_server.db.session import User
    from sqlalchemy.orm import Session

    with Session(session.engine) as db:
        user = db.get(User, uuid.UUID(user_id))
        assert user is not None
        user.is_superuser = True
        db.add(user)
        db.commit()


def test_member_updates_removals_and_superuser_visibility(
    tmp_path, isolated_app_factory
) -> None:
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'member-admin.db'}")
    with TestClient(app) as client:
        owner, owner_headers = _register(client, "owner@example.com")
        member, _ = _register(client, "member@example.com")
        superuser, super_headers = _register(client, "root@example.com")
        _promote_to_superuser(superuser["user_id"])

        project = client.post(
            "/projects", json={"name": "Administration"}, headers=owner_headers
        ).json()
        project_id = project["id"]
        assert (
            client.get(f"/projects/{project_id}", headers=owner_headers).status_code
            == 200
        )

        missing_user = client.post(
            f"/projects/{project_id}/members",
            json={"user_email": "missing@example.com", "role": "member"},
            headers=owner_headers,
        )
        assert missing_user.status_code == 404

        protected_add = client.post(
            f"/projects/{project_id}/members",
            json={"user_email": "root@example.com", "role": "member"},
            headers=owner_headers,
        )
        assert protected_add.status_code == 403

        added_superuser = client.post(
            f"/projects/{project_id}/members",
            json={"user_email": "root@example.com", "role": "member"},
            headers=super_headers,
        )
        assert added_superuser.status_code == 201
        protected_remove = client.delete(
            f"/projects/{project_id}/members/{superuser['user_id']}",
            headers=owner_headers,
        )
        assert protected_remove.status_code == 403

        added = client.post(
            f"/projects/{project_id}/members",
            json={"user_email": "member@example.com", "role": "admin"},
            headers=owner_headers,
        )
        assert added.status_code == 201
        assert added.json()["updated"] is False

        updated = client.post(
            f"/projects/{project_id}/members",
            json={"user_email": "member@example.com", "role": "manager"},
            headers=owner_headers,
        )
        assert updated.status_code == 201
        assert updated.json()["updated"] is True

        missing_member = client.delete(
            f"/projects/{project_id}/members/{uuid.uuid4()}", headers=owner_headers
        )
        assert missing_member.status_code == 404
        removed = client.delete(
            f"/projects/{project_id}/members/{member['user_id']}",
            headers=owner_headers,
        )
        assert removed.status_code == 204

        all_projects = client.get("/projects", headers=super_headers)
        assert all_projects.status_code == 200
        assert project_id in {entry["id"] for entry in all_projects.json()}
        member_projects = client.get("/projects", headers=owner_headers)
        assert member_projects.status_code == 200
        assert project_id in {entry["id"] for entry in member_projects.json()}
        assert owner["user_id"] != superuser["user_id"]


def test_superuser_bypass_pruning_and_project_cascade_delete(
    tmp_path, isolated_app_factory
) -> None:
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'project-delete.db'}")
    with TestClient(app) as client:
        regular, regular_headers = _register(client, "regular@example.com")
        superuser, super_headers = _register(client, "super@example.com")
        _promote_to_superuser(superuser["user_id"])

        project_id = client.post(
            "/projects", json={"name": "Disposable"}, headers=regular_headers
        ).json()["id"]
        risk = client.post(
            f"/projects/{project_id}/risks",
            json={
                "type": "risk",
                "title": "Cascade me",
                "probability": 2,
                "impact": 3,
            },
            headers=regular_headers,
        )
        assert risk.status_code == 201

        default_prune = client.post(
            f"/projects/{project_id}/maintenance/prune?days=0",
            headers=regular_headers,
        )
        assert default_prune.status_code == 200
        assert default_prune.json()["ok"] is True
        bounded_prune = client.post(
            f"/projects/{project_id}/maintenance/prune?days=99999",
            headers=regular_headers,
        )
        assert bounded_prune.status_code == 200

        forbidden = client.delete(
            f"/projects/{project_id}", headers=regular_headers
        )
        assert forbidden.status_code == 403
        missing_id = uuid.uuid4()
        assert (
            client.get(f"/projects/{missing_id}", headers=super_headers).status_code
            == 404
        )
        assert (
            client.delete(f"/projects/{missing_id}", headers=super_headers).status_code
            == 404
        )

        deleted = client.delete(f"/projects/{project_id}", headers=super_headers)
        assert deleted.status_code == 204
        assert (
            client.get(f"/projects/{project_id}", headers=super_headers).status_code
            == 404
        )

        own_project = client.post(
            "/projects", json={"name": "Superuser project"}, headers=super_headers
        ).json()["id"]
        downgraded = client.post(
            f"/projects/{own_project}/members",
            json={"user_email": "super@example.com", "role": "viewer"},
            headers=super_headers,
        )
        assert downgraded.status_code == 201
        assert downgraded.json()["updated"] is True
        assert regular["user_id"] != superuser["user_id"]
