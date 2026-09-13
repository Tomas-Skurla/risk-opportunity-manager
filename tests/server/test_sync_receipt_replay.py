"""Durable sync receipt outcomes are replayed without repeating mutations."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from fastapi.testclient import TestClient
from riskapp_server.sync import engine


def _setup(client: TestClient) -> tuple[str, dict[str, str]]:
    registered = client.post(
        "/register",
        json={"email": "receipt-replay@test.com", "password": "Password123!"},
    )
    assert registered.status_code == 201, registered.text
    headers = {
        "Authorization": f"Bearer {registered.json()['access_token']}"
    }
    project = client.post(
        "/projects", json={"name": "Receipt replay"}, headers=headers
    )
    assert project.status_code == 201, project.text
    return project.json()["id"], headers


def _push(client, project_id, headers, change):
    return client.post(
        f"/projects/{project_id}/sync/push",
        json={"project_id": project_id, "changes": [change]},
        headers=headers,
    )


def test_accepted_receipt_is_replayed_without_reapplying_change(
    tmp_path, isolated_app_factory
) -> None:
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'accepted.db'}")
    with TestClient(app) as client:
        project_id, headers = _setup(client)
        risk_id = str(uuid.uuid4())
        change = {
            "change_id": str(uuid.uuid4()),
            "entity": "risk",
            "op": "upsert",
            "base_version": 0,
            "record": {
                "id": risk_id,
                "title": "Created once",
                "probability": 2,
                "impact": 3,
            },
        }

        first = _push(client, project_id, headers, change)
        replay = _push(client, project_id, headers, change)

        assert first.status_code == replay.status_code == 200
        assert first.json()["results"] == [
            {
                "change_id": change["change_id"],
                "status": "accepted",
                "replayed": False,
                "entity": "risk",
                "op": "upsert",
                "entity_id": risk_id,
                "reason": None,
                "detail": None,
                "server_version": None,
                "server_record": None,
                "server_updated_at": None,
                "failure_kind": None,
                "retryable": False,
            }
        ]
        replay_body = replay.json()
        assert replay_body["accepted"] == 0
        assert replay_body["duplicates"] == 1
        assert replay_body["results"][0]["status"] == "accepted"
        assert replay_body["results"][0]["replayed"] is True
        assert replay_body["conflicts"] == []
        assert replay_body["errors"] == []

        pulled = client.post(
            f"/projects/{project_id}/sync/pull",
            json={"project_id": project_id, "since": "2000-01-01T00:00:00"},
            headers=headers,
        ).json()
        row = next(item for item in pulled["risks"] if item["id"] == risk_id)
        assert row["version"] == 1


def test_conflict_and_error_receipts_replay_the_original_outcome(
    tmp_path, isolated_app_factory
) -> None:
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'failures.db'}")
    with TestClient(app) as client:
        project_id, headers = _setup(client)
        created = client.post(
            f"/projects/{project_id}/risks",
            json={
                "type": "risk",
                "title": "Server value",
                "probability": 2,
                "impact": 2,
            },
            headers=headers,
        )
        assert created.status_code == 201, created.text

        conflict_change = {
            "change_id": str(uuid.uuid4()),
            "entity": "risk",
            "op": "upsert",
            "base_version": 0,
            "record": {
                "id": created.json()["id"],
                "title": "Stale value",
                "probability": 5,
                "impact": 5,
            },
        }
        first_conflict = _push(client, project_id, headers, conflict_change).json()
        replayed_conflict = _push(client, project_id, headers, conflict_change).json()
        assert first_conflict["results"][0]["status"] == "conflict"
        assert first_conflict["results"][0]["replayed"] is False
        assert first_conflict["results"][0]["failure_kind"] == "conflict"
        assert first_conflict["results"][0]["retryable"] is False
        first_record = first_conflict["results"][0]["server_record"]
        assert first_record["id"] == created.json()["id"]
        assert first_record["title"] == "Server value"
        assert first_record["version"] == 1
        assert replayed_conflict["results"][0]["status"] == "conflict"
        assert replayed_conflict["results"][0]["reason"] == "base_version_required"
        assert replayed_conflict["results"][0]["server_version"] == 1
        assert replayed_conflict["results"][0]["server_record"] == first_record
        assert (
            replayed_conflict["results"][0]["server_updated_at"]
            == first_conflict["results"][0]["server_updated_at"]
        )
        assert replayed_conflict["results"][0]["replayed"] is True
        assert replayed_conflict["conflicts"][0]["replayed"] is True

        error_change = {
            "change_id": str(uuid.uuid4()),
            "entity": "action",
            "op": "upsert",
            "base_version": 0,
            "record": {
                "id": str(uuid.uuid4()),
                "kind": "mitigation",
                "title": "Missing target",
            },
        }
        first_error = _push(client, project_id, headers, error_change).json()
        replayed_error = _push(client, project_id, headers, error_change).json()
        assert first_error["results"][0]["status"] == "error"
        assert first_error["results"][0]["reason"] == "http_error"
        assert first_error["results"][0]["failure_kind"] == "validation"
        assert first_error["results"][0]["retryable"] is False
        assert replayed_error["results"][0]["status"] == "error"
        assert (
            replayed_error["results"][0]["detail"]
            == first_error["results"][0]["detail"]
        )
        assert replayed_error["results"][0]["replayed"] is True
        assert replayed_error["errors"][0]["replayed"] is True


def test_transient_internal_failure_is_not_receipted_and_same_id_can_retry(
    tmp_path, isolated_app_factory, monkeypatch
) -> None:
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'transient.db'}")
    with TestClient(app) as client:
        project_id, headers = _setup(client)
        risk_id = str(uuid.uuid4())
        change = {
            "change_id": str(uuid.uuid4()),
            "entity": "risk",
            "op": "upsert",
            "base_version": 0,
            "record": {
                "id": risk_id,
                "title": "Retry me",
                "probability": 2,
                "impact": 3,
            },
        }
        # Failure injection wraps the internal upsert seam.
        # pylint: disable-next=protected-access
        original_apply = engine._apply_upsert
        attempts = 0

        def fail_once(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("temporary database fault")
            return original_apply(*args, **kwargs)

        monkeypatch.setattr(engine, "_apply_upsert", fail_once)

        first = _push(client, project_id, headers, change).json()
        assert first["results"][0]["status"] == "error"
        assert first["results"][0]["reason"] == "internal_error"
        assert first["results"][0]["failure_kind"] == "transient"
        assert first["results"][0]["retryable"] is True

        retried = _push(client, project_id, headers, change).json()
        assert retried["accepted"] == 1
        assert retried["duplicates"] == 0
        assert retried["results"][0]["status"] == "accepted"
        assert retried["results"][0]["replayed"] is False


def test_replay_requires_identical_payload_and_global_id_scope(
    tmp_path, isolated_app_factory
) -> None:
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'scope.db'}")
    with TestClient(app) as client:
        project_id, headers = _setup(client)
        risk_id = str(uuid.uuid4())
        change = {
            "change_id": str(uuid.uuid4()), "entity": "risk", "op": "upsert",
            "base_version": 0,
            "record": {
                "id": risk_id, "title": "Original",
                "probability": 2, "impact": 3,
            },
        }
        assert _push(client, project_id, headers, change).json()["accepted"] == 1
        altered = {**change, "record": {**change["record"], "title": "Changed"}}
        rejected = _push(client, project_id, headers, altered).json()
        assert rejected["duplicates"] == 0
        assert rejected["results"][0]["reason"] == "change_id_payload_mismatch"
        assert rejected["results"][0]["failure_kind"] == "validation"

        other_project = client.post(
            "/projects", json={"name": "Different scope"}, headers=headers
        ).json()["id"]
        scoped = _push(client, other_project, headers, change).json()
        assert scoped["accepted"] == 0
        assert scoped["results"][0]["reason"] == "change_id_in_use"
        assert scoped["results"][0]["server_record"] is None
        reordered = {**change, "record": dict(reversed(list(change["record"].items())))}
        assert _push(client, project_id, headers, reordered).json()["duplicates"] == 1


def test_concurrent_identical_requests_share_one_receipt(
    tmp_path, isolated_app_factory
) -> None:
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'parallel.db'}")
    with TestClient(app) as client:
        project_id, headers = _setup(client)
        change = {
            "change_id": str(uuid.uuid4()), "entity": "risk", "op": "upsert",
            "base_version": 0,
            "record": {
                "id": str(uuid.uuid4()), "title": "One write",
                "probability": 2, "impact": 3,
            },
        }
        with ThreadPoolExecutor(max_workers=2) as pool:
            bodies = list(pool.map(
                lambda _: _push(client, project_id, headers, change).json(), range(2)
            ))
        assert sorted(body["accepted"] for body in bodies) == [0, 1]
        assert sorted(body["duplicates"] for body in bodies) == [0, 1]


def test_pre_migration_receipt_cannot_replay_unverifiable_payload(
    tmp_path, isolated_app_factory
) -> None:
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'legacy.db'}")
    with TestClient(app) as client:
        project_id, headers = _setup(client)
        change = {
            "change_id": str(uuid.uuid4()), "entity": "risk", "op": "upsert",
            "base_version": 0,
            "record": {
                "id": str(uuid.uuid4()), "title": "Legacy",
                "probability": 2, "impact": 3,
            },
        }
        assert _push(client, project_id, headers, change).json()["accepted"] == 1
        # pylint: disable-next=import-outside-toplevel
        from riskapp_server.db.session import SessionLocal, SyncReceipt

        with SessionLocal() as db:
            receipt = db.get(SyncReceipt, uuid.UUID(change["change_id"]))
            assert receipt is not None
            receipt.payload_hash = None
            db.commit()
        replay = _push(client, project_id, headers, change).json()
        assert replay["duplicates"] == 0
        assert replay["results"][0]["reason"] == "receipt_unverifiable"


def test_audit_prune_keeps_receipts_inside_idempotency_window(
    tmp_path, isolated_app_factory
) -> None:
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'retention.db'}")
    with TestClient(app) as client:
        project_id, headers = _setup(client)
        change = {
            "change_id": str(uuid.uuid4()), "entity": "risk", "op": "upsert",
            "base_version": 0,
            "record": {
                "id": str(uuid.uuid4()), "title": "Keep receipt",
                "probability": 2, "impact": 3,
            },
        }
        assert _push(client, project_id, headers, change).json()["accepted"] == 1
        # pylint: disable-next=import-outside-toplevel
        from riskapp_server.db.session import SessionLocal, SyncReceipt, utcnow

        with SessionLocal() as db:
            receipt = db.get(SyncReceipt, uuid.UUID(change["change_id"]))
            assert receipt is not None
            receipt.processed_at = utcnow() - timedelta(days=200)
            db.commit()
        pruned = client.post(
            f"/projects/{project_id}/maintenance/prune?days=1", headers=headers
        )
        assert pruned.status_code == 200
        assert pruned.json()["sync_receipts_deleted"] == 0
        assert _push(client, project_id, headers, change).json()["duplicates"] == 1
