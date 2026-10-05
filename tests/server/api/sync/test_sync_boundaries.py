"""Sync pagination, authorization, and defensive engine boundaries."""

from __future__ import annotations

import uuid

from support import (
    add_member,
    create_item,
    create_project,
    new_change,
    newly_accepted,
    push,
    register_user,
    replayed,
    results_with,
)


def test_sync_pull_rejects_malformed_requests(api) -> None:
    """Pulls are sequence-only, and malformed sequence requests are refused.

    Paginating within one sequence snapshot is covered in
    test_sync_monotonic_sequence.py.
    """
    user = register_user(api)
    project = create_project(api, user, name="Sync")
    project_id = project.id
    create_item(api, project, user, kind="risk", title="First")
    create_item(api, project, user, kind="risk", title="Second")
    url = f"/projects/{project_id}/sync/pull"

    first_page = api.post(
        url,
        json={"project_id": project_id, "since_sequence": 0, "limit_per_entity": 1},
        headers=user.headers,
    )
    assert first_page.status_code == 200, first_page.text
    page = first_page.json()
    assert page["has_more"]["risks"] is True
    snapshot_sequence = page["server_sequence"]

    def pull(body: dict):
        return api.post(
            url, json={"project_id": project_id, **body}, headers=user.headers
        )

    # The old timestamp-based request is no longer accepted.
    assert pull({"since": "2000-01-01T00:00:00"}).status_code == 422
    # Cursors only make sense inside a fixed snapshot.
    missing_snapshot = pull(
        {"since_sequence": 0, "limit_per_entity": 1, "cursors": page["cursors"]}
    )
    assert missing_snapshot.status_code == 422

    malformed_cursor = pull(
        {
            "since_sequence": 0,
            "limit_per_entity": 1,
            "cursors": {"risks": "not-a-cursor"},
            "snapshot_sequence": snapshot_sequence,
        }
    )

    assert malformed_cursor.status_code == 400
    assert malformed_cursor.json()["detail"] == "Invalid cursor"

    future_snapshot = pull({"since_sequence": 0, "snapshot_sequence": 10**6})
    assert future_snapshot.status_code == 400
    assert (
        future_snapshot.json()["detail"] == "snapshot_sequence is ahead of the server"
    )

    snapshot_before_since = pull(
        {"since_sequence": snapshot_sequence, "snapshot_sequence": 0}
    )
    assert snapshot_before_since.status_code == 400
    assert (
        snapshot_before_since.json()["detail"]
        == "snapshot_sequence precedes since_sequence"
    )

    another_project = str(uuid.uuid4())
    pull_mismatch = api.post(
        url,
        json={"project_id": another_project, "since_sequence": 0},
        headers=user.headers,
    )
    assert pull_mismatch.status_code == 400
    push_mismatch = api.post(
        f"/projects/{project_id}/sync/push",
        json={"project_id": another_project, "changes": []},
        headers=user.headers,
    )
    assert push_mismatch.status_code == 400


def test_sync_engine_records_invalid_changes_and_member_delete_denials(api) -> None:
    admin = register_user(api)
    member = register_user(api)
    project = create_project(api, admin, name="Sync")
    project_id = project.id
    add_member(api, project, member, "member")
    risk = create_item(api, project, admin, kind="risk", title="Protected")

    denied = push(
        api,
        project_id,
        member,
        new_change(
            "risk", {"id": risk.id, "status": "deleted"}, base_version=risk.version
        ),
        new_change("risk", {"id": risk.id}, op="delete", base_version=risk.version),
    )
    assert denied.status_code == 200, denied.text
    assert len(newly_accepted(denied.json())) == 0
    assert [error["reason"] for error in results_with(denied.json(), "error")] == [
        "insufficient_permissions",
        "insufficient_permissions",
    ]

    # These imports follow isolated_app_factory's module reloads.
    # pylint: disable=import-outside-toplevel
    import riskapp_server.db.session as session
    import riskapp_server.sync.engine as engine
    from riskapp_server.schemas.models import SyncChange
    from sqlalchemy.orm import Session

    # pylint: enable=import-outside-toplevel

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
            uuid.UUID(admin.id),
            uuid.UUID(project_id),
            changes,
        )

        empty = engine.push_changes(
            db,
            uuid.UUID(admin.id),
            uuid.UUID(project_id),
            [],
        )

    assert len(newly_accepted(result)) == 1
    assert [error["reason"] for error in results_with(result, "error")] == [
        "unknown_entity",
        "unknown_op",
        "http_error",
        "http_error",
    ]
    assert len(newly_accepted(empty)) == 0
    assert results_with(empty, "error") == []
    assert member.id != admin.id


def test_sync_soft_delete_transitions_require_manager(api) -> None:
    admin = register_user(api)
    member = register_user(api)
    project = create_project(api, admin, name="Protected")
    project_id = project.id
    add_member(api, project, member, "member")
    risk = create_item(api, project, admin, kind="risk", title="Protected risk")
    action_response = api.post(
        f"/projects/{project_id}/actions",
        json={
            "risk_id": risk.id,
            "kind": "mitigation",
            "title": "Protected action",
            "description": "",
            "status": "open",
        },
        headers=admin.headers,
    )
    assert action_response.status_code == 201, action_response.text
    action = action_response.json()

    action_delete = push(
        api,
        project_id,
        member,
        new_change(
            "action",
            {
                "id": action["id"],
                "is_deleted": True,
            },
            base_version=action["version"],
        ),
    )
    assert action_delete.status_code == 200, action_delete.text
    assert len(newly_accepted(action_delete.json())) == 0
    assert action_delete.json()["results"][0]["reason"] == ("insufficient_permissions")
    admin_delete = push(
        api,
        project_id,
        admin,
        new_change(
            "risk", {"id": risk.id, "is_deleted": True}, base_version=risk.version
        ),
    )
    assert admin_delete.status_code == 200, admin_delete.text
    deleted_result = admin_delete.json()["results"][0]
    assert deleted_result["status"] == "accepted"
    assert deleted_result["server_record"]["is_deleted"] is True

    member_undelete = push(
        api,
        project_id,
        member,
        new_change(
            "risk",
            {"id": risk.id, "is_deleted": False},
            base_version=deleted_result["server_version"],
        ),
    )
    assert member_undelete.status_code == 200, member_undelete.text
    assert len(newly_accepted(member_undelete.json())) == 0
    assert member_undelete.json()["results"][0]["reason"] == (
        "insufficient_permissions"
    )


def test_database_constraint_failure_is_permanent_and_receipted(api) -> None:
    user = register_user(api)
    project = create_project(api, user, name="Constraints")
    project_id = project.id
    risk = create_item(api, project, user, kind="risk", title="Assessed risk")

    def assessment_change(assessment_id: str) -> dict:
        return new_change(
            "assessment",
            {
                "id": assessment_id,
                "risk_id": risk.id,
                "probability": 2,
                "impact": 3,
                "notes": "Assessment",
            },
        )

    first = assessment_change(str(uuid.uuid4()))
    accepted = push(api, project_id, user, first)
    assert accepted.status_code == 200, accepted.text
    assert len(newly_accepted(accepted.json())) == 1

    duplicate = assessment_change(str(uuid.uuid4()))
    rejected = push(api, project_id, user, duplicate)
    assert rejected.status_code == 200, rejected.text
    result = rejected.json()["results"][0]
    assert result["status"] == "error"
    assert result["reason"] == "constraint_violation"
    assert result["failure_kind"] == "validation"
    assert result["retryable"] is False
    replay = push(api, project_id, user, duplicate)
    assert replay.status_code == 200, replay.text
    replayed_result = replay.json()["results"][0]
    assert len(replayed(replay.json())) == 1
    assert replayed_result["reason"] == "constraint_violation"
    assert replayed_result["replayed"] is True
