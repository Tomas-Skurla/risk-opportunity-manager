"""Behavioral tests for the offline synchronization coordinator."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from riskapp_client.domain.domain_models import Project
from riskapp_client.services.synchronization_service import SyncService


def _service(*, remote=None):
    store = Mock()
    store.write_transaction.side_effect = nullcontext
    outbox = Mock()
    outbox.next_retry_at.return_value = None
    return SyncService(store, outbox, remote), store, outbox


def test_sync_service_delegates_counts_and_requires_a_remote() -> None:
    service, _store, outbox = _service()
    outbox.pending_count.return_value = 3
    outbox.blocked_count.return_value = 2
    outbox.conflict_count.return_value = 1
    outbox.error_count.return_value = 1
    outbox.deferred_count.return_value = 4
    outbox.get_blocked_changes.return_value = [{"change_id": "blocked-1"}]
    _store.get_last_server_time.return_value = "2026-08-10T08:00:00Z"

    assert service.can_sync() is False
    assert service.pending_count("project-1") == 3
    assert service.blocked_count() == 2
    assert service.conflict_count("project-1") == 1
    assert service.error_count("project-1") == 1
    assert service.deferred_count("project-1") == 4
    assert service.next_retry_at("project-1") is None
    assert service.last_sync_time("project-1") == "2026-08-10T08:00:00Z"
    assert service.last_sync_time(None) is None
    assert service.blocked_details("project-1") == [{"change_id": "blocked-1"}]
    outbox.get_blocked_changes.return_value = [
        {"change_id": "conflict-1", "failure_kind": "conflict"},
        {"change_id": "error-1", "failure_kind": "validation"},
    ]
    assert service.conflict_details("project-1") == [
        {"change_id": "conflict-1", "failure_kind": "conflict"}
    ]
    outbox.pending_count.assert_called_once_with("project-1")
    outbox.blocked_count.assert_called_once_with(None)

    with pytest.raises(RuntimeError, match="No server configured"):
        service._push_once("project-1", [])
    with pytest.raises(RuntimeError, match="No server configured"):
        service.sync_project("project-1")


def test_process_push_removes_successes_and_blocks_failures() -> None:
    remote = Mock()
    remote.sync_push.return_value = {
        "conflicts": [{"change_id": "conflict-1", "reason": "stale"}],
        "errors": [{"change_id": "error-1", "reason": "invalid"}],
        "duplicate_change_ids": ["duplicate-1", ""],
    }
    service, _store, outbox = _service(remote=remote)
    changes = [
        {"change_id": "ok-1"},
        {"change_id": "conflict-1"},
        {"change_id": "error-1"},
        {},
    ]

    processed, conflicts, errors = service._process_push("project-1", changes)

    assert processed == 2
    assert conflicts[0]["change_id"] == "conflict-1"
    assert errors[0]["change_id"] == "error-1"
    assert set(outbox.delete_outbox_ids.call_args.args[0]) == {
        "ok-1",
        "duplicate-1",
    }
    assert outbox.block_outbox_id.call_count == 2
    assert outbox.block_outbox_id.call_args_list[0].args[0] == "conflict-1"
    assert outbox.block_outbox_id.call_args_list[0].args[1] == {
        "change_id": "conflict-1",
        "reason": "stale",
    }
    assert outbox.block_outbox_id.call_args_list[0].kwargs == {
        "failure_kind": "conflict"
    }
    assert outbox.block_outbox_id.call_args_list[1].args[0] == "error-1"
    assert outbox.block_outbox_id.call_args_list[1].kwargs == {
        "failure_kind": "validation"
    }


@pytest.mark.parametrize(
    ("status", "failure_kind", "retryable"),
    [
        (0, "transient", True),
        (408, "transient", True),
        (429, "transient", True),
        (503, "transient", True),
        (401, "authentication", False),
        (403, "permission", False),
        (422, "validation", False),
    ],
)
def test_push_request_failures_follow_retry_state_machine(
    status: int, failure_kind: str, retryable: bool
) -> None:
    class RequestError(RuntimeError):
        def __init__(self, code: int) -> None:
            super().__init__(f"status {code}")
            self.status = code
            self.detail = "request failed"

    remote = Mock()
    remote.sync_push.side_effect = RequestError(status)
    service, _store, outbox = _service(remote=remote)

    processed, conflicts, errors = service._process_push(
        "project-1", [{"change_id": "change-1"}]
    )

    assert processed == 0
    assert conflicts == []
    assert errors[0]["failure_kind"] == failure_kind
    assert errors[0]["retryable"] is retryable
    assert errors[0]["request_failed"] is True
    if retryable:
        outbox.defer_outbox_id.assert_called_once_with("change-1", errors[0])
        outbox.block_outbox_id.assert_not_called()
    else:
        outbox.block_outbox_id.assert_called_once_with(
            "change-1", errors[0], failure_kind=failure_kind
        )
        outbox.defer_outbox_id.assert_not_called()


def test_retryable_per_change_result_is_deferred_not_blocked() -> None:
    remote = Mock()
    remote.sync_push.return_value = {
        "results": [
            {
                "change_id": "change-1",
                "status": "error",
                "reason": "internal_error",
                "failure_kind": "transient",
                "retryable": True,
            }
        ]
    }
    service, _store, outbox = _service(remote=remote)

    processed, conflicts, errors = service._process_push(
        "project-1", [{"change_id": "change-1"}]
    )

    assert processed == 0
    assert conflicts == []
    outbox.defer_outbox_id.assert_called_once_with("change-1", errors[0])
    outbox.block_outbox_id.assert_not_called()


def test_request_level_push_failure_stops_pull_and_returns_retry_state() -> None:
    class OfflineError(RuntimeError):
        status = 0
        detail = "network unavailable"

    remote = Mock()
    remote.sync_push.side_effect = OfflineError()
    service, store, outbox = _service(remote=remote)
    outbox.get_pending_changes.return_value = [{"change_id": "change-1"}]
    outbox.get_blocked_changes.return_value = []
    outbox.next_retry_at.return_value = "2026-09-04T12:00:02"

    summary = service.sync_project("project-1")

    assert summary["state"] == "retry_wait"
    assert summary["deferred"] == 1
    assert summary["errors"] == 0
    assert summary["next_retry_at"] == "2026-09-04T12:00:02"
    remote.sync_pull.assert_not_called()
    store.set_last_server_time.assert_not_called()


def test_last_sync_time_hides_uninitialized_watermark() -> None:
    service, store, _outbox = _service(remote=Mock())
    store.get_last_server_time.return_value = "1970-01-01T00:00:00"

    assert service.last_sync_time("project-1") is None


def test_process_push_blocks_conflicts_for_explicit_resolution() -> None:
    remote = Mock()
    remote.sync_push.return_value = {
        "conflicts": [{"change_id": "conflict-1"}],
        "errors": [],
    }
    service, _store, outbox = _service(remote=remote)

    processed, _conflicts, _errors = service._process_push(
        "project-1", [{"change_id": "conflict-1"}]
    )

    assert processed == 0
    outbox.delete_outbox_ids.assert_not_called()
    outbox.block_outbox_id.assert_called_once()
    assert outbox.block_outbox_id.call_args.args[0] == "conflict-1"


def test_process_push_uses_replayed_receipt_status_not_duplicate_flag() -> None:
    remote = Mock()
    remote.sync_push.return_value = {
        "duplicates": 3,
        "duplicate_change_ids": ["accepted-1", "conflict-1", "error-1"],
        "results": [
            {
                "change_id": "accepted-1",
                "status": "accepted",
                "replayed": True,
            },
            {
                "change_id": "conflict-1",
                "status": "conflict",
                "replayed": True,
                "reason": "version_mismatch",
                "server_version": 4,
            },
            {
                "change_id": "error-1",
                "status": "error",
                "replayed": True,
                "reason": "http_error",
            },
        ],
    }
    service, _store, outbox = _service(remote=remote)

    processed, conflicts, errors = service._process_push(
        "project-1",
        [
            {"change_id": "accepted-1"},
            {"change_id": "conflict-1"},
            {"change_id": "error-1"},
        ],
    )

    assert processed == 1
    outbox.delete_outbox_ids.assert_called_once_with(["accepted-1"])
    assert conflicts[0]["change_id"] == "conflict-1"
    assert errors[0]["change_id"] == "error-1"
    assert outbox.block_outbox_id.call_count == 2


def test_sync_project_blocks_conflict_then_applies_pull_in_parent_order() -> None:
    remote = Mock()
    remote.sync_push.return_value = {
        "conflicts": [{"change_id": "old-2", "server_version": 4}],
        "errors": [{"change_id": "bad-1", "reason": "invalid"}],
    }
    remote.sync_pull.return_value = {
        "server_time": "2026-08-10T08:00:00Z",
        "risks": [{"id": "risk-1"}],
        "opportunities": [{"id": "opportunity-1"}],
        "actions": [{"id": "action-1"}],
        "assessments": [{"id": "assessment-1"}],
        "helpdesk_tickets": [{"id": "ticket-1"}],
    }
    service, store, outbox = _service(remote=remote)
    outbox.get_pending_changes.return_value = [
        {"change_id": "ok-1"},
        {"change_id": "old-2"},
        {"change_id": "bad-1"},
    ]
    outbox.get_blocked_changes.return_value = [
        {"change_id": "old-2"},
        {"change_id": "bad-1"},
    ]
    store.get_last_server_time.return_value = "2026-08-09T08:00:00Z"

    summary = service.sync_project("project-1")

    assert summary == {
        "state": "attention_required",
        "pushed": 1,
        "conflicts": 1,
        "errors": 1,
        "deferred": 0,
        "blocked": 2,
        "blocked_details": [
            {"change_id": "old-2"},
            {"change_id": "bad-1"},
        ],
        "pulled_risks": 1,
        "pulled_opportunities": 1,
        "pulled_actions": 1,
        "pulled_assessments": 1,
        "pulled_helpdesk_tickets": 1,
        "next_retry_at": None,
    }
    remote.sync_push.assert_called_once()
    outbox.requeue_conflict_with_new_id.assert_not_called()
    store.apply_pull_risks.assert_called_once()
    store.apply_pull_opportunities.assert_called_once()
    store.apply_pull_actions.assert_called_once()
    store.apply_pull_assessments.assert_called_once()
    store.apply_pull_helpdesk_tickets.assert_called_once()
    store.set_last_server_time.assert_called_once_with(
        "project-1", "2026-08-10T08:00:00Z"
    )


def test_sync_project_falls_back_to_paginated_pull_only_for_413() -> None:
    class PullError(RuntimeError):
        def __init__(self, status):
            super().__init__(f"status {status}")
            self.status = status

    remote = Mock()
    remote.sync_pull.side_effect = [
        PullError(413),
        {
            "server_time": "snapshot",
            "risks": [{"id": "risk-1"}],
            "has_more": {"risks": True},
            "cursors": {"risks": "cursor-1"},
        },
        {
            "server_time": "snapshot",
            "risks": [{"id": "risk-2"}],
            "opportunities": [{"id": "opportunity-1"}],
            "has_more": {"risks": False},
            "cursors": {},
        },
    ]
    service, store, outbox = _service(remote=remote)
    outbox.get_pending_changes.return_value = []
    outbox.get_blocked_changes.return_value = []
    store.get_last_server_time.return_value = "since"

    summary = service.sync_project("project-1")

    assert summary["pulled_risks"] == 2
    assert summary["pulled_opportunities"] == 1
    assert remote.sync_pull.call_args_list[1] == call(
        "project-1",
        "since",
        limit_per_entity=2000,
        cursors=None,
        snapshot_time=None,
    )
    assert remote.sync_pull.call_args_list[2] == call(
        "project-1",
        "since",
        limit_per_entity=2000,
        cursors={"risks": "cursor-1"},
        snapshot_time="snapshot",
    )

    remote.sync_pull.side_effect = PullError(500)
    failed = service.sync_project("project-1")
    assert failed["state"] == "retry_wait"
    assert failed["sync_error"]["failure_kind"] == "transient"
    assert failed["sync_error"]["retryable"] is True


def test_promote_local_project_renames_collision_and_migrates_cache() -> None:
    remote = Mock()
    remote.list_projects.return_value = [
        Project("p1", "Local Project"),
        Project("p2", "Local Project (2)"),
    ]
    remote.create_project.return_value = Project("server-1", "Local Project (3)")
    service, store, _outbox = _service(remote=remote)
    store.get_project.return_value = Project(
        "local-1", "Local Project", "Offline", "user-1"
    )

    promoted = service._promote_local_project("local-1")

    assert promoted == "server-1"
    remote.create_project.assert_called_once_with(
        name="Local Project (3)", description="Offline"
    )
    store.conn.execute.assert_called_once_with(
        "UPDATE projects SET name = ? WHERE id = ?;",
        ("Local Project (3)", "local-1"),
    )
    store.write_transaction.assert_called_once_with()
    store.migrate_project_id.assert_called_once_with(
        old_project_id="local-1", new_project_id="server-1"
    )
    store.upsert_projects.assert_called_once_with(
        [remote.create_project.return_value]
    )


def test_promote_local_project_rejects_anonymous_and_missing_capabilities() -> None:
    service, store, _outbox = _service(remote=Mock())
    store.get_project.return_value = None
    assert service._promote_local_project("local-missing") is None

    store.get_project.return_value = Project("local-anon", "Local", created_by="")
    with pytest.raises(RuntimeError, match="cannot be synced"):
        service._promote_local_project("local-anon")

    service._remote = SimpleNamespace()
    store.get_project.return_value = Project(
        "local-user", "Local", created_by="user-1"
    )
    assert service._promote_local_project("local-user") is None


def test_promote_local_project_handles_listing_failure_and_invalid_create() -> None:
    remote = Mock()
    remote.list_projects.side_effect = RuntimeError("offline")
    remote.create_project.return_value = None
    service, store, _outbox = _service(remote=remote)
    store.get_project.return_value = Project(
        "local-1", "", created_by="user-1"
    )

    assert service._promote_local_project("local-1") is None
    remote.create_project.assert_called_once_with(
        name="Local Project", description=""
    )
