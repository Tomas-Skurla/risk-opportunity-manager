"""Atomic optimistic-concurrency guarantees for synchronized entities."""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient


def _setup_entities(client: TestClient) -> tuple[str, dict[str, str], dict[str, dict]]:
    registered = client.post(
        "/register",
        json={"email": "atomic-sync@test.com", "password": "Password123!"},
    )
    assert registered.status_code == 201, registered.text
    headers = {
        "Authorization": f"Bearer {registered.json()['access_token']}"
    }
    project = client.post(
        "/projects", json={"name": "Atomic Sync"}, headers=headers
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]

    risk = client.post(
        f"/projects/{project_id}/risks",
        json={
            "type": "risk",
            "title": "Risk",
            "probability": 2,
            "impact": 3,
        },
        headers=headers,
    )
    opportunity = client.post(
        f"/projects/{project_id}/opportunities",
        json={
            "type": "opportunity",
            "title": "Opportunity",
            "probability": 3,
            "impact": 2,
        },
        headers=headers,
    )
    assert risk.status_code == 201, risk.text
    assert opportunity.status_code == 201, opportunity.text

    action = client.post(
        f"/projects/{project_id}/actions",
        json={
            "risk_id": risk.json()["id"],
            "kind": "mitigation",
            "title": "Action",
        },
        headers=headers,
    )
    assessment = client.put(
        f"/projects/{project_id}/risks/{risk.json()['id']}/assessment",
        json={"probability": 2, "impact": 3, "notes": "Assessment"},
        headers=headers,
    )
    ticket = client.post(
        f"/projects/{project_id}/helpdesk/tickets",
        json={"title": "Ticket"},
        headers=headers,
    )
    for response in (action, assessment, ticket):
        assert response.status_code in {200, 201}, response.text

    return project_id, headers, {
        "risk": risk.json(),
        "opportunity": opportunity.json(),
        "action": action.json(),
        "assessment": assessment.json(),
        "helpdesk_ticket": ticket.json(),
    }


def _update_records(entities: dict[str, dict]) -> dict[str, dict]:
    risk_id = entities["risk"]["id"]
    return {
        "risk": {
            "id": risk_id,
            "title": "Risk updated",
            "probability": 4,
            "impact": 3,
        },
        "opportunity": {
            "id": entities["opportunity"]["id"],
            "title": "Opportunity updated",
            "probability": 4,
            "impact": 4,
        },
        "action": {
            "id": entities["action"]["id"],
            "risk_id": risk_id,
            "kind": "mitigation",
            "title": "Action updated",
        },
        "assessment": {
            "id": entities["assessment"]["id"],
            "risk_id": risk_id,
            "probability": 4,
            "impact": 4,
            "notes": "Assessment updated",
        },
        "helpdesk_ticket": {
            "id": entities["helpdesk_ticket"]["id"],
            "title": "Ticket updated",
            "status": "resolved",
        },
    }


def _push_payload(
    project_id: str, records: dict[str, dict], *, base_version: int | None
) -> dict:
    return {
        "project_id": project_id,
        "changes": [
            {
                "change_id": str(uuid.uuid4()),
                "entity": entity,
                "op": "upsert",
                "base_version": base_version,
                "record": record,
            }
            for entity, record in records.items()
        ],
    }


def test_all_existing_sync_entity_types_require_and_claim_base_version(
    tmp_path, isolated_app_factory
) -> None:
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'all-types.db'}")
    with TestClient(app) as client:
        project_id, headers, entities = _setup_entities(client)
        records = _update_records(entities)

        for absent_version in (None, 0):
            missing = client.post(
                f"/projects/{project_id}/sync/push",
                json=_push_payload(
                    project_id, records, base_version=absent_version
                ),
                headers=headers,
            )
            assert missing.status_code == 200, missing.text
            missing_body = missing.json()
            assert missing_body["accepted"] == 0
            assert {
                conflict["entity"] for conflict in missing_body["conflicts"]
            } == set(records)
            assert {
                conflict["reason"] for conflict in missing_body["conflicts"]
            } == {"base_version_required"}
            assert {
                conflict["server_version"]
                for conflict in missing_body["conflicts"]
            } == {1}

        accepted = client.post(
            f"/projects/{project_id}/sync/push",
            json=_push_payload(project_id, records, base_version=1),
            headers=headers,
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["accepted"] == 5
        assert accepted.json()["conflicts"] == []
        assert accepted.json()["errors"] == []

        pulled = client.post(
            f"/projects/{project_id}/sync/pull",
            json={"project_id": project_id, "since": "2000-01-01T00:00:00"},
            headers=headers,
        )
        assert pulled.status_code == 200, pulled.text
        body = pulled.json()
        collections = {
            "risk": body["risks"],
            "opportunity": body["opportunities"],
            "action": body["actions"],
            "assessment": body["assessments"],
            "helpdesk_ticket": body["helpdesk_tickets"],
        }
        for entity, rows in collections.items():
            row = next(item for item in rows if item["id"] == entities[entity]["id"])
            assert row["version"] == 2


@pytest.mark.parametrize(
    ("entity", "table"),
    [
        ("risk", "items"),
        ("opportunity", "items"),
        ("action", "actions"),
        ("assessment", "assessments"),
        ("helpdesk_ticket", "helpdesk_tickets"),
    ],
)
def test_version_claim_sql_is_conditional_for_every_entity(entity, table) -> None:
    from riskapp_server.sync import engine
    from sqlalchemy.dialects import sqlite

    db = Mock()
    db.execute.return_value = SimpleNamespace(rowcount=1)

    engine._claim_base_version(
        db,
        entity,
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        7,
    )

    statement = db.execute.call_args.args[0]
    compiled = str(statement.compile(dialect=sqlite.dialect()))
    assert compiled.startswith(f"UPDATE {table} SET")
    assert f"{table}.version = ?" in compiled


def test_two_concurrent_sync_updates_cannot_claim_the_same_sqlite_version(
    tmp_path, isolated_app_factory, monkeypatch
) -> None:
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'concurrent.db'}")
    with TestClient(app) as client:
        project_id, headers, entities = _setup_entities(client)
        risk_id = entities["risk"]["id"]

        from riskapp_server.sync import engine

        original_begin = engine._begin_push_transaction
        barrier = threading.Barrier(2)

        def synchronized_begin(db) -> None:
            barrier.wait(timeout=10)
            original_begin(db)

        monkeypatch.setattr(engine, "_begin_push_transaction", synchronized_begin)

        def push(title: str):
            return client.post(
                f"/projects/{project_id}/sync/push",
                json={
                    "project_id": project_id,
                    "changes": [
                        {
                            "change_id": str(uuid.uuid4()),
                            "entity": "risk",
                            "op": "upsert",
                            "base_version": 1,
                            "record": {
                                "id": risk_id,
                                "title": title,
                                "probability": 3,
                                "impact": 3,
                            },
                        }
                    ],
                },
                headers=headers,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(push, ("Writer A", "Writer B")))

        for response in responses:
            assert response.status_code == 200, response.text
        bodies = [response.json() for response in responses]
        assert sorted(body["accepted"] for body in bodies) == [0, 1]
        loser = next(body for body in bodies if body["accepted"] == 0)
        assert loser["conflicts"][0]["reason"] == "version_mismatch"
        assert loser["conflicts"][0]["server_version"] == 2
