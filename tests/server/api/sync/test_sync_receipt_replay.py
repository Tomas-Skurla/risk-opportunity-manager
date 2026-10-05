"""Durable sync receipt outcomes are replayed without repeating mutations."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from riskapp_server.sync import engine
from support import (
    create_project,
    new_change,
    newly_accepted,
    promote_to_superuser,
    pull,
    push,
    register_user,
    replayed,
    results_with,
)


def test_accepted_receipt_is_replayed_without_reapplying_change(api) -> None:
    user = register_user(api)
    project_id = create_project(api, user, name="Receipt replay").id
    risk_id = str(uuid.uuid4())
    change = new_change(
        "risk",
        {
            "id": risk_id,
            "title": "Created once",
            "probability": 2,
            "impact": 3,
        },
        base_version=0,
    )
    first = push(api, project_id, user, change)
    replay = push(api, project_id, user, change)

    assert first.status_code == replay.status_code == 200
    first_result = first.json()["results"][0]
    assert first_result["change_id"] == change["change_id"]
    assert first_result["status"] == "accepted"
    assert first_result["replayed"] is False
    assert first_result["entity"] == "risk"
    assert first_result["op"] == "upsert"
    assert first_result["entity_id"] == risk_id
    assert first_result["server_version"] == 1
    assert first_result["server_record"]["id"] == risk_id
    assert first_result["server_record"]["title"] == "Created once"
    assert first_result["server_record"]["version"] == 1
    replay_body = replay.json()
    assert len(newly_accepted(replay_body)) == 0
    assert len(replayed(replay_body)) == 1
    assert replay_body["results"][0]["status"] == "accepted"
    assert replay_body["results"][0]["replayed"] is True
    assert replay_body["results"][0]["server_version"] == 1
    assert replay_body["results"][0]["server_record"] == (first_result["server_record"])
    assert results_with(replay_body, "conflict") == []
    assert results_with(replay_body, "error") == []

    pulled = pull(api, project_id, user).json()
    row = next(item for item in pulled["risks"] if item["id"] == risk_id)
    assert row["version"] == 1


def test_accepted_receipt_replay_returns_the_current_server_row(api) -> None:
    user = register_user(api)
    project_id = create_project(api, user, name="Receipt replay").id
    risk_id = str(uuid.uuid4())

    original = new_change(
        "risk",
        {
            "id": risk_id,
            "title": "Original",
            "probability": 2,
            "impact": 3,
        },
        base_version=0,
    )
    assert len(newly_accepted(push(api, project_id, user, original).json())) == 1

    newer = new_change(
        "risk",
        {
            "id": risk_id,
            "title": "Newer server value",
            "probability": 5,
            "impact": 4,
        },
        base_version=1,
    )
    assert len(newly_accepted(push(api, project_id, user, newer).json())) == 1
    replay = push(api, project_id, user, original).json()

    assert len(replayed(replay)) == 1
    result = replay["results"][0]
    assert result["replayed"] is True
    assert result["receipt_server_version"] == 1
    assert result["server_version"] == 2
    assert result["server_record"]["version"] == 2
    assert result["server_record"]["title"] == "Newer server value"


def test_conflict_and_error_receipts_replay_the_original_outcome(api) -> None:
    user = register_user(api)
    project_id = create_project(api, user, name="Receipt replay").id
    created = api.post(
        f"/projects/{project_id}/risks",
        json={
            "type": "risk",
            "title": "Server value",
            "probability": 2,
            "impact": 2,
        },
        headers=user.headers,
    )
    assert created.status_code == 201, created.text

    conflict_change = new_change(
        "risk",
        {
            "id": created.json()["id"],
            "title": "Stale value",
            "probability": 5,
            "impact": 5,
        },
        base_version=0,
    )
    first_conflict = push(api, project_id, user, conflict_change).json()
    replayed_conflict = push(api, project_id, user, conflict_change).json()

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
    assert results_with(replayed_conflict, "conflict")[0]["replayed"] is True

    error_change = new_change(
        "action",
        {
            "id": str(uuid.uuid4()),
            "kind": "mitigation",
            "title": "Missing target",
        },
        base_version=0,
    )
    first_error = push(api, project_id, user, error_change).json()
    replayed_error = push(api, project_id, user, error_change).json()
    assert first_error["results"][0]["status"] == "error"
    assert first_error["results"][0]["reason"] == "http_error"
    assert first_error["results"][0]["failure_kind"] == "validation"
    assert first_error["results"][0]["retryable"] is False
    assert replayed_error["results"][0]["status"] == "error"
    assert replayed_error["results"][0]["detail"] == first_error["results"][0]["detail"]
    assert replayed_error["results"][0]["replayed"] is True
    assert results_with(replayed_error, "error")[0]["replayed"] is True


def test_transient_internal_failure_is_not_receipted_and_same_id_can_retry(
    api, monkeypatch
) -> None:
    user = register_user(api)
    project_id = create_project(api, user, name="Receipt replay").id
    risk_id = str(uuid.uuid4())
    change = new_change(
        "risk",
        {
            "id": risk_id,
            "title": "Retry me",
            "probability": 2,
            "impact": 3,
        },
        base_version=0,
    )
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

    first = push(api, project_id, user, change).json()
    assert first["results"][0]["status"] == "error"
    assert first["results"][0]["reason"] == "internal_error"
    assert first["results"][0]["failure_kind"] == "transient"
    assert first["results"][0]["retryable"] is True

    retried = push(api, project_id, user, change).json()
    assert len(newly_accepted(retried)) == 1
    assert len(replayed(retried)) == 0
    assert retried["results"][0]["status"] == "accepted"
    assert retried["results"][0]["replayed"] is False


def test_replay_requires_identical_payload_and_global_id_scope(api) -> None:
    user = register_user(api)
    project_id = create_project(api, user, name="Receipt replay").id
    risk_id = str(uuid.uuid4())
    change = new_change(
        "risk",
        {
            "id": risk_id,
            "title": "Original",
            "probability": 2,
            "impact": 3,
        },
        base_version=0,
    )
    assert len(newly_accepted(push(api, project_id, user, change).json())) == 1
    altered = {**change, "record": {**change["record"], "title": "Changed"}}
    rejected = push(api, project_id, user, altered).json()
    assert len(replayed(rejected)) == 0
    assert rejected["results"][0]["reason"] == "change_id_payload_mismatch"
    assert rejected["results"][0]["failure_kind"] == "validation"

    other_project = api.post(
        "/projects", json={"name": "Different scope"}, headers=user.headers
    ).json()["id"]
    scoped = push(api, other_project, user, change).json()
    assert len(newly_accepted(scoped)) == 0
    assert scoped["results"][0]["reason"] == "change_id_in_use"
    assert scoped["results"][0]["server_record"] is None
    reordered = {**change, "record": dict(reversed(list(change["record"].items())))}
    assert len(replayed(push(api, project_id, user, reordered).json())) == 1


def test_concurrent_identical_requests_share_one_receipt(api) -> None:
    user = register_user(api)
    project_id = create_project(api, user, name="Receipt replay").id
    change = new_change(
        "risk",
        {
            "id": str(uuid.uuid4()),
            "title": "One write",
            "probability": 2,
            "impact": 3,
        },
        base_version=0,
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        bodies = list(
            pool.map(lambda _: push(api, project_id, user, change).json(), range(2))
        )
    assert sorted(len(newly_accepted(body)) for body in bodies) == [0, 1]
    assert sorted(len(replayed(body)) for body in bodies) == [0, 1]


def test_pre_migration_receipt_cannot_replay_unverifiable_payload(api) -> None:
    user = register_user(api)
    project_id = create_project(api, user, name="Receipt replay").id
    change = new_change(
        "risk",
        {
            "id": str(uuid.uuid4()),
            "title": "Legacy",
            "probability": 2,
            "impact": 3,
        },
        base_version=0,
    )
    assert len(newly_accepted(push(api, project_id, user, change).json())) == 1
    # pylint: disable-next=import-outside-toplevel
    from riskapp_server.db.session import SessionLocal, SyncReceipt

    with SessionLocal() as db:
        receipt = db.get(SyncReceipt, uuid.UUID(change["change_id"]))
        assert receipt is not None
        receipt.payload_hash = None
        db.commit()
    replay = push(api, project_id, user, change).json()
    assert len(replayed(replay)) == 0
    assert replay["results"][0]["reason"] == "receipt_unverifiable"


def test_audit_prune_keeps_receipts_inside_idempotency_window(api) -> None:
    user = register_user(api)
    project_id = create_project(api, user, name="Receipt replay").id
    change = new_change(
        "risk",
        {
            "id": str(uuid.uuid4()),
            "title": "Keep receipt",
            "probability": 2,
            "impact": 3,
        },
        base_version=0,
    )
    assert len(newly_accepted(push(api, project_id, user, change).json())) == 1
    # pylint: disable-next=import-outside-toplevel
    from riskapp_server.db.session import SessionLocal, SyncReceipt, utcnow

    with SessionLocal() as db:
        receipt = db.get(SyncReceipt, uuid.UUID(change["change_id"]))
        assert receipt is not None
        receipt.processed_at = utcnow() - timedelta(days=200)
        db.commit()
    promote_to_superuser(user)
    pruned = api.post(
        f"/admin/projects/{project_id}/maintenance/prune?days=1", headers=user.headers
    )
    assert pruned.status_code == 200
    assert pruned.json()["sync_receipts_deleted"] == 0
    assert len(replayed(push(api, project_id, user, change).json())) == 1
