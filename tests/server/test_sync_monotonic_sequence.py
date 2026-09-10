"""Transactional monotonic synchronization-feed tests."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi.testclient import TestClient

_SYNC_EPOCH = "1970-01-01T00:00:00"


def _setup(client: TestClient, email: str) -> tuple[str, dict[str, str]]:
    registered = client.post(
        "/register", json={"email": email, "password": "Password123!"}
    )
    assert registered.status_code == 201, registered.text
    headers = {
        "Authorization": f"Bearer {registered.json()['access_token']}"
    }
    project = client.post(
        "/projects", json={"name": "Sequence feed"}, headers=headers
    )
    assert project.status_code == 201, project.text
    return project.json()["id"], headers


def _create_risk(
    client: TestClient,
    headers: dict[str, str],
    project_id: str,
    title: str,
    *,
    code: str | None = None,
) -> dict:
    payload = {
        "type": "risk",
        "title": title,
        "probability": 2,
        "impact": 3,
    }
    if code is not None:
        payload["code"] = code
    response = client.post(
        f"/projects/{project_id}/risks",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _pull(
    client: TestClient,
    headers: dict[str, str],
    project_id: str,
    *,
    since: str = _SYNC_EPOCH,
    since_sequence: int = 0,
    **pagination: object,
) -> dict:
    response = client.post(
        f"/projects/{project_id}/sync/pull",
        json={
            "project_id": project_id,
            "since": since,
            "since_sequence": since_sequence,
            **pagination,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_sequence_pull_finds_an_update_with_an_older_timestamp(
    tmp_path, isolated_app_factory, monkeypatch
) -> None:
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'late.db'}")
    with TestClient(app) as client:
        project_id, headers = _setup(client, "late-commit@test.com")
        risk = _create_risk(client, headers, project_id, "Before")
        initial = _pull(client, headers, project_id)

        # Simulate the timestamp ordering hazard: a later transaction publishes
        # a row whose application timestamp is older than the prior watermark.
        from riskapp_server.core import items_crud

        monkeypatch.setattr(items_crud, "utcnow", lambda: datetime(2001, 1, 1))
        updated = client.patch(
            f"/projects/{project_id}/risks/{risk['id']}",
            json={"title": "After", "base_version": risk["version"]},
            headers=headers,
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["updated_at"].startswith("2001-01-01")

        incremental = _pull(
            client,
            headers,
            project_id,
            since=initial["server_time"],
            since_sequence=initial["server_sequence"],
        )
        assert [row["id"] for row in incremental["risks"]] == [risk["id"]]
        assert incremental["risks"][0]["title"] == "After"
        assert incremental["server_sequence"] > initial["server_sequence"]


def test_sequence_snapshot_stays_fixed_across_pagination(
    tmp_path, isolated_app_factory
) -> None:
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'pages.db'}")
    with TestClient(app) as client:
        project_id, headers = _setup(client, "sequence-pages@test.com")
        first_risk = _create_risk(client, headers, project_id, "First")
        second_risk = _create_risk(client, headers, project_id, "Second")

        first_page = _pull(
            client,
            headers,
            project_id,
            limit_per_entity=1,
        )
        assert first_page["has_more"]["risks"] is True
        assert first_page["cursors"]["risks"].startswith("seq:")
        snapshot_sequence = first_page["server_sequence"]

        third_risk = _create_risk(client, headers, project_id, "Third")
        second_page = _pull(
            client,
            headers,
            project_id,
            since_sequence=0,
            limit_per_entity=1,
            cursors=first_page["cursors"],
            snapshot_time=first_page["server_time"],
            snapshot_sequence=snapshot_sequence,
        )
        assert second_page["server_sequence"] == snapshot_sequence
        assert {first_page["risks"][0]["id"], second_page["risks"][0]["id"]} == {
            first_risk["id"],
            second_risk["id"],
        }

        next_pull = _pull(
            client,
            headers,
            project_id,
            since=first_page["server_time"],
            since_sequence=snapshot_sequence,
        )
        assert [row["id"] for row in next_pull["risks"]] == [third_risk["id"]]


def test_rolled_back_write_does_not_consume_a_sequence(
    tmp_path, isolated_app_factory
) -> None:
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'rollback.db'}")
    with TestClient(app) as client:
        project_id, headers = _setup(client, "sequence-rollback@test.com")
        _create_risk(client, headers, project_id, "First", code="R-SAME")
        initial = _pull(client, headers, project_id)

        duplicate = client.post(
            f"/projects/{project_id}/risks",
            json={
                "type": "risk",
                "title": "Rejected",
                "probability": 2,
                "impact": 2,
                "code": "R-SAME",
            },
            headers=headers,
        )
        assert duplicate.status_code == 409

        accepted = _create_risk(
            client, headers, project_id, "Second", code="R-OTHER"
        )
        incremental = _pull(
            client,
            headers,
            project_id,
            since=initial["server_time"],
            since_sequence=initial["server_sequence"],
        )

        assert incremental["server_sequence"] == initial["server_sequence"] + 1
        assert [row["id"] for row in incremental["risks"]] == [accepted["id"]]


def test_every_syncable_entity_uses_one_project_sequence(
    tmp_path, isolated_app_factory
) -> None:
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'entities.db'}")
    with TestClient(app) as client:
        project_id, headers = _setup(client, "sequence-entities@test.com")
        risk = _create_risk(client, headers, project_id, "Parent")

        action = client.post(
            f"/projects/{project_id}/actions",
            json={
                "risk_id": risk["id"],
                "kind": "mitigation",
                "title": "Reduce exposure",
            },
            headers=headers,
        )
        assert action.status_code == 201, action.text

        assessment = client.put(
            f"/projects/{project_id}/risks/{risk['id']}/assessment",
            json={"probability": 3, "impact": 4, "notes": "Reviewed"},
            headers=headers,
        )
        assert assessment.status_code == 200, assessment.text

        ticket = client.post(
            f"/projects/{project_id}/helpdesk/tickets",
            json={"title": "Need help"},
            headers=headers,
        )
        assert ticket.status_code == 201, ticket.text

        pulled = _pull(client, headers, project_id)
        assert pulled["server_sequence"] == 4
        assert [row["id"] for row in pulled["risks"]] == [risk["id"]]
        assert [row["id"] for row in pulled["actions"]] == [action.json()["id"]]
        assert [row["id"] for row in pulled["assessments"]] == [
            assessment.json()["id"]
        ]
        assert [row["id"] for row in pulled["helpdesk_tickets"]] == [
            ticket.json()["id"]
        ]

        import riskapp_server.db.session as session
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        with Session(session.engine) as db:
            sequences = [
                db.execute(
                    select(model.change_sequence).where(model.id == entity_id)
                ).scalar_one()
                for model, entity_id in (
                    (session.Item, uuid.UUID(risk["id"])),
                    (session.Action, uuid.UUID(action.json()["id"])),
                    (session.Assessment, uuid.UUID(assessment.json()["id"])),
                    (session.HelpDeskTicket, uuid.UUID(ticket.json()["id"])),
                )
            ]
        assert sorted(sequences) == [1, 2, 3, 4]
