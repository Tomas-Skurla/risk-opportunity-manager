from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def _setup(c: TestClient):
    r = c.post(
        "/register",
        json={"email": "helpdesk@test.com", "password": "Password123!"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    r = c.post("/projects", json={"name": "Helpdesk Project"}, headers=h)
    assert r.status_code == 201, r.text
    return h, r.json()["id"]


def test_helpdesk_rest_crud_and_soft_delete(tmp_path, isolated_app_factory):
    """Helpdesk tickets support full REST CRUD with soft-delete"""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'helpdesk_rest.db'}")
    with TestClient(app) as c:
        h, pid = _setup(c)

        r = c.post(
            f"/projects/{pid}/helpdesk/tickets",
            json={
                "title": "Export fails",
                "description": "CSV export crashes",
                "category": "bug",
                "priority": "high",
                "reporter_email": "reporter@example.com",
            },
            headers=h,
        )
        assert r.status_code == 201, r.text
        ticket = r.json()
        assert ticket["status"] == "open"
        assert ticket["version"] == 1

        r = c.patch(
            f"/projects/{pid}/helpdesk/tickets/{ticket['id']}",
            json={"status": "in_progress", "base_version": 1},
            headers=h,
        )
        assert r.status_code == 200, r.text
        updated = r.json()
        assert updated["status"] == "in_progress"
        assert updated["version"] == 2

        r = c.get(f"/projects/{pid}/helpdesk/tickets", headers=h)
        assert r.status_code == 200, r.text
        assert [x["id"] for x in r.json()] == [ticket["id"]]

        r = c.delete(f"/projects/{pid}/helpdesk/tickets/{ticket['id']}", headers=h)
        assert r.status_code == 204, r.text

        r = c.get(f"/projects/{pid}/helpdesk/tickets", headers=h)
        assert r.status_code == 200, r.text
        assert r.json() == []


def test_helpdesk_sync_round_trip_with_legacy_base_version_zero(
    tmp_path, isolated_app_factory
):
    """Helpdesk sync push/pull round-trip works with legacy base_version=0 clients"""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'helpdesk_sync.db'}")
    with TestClient(app) as c:
        h, pid = _setup(c)

        ticket_id = str(uuid.uuid4())
        r = c.post(
            f"/projects/{pid}/sync/push",
            json={
                "project_id": pid,
                "changes": [
                    {
                        "change_id": str(uuid.uuid4()),
                        "entity": "helpdesk_ticket",
                        "op": "upsert",
                        "base_version": 0,
                        "record": {
                            "id": ticket_id,
                            "title": "Sync me",
                            "description": "Created offline",
                            "category": "bug",
                            "priority": "medium",
                            "status": "open",
                            "reporter_email": "sync@example.com",
                        },
                    }
                ],
            },
            headers=h,
        )
        assert r.status_code == 200, r.text
        assert r.json()["accepted"] == 1

        r = c.post(
            f"/projects/{pid}/sync/pull",
            json={"project_id": pid, "since": "2000-01-01T00:00:00"},
            headers=h,
        )
        assert r.status_code == 200, r.text
        pulled = r.json()["helpdesk_tickets"]
        assert len(pulled) == 1
        assert pulled[0]["id"] == ticket_id
        assert pulled[0]["title"] == "Sync me"

        r = c.post(
            f"/projects/{pid}/sync/push",
            json={
                "project_id": pid,
                "changes": [
                    {
                        "change_id": str(uuid.uuid4()),
                        "entity": "helpdesk_ticket",
                        "op": "upsert",
                        "base_version": 0,
                        "record": {
                            "id": ticket_id,
                            "title": "Sync me v2",
                            "status": "resolved",
                        },
                    }
                ],
            },
            headers=h,
        )
        assert r.status_code == 200, r.text
        assert r.json()["accepted"] == 1

        r = c.post(
            f"/projects/{pid}/sync/pull",
            json={"project_id": pid, "since": "2000-01-01T00:00:00"},
            headers=h,
        )
        assert r.status_code == 200, r.text
        pulled = {x["id"]: x for x in r.json()["helpdesk_tickets"]}
        assert pulled[ticket_id]["title"] == "Sync me v2"
        assert pulled[ticket_id]["status"] == "resolved"


def test_helpdesk_sync_delete_marks_deleted_and_is_pulled(
    tmp_path, isolated_app_factory
):
    """Helpdesk sync delete marks ticket deleted and is surfaced on pull"""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'helpdesk_delete.db'}")
    with TestClient(app) as c:
        h, pid = _setup(c)

        r = c.post(
            f"/projects/{pid}/helpdesk/tickets",
            json={"title": "Delete me"},
            headers=h,
        )
        assert r.status_code == 201, r.text
        ticket = r.json()

        r = c.post(
            f"/projects/{pid}/sync/push",
            json={
                "project_id": pid,
                "changes": [
                    {
                        "change_id": str(uuid.uuid4()),
                        "entity": "helpdesk_ticket",
                        "op": "delete",
                        "base_version": 0,
                        "record": {"id": ticket["id"]},
                    }
                ],
            },
            headers=h,
        )
        assert r.status_code == 200, r.text
        assert r.json()["accepted"] == 1

        r = c.post(
            f"/projects/{pid}/sync/pull",
            json={"project_id": pid, "since": "2000-01-01T00:00:00"},
            headers=h,
        )
        assert r.status_code == 200, r.text
        pulled = {x["id"]: x for x in r.json()["helpdesk_tickets"]}
        assert pulled[ticket["id"]]["is_deleted"] is True


def test_helpdesk_update_requires_matching_base_version(isolated_app_factory, tmp_path):
    """Helpdesk PATCH with stale base_version returns HTTP 409 with version_mismatch"""
    from fastapi.testclient import TestClient

    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path/'helpdesk_version.db'}")
    # client = TestClient(app)

    email = "owner@example.com"
    password = "StrongPass123!"

    with TestClient(app) as client:
        assert (
            client.post(
                "/register", json={"email": email, "password": password}
            ).status_code
            == 201
        )
        tok = client.post(
            "/login",
            data={"username": email, "password": password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ).json()["access_token"]

        headers = {"Authorization": f"Bearer {tok}"}

        project = client.post(
            "/projects", json={"name": "P", "description": ""}, headers=headers
        ).json()
        project_id = project["id"]

        created = client.post(
            f"/projects/{project_id}/helpdesk/tickets",
            json={"title": "Broken export", "category": "bug", "priority": "high"},
            headers=headers,
        )
        assert created.status_code == 201
        ticket = created.json()

        resp = client.patch(
            f"/projects/{project_id}/helpdesk/tickets/{ticket['id']}",
            json={"title": "Broken export 2", "base_version": 999},
            headers=headers,
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["reason"] == "version_mismatch"
        assert detail["server_version"] == 1
