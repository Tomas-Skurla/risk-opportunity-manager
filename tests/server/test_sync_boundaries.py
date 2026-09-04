"""Sync pagination, authorization, and defensive engine boundaries."""

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


def _create_risk(
    client: TestClient, headers: dict[str, str], project_id: str, title: str
) -> dict:
    response = client.post(
        f"/projects/{project_id}/risks",
        json={
            "type": "risk",
            "title": title,
            "probability": 2,
            "impact": 3,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_sync_pull_cursor_paginates_and_rejects_malformed_requests(
    tmp_path, isolated_app_factory
) -> None:
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'pull.db'}")
    with TestClient(app) as client:
        _, headers = _register(client, "pull-branches@test.com")
        project_id = client.post(
            "/projects", json={"name": "Sync"}, headers=headers
        ).json()["id"]
        first_risk = _create_risk(client, headers, project_id, "First")
        second_risk = _create_risk(client, headers, project_id, "Second")

        first_page = client.post(
            f"/projects/{project_id}/sync/pull",
            json={
                "project_id": project_id,
                "since": "2000-01-01T00:00:00+00:00",
                "limit_per_entity": 1,
            },
            headers=headers,
        )
        assert first_page.status_code == 200, first_page.text
        page = first_page.json()
        assert page["has_more"]["risks"] is True
        assert len(page["risks"]) == 1
        snapshot_time = page["server_time"]

        # A row created after page one belongs to the next pull, not to a later
        # page in this already-open snapshot.
        third_risk = _create_risk(client, headers, project_id, "Third")

        second_page = client.post(
            f"/projects/{project_id}/sync/pull",
            json={
                "project_id": project_id,
                "since": "2000-01-01T00:00:00",
                "limit_per_entity": 1,
                "cursors": page["cursors"],
                "snapshot_time": snapshot_time,
            },
            headers=headers,
        )
        assert second_page.status_code == 200, second_page.text
        second = second_page.json()
        assert second["server_time"] == snapshot_time
        assert second["has_more"]["risks"] is False
        assert {page["risks"][0]["id"], second["risks"][0]["id"]} == {
            first_risk["id"],
            second_risk["id"],
        }

        next_pull = client.post(
            f"/projects/{project_id}/sync/pull",
            json={"project_id": project_id, "since": snapshot_time},
            headers=headers,
        )
        assert next_pull.status_code == 200, next_pull.text
        assert [row["id"] for row in next_pull.json()["risks"]] == [third_risk["id"]]

        missing_snapshot = client.post(
            f"/projects/{project_id}/sync/pull",
            json={
                "project_id": project_id,
                "since": "2000-01-01T00:00:00",
                "limit_per_entity": 1,
                "cursors": page["cursors"],
            },
            headers=headers,
        )
        assert missing_snapshot.status_code == 422

        malformed_cursor = client.post(
            f"/projects/{project_id}/sync/pull",
            json={
                "project_id": project_id,
                "since": "2000-01-01T00:00:00",
                "limit_per_entity": 1,
                "cursors": {"risks": "not-a-cursor"},
                "snapshot_time": snapshot_time,
            },
            headers=headers,
        )
        assert malformed_cursor.status_code == 400
        assert malformed_cursor.json()["detail"] == "Invalid cursor"

        future_snapshot = client.post(
            f"/projects/{project_id}/sync/pull",
            json={
                "project_id": project_id,
                "since": "2000-01-01T00:00:00",
                "snapshot_time": "2999-01-01T00:00:00Z",
            },
            headers=headers,
        )
        assert future_snapshot.status_code == 400
        assert future_snapshot.json()["detail"] == "snapshot_time is in the future"

        another_project = str(uuid.uuid4())
        pull_mismatch = client.post(
            f"/projects/{project_id}/sync/pull",
            json={"project_id": another_project, "since": "2000-01-01T00:00:00"},
            headers=headers,
        )
        assert pull_mismatch.status_code == 400
        push_mismatch = client.post(
            f"/projects/{project_id}/sync/push",
            json={"project_id": another_project, "changes": []},
            headers=headers,
        )
        assert push_mismatch.status_code == 400


def test_sync_engine_records_invalid_changes_and_member_delete_denials(
    tmp_path, isolated_app_factory
) -> None:
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'push.db'}")
    with TestClient(app) as client:
        admin, admin_headers = _register(client, "sync-admin@test.com")
        member, member_headers = _register(client, "sync-member@test.com")
        project_id = client.post(
            "/projects", json={"name": "Sync"}, headers=admin_headers
        ).json()["id"]
        added = client.post(
            f"/projects/{project_id}/members",
            json={"user_email": "sync-member@test.com", "role": "member"},
            headers=admin_headers,
        )
        assert added.status_code == 201, added.text
        risk = _create_risk(client, admin_headers, project_id, "Protected")

        denied = client.post(
            f"/projects/{project_id}/sync/push",
            json={
                "project_id": project_id,
                "changes": [
                    {
                        "change_id": str(uuid.uuid4()),
                        "entity": "risk",
                        "op": "upsert",
                        "base_version": risk["version"],
                        "record": {"id": risk["id"], "status": "deleted"},
                    },
                    {
                        "change_id": str(uuid.uuid4()),
                        "entity": "risk",
                        "op": "delete",
                        "base_version": risk["version"],
                        "record": {"id": risk["id"]},
                    },
                ],
            },
            headers=member_headers,
        )
        assert denied.status_code == 200, denied.text
        assert denied.json()["accepted"] == 0
        assert [error["reason"] for error in denied.json()["errors"]] == [
            "insufficient_permissions",
            "insufficient_permissions",
        ]

        import riskapp_server.db.session as session
        import riskapp_server.sync.engine as engine
        from riskapp_server.schemas.models import SyncChange
        from sqlalchemy.orm import Session

        def constructed(*, entity: str, op: str, record: dict) -> SyncChange:
            return SyncChange.model_construct(
                change_id=uuid.uuid4(),
                entity=entity,
                op=op,
                base_version=None,
                record=record,
            )

        missing_id = str(uuid.uuid4())
        changes = [
            constructed(entity="unknown", op="upsert", record={}),
            constructed(entity="risk", op="rename", record={}),
            constructed(entity="risk", op="upsert", record={"id": "bad-uuid"}),
            constructed(
                entity="action",
                op="upsert",
                record={"id": str(uuid.uuid4()), "title": "No target"},
            ),
            constructed(entity="risk", op="delete", record={"id": missing_id}),
        ]
        with Session(session.engine) as db:
            result = engine.push_changes(
                db,
                uuid.UUID(admin["user_id"]),
                uuid.UUID(project_id),
                changes,
            )
            empty = engine.push_changes(
                db,
                uuid.UUID(admin["user_id"]),
                uuid.UUID(project_id),
                [],
            )

        assert result["accepted"] == 1
        assert [error["reason"] for error in result["errors"]] == [
            "unknown_entity",
            "unknown_op",
            "http_error",
            "http_error",
        ]
        assert empty["accepted"] == 0
        assert empty["errors"] == []
        assert member["user_id"] != admin["user_id"]
