"""Transactional monotonic synchronization-feed tests."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi.testclient import TestClient
from support import User, create_item, create_project, pull, register_user

# Imports stay local to the modules reloaded for each isolated test app.
# pylint: disable=import-outside-toplevel


def _pull(client: TestClient, project_id: str, user: User, **params: Any) -> dict:
    """Pull and return the body; every pull in these tests must succeed."""
    response = pull(client, project_id, user, **params)
    assert response.status_code == 200, response.text
    return response.json()


def test_sequence_pull_finds_an_update_with_an_older_timestamp(
    api, monkeypatch
) -> None:

    user = register_user(api)
    project = create_project(api, user, name="Sequence feed")
    project_id = project.id
    risk = create_item(api, project, user, kind="risk", title="Before")
    initial = _pull(api, project_id, user)

    # Simulate the timestamp ordering hazard: a later transaction publishes
    # a row whose application timestamp is older than the prior watermark.
    from riskapp_server.core import items_crud

    monkeypatch.setattr(items_crud, "utcnow", lambda: datetime(2001, 1, 1))
    updated = api.patch(
        f"/projects/{project_id}/risks/{risk.id}",
        json={"title": "After", "base_version": risk.version},
        headers=user.headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["updated_at"].startswith("2001-01-01")

    incremental = _pull(
        api,
        project_id,
        user,
        since_sequence=initial["server_sequence"],
    )
    assert [row["id"] for row in incremental["risks"]] == [risk.id]
    assert incremental["risks"][0]["title"] == "After"
    assert incremental["server_sequence"] > initial["server_sequence"]


def test_sequence_snapshot_stays_fixed_across_pagination(api) -> None:
    user = register_user(api)
    project = create_project(api, user, name="Sequence feed")
    project_id = project.id
    first_risk = create_item(api, project, user, kind="risk", title="First")
    second_risk = create_item(api, project, user, kind="risk", title="Second")

    first_page = _pull(
        api,
        project_id,
        user,
        limit_per_entity=1,
    )
    assert first_page["has_more"]["risks"] is True
    assert first_page["cursors"]["risks"].startswith("seq:")
    snapshot_sequence = first_page["server_sequence"]

    third_risk = create_item(api, project, user, kind="risk", title="Third")
    second_page = _pull(
        api,
        project_id,
        user,
        since_sequence=0,
        limit_per_entity=1,
        cursors=first_page["cursors"],
        snapshot_sequence=snapshot_sequence,
    )
    assert second_page["server_sequence"] == snapshot_sequence
    assert {first_page["risks"][0]["id"], second_page["risks"][0]["id"]} == {
        first_risk.id,
        second_risk.id,
    }

    next_pull = _pull(
        api,
        project_id,
        user,
        since_sequence=snapshot_sequence,
    )
    assert [row["id"] for row in next_pull["risks"]] == [third_risk.id]


def test_rolled_back_write_does_not_consume_a_sequence(api) -> None:
    user = register_user(api)
    project = create_project(api, user, name="Sequence feed")
    project_id = project.id
    create_item(api, project, user, kind="risk", title="First", code="R-SAME")
    initial = _pull(api, project_id, user)

    duplicate = api.post(
        f"/projects/{project_id}/risks",
        json={
            "type": "risk",
            "title": "Rejected",
            "probability": 2,
            "impact": 2,
            "code": "R-SAME",
        },
        headers=user.headers,
    )
    assert duplicate.status_code == 409

    accepted = create_item(
        api, project, user, kind="risk", title="Second", code="R-OTHER"
    )
    incremental = _pull(
        api,
        project_id,
        user,
        since_sequence=initial["server_sequence"],
    )

    assert incremental["server_sequence"] == initial["server_sequence"] + 1
    assert [row["id"] for row in incremental["risks"]] == [accepted.id]


def test_every_syncable_entity_uses_one_project_sequence(api) -> None:
    user = register_user(api)
    project = create_project(api, user, name="Sequence feed")
    project_id = project.id
    risk = create_item(api, project, user, kind="risk", title="Parent")

    action = api.post(
        f"/projects/{project_id}/actions",
        json={
            "risk_id": risk.id,
            "kind": "mitigation",
            "title": "Reduce exposure",
        },
        headers=user.headers,
    )
    assert action.status_code == 201, action.text

    assessment = api.put(
        f"/projects/{project_id}/risks/{risk.id}/assessment",
        json={
            "probability": 3,
            "impact": 4,
            "notes": "Reviewed",
            "base_version": 0,
        },
        headers=user.headers,
    )
    assert assessment.status_code == 200, assessment.text

    ticket = api.post(
        f"/projects/{project_id}/helpdesk/tickets",
        json={"title": "Need help"},
        headers=user.headers,
    )
    assert ticket.status_code == 201, ticket.text

    pulled = _pull(api, project_id, user)
    assert pulled["server_sequence"] == 4
    assert [row["id"] for row in pulled["risks"]] == [risk.id]
    assert [row["id"] for row in pulled["actions"]] == [action.json()["id"]]
    assert [row["id"] for row in pulled["assessments"]] == [assessment.json()["id"]]
    assert [row["id"] for row in pulled["helpdesk_tickets"]] == [ticket.json()["id"]]

    import riskapp_server.db.session as session
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    with Session(session.engine) as db:
        sequences = [
            db.execute(
                select(model.change_sequence).where(model.id == entity_id)
            ).scalar_one()
            for model, entity_id in (
                (session.Item, uuid.UUID(risk.id)),
                (session.Action, uuid.UUID(action.json()["id"])),
                (session.Assessment, uuid.UUID(assessment.json()["id"])),
                (session.HelpDeskTicket, uuid.UUID(ticket.json()["id"])),
            )
        ]
    assert sorted(sequences) == [1, 2, 3, 4]
