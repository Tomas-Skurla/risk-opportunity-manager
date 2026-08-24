"""Behavioral tests for the offline synchronization coordinator."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from riskapp_client.domain.domain_models import Project
from riskapp_client.services.synchronization_service import SyncService


def _service(*, remote=None):
    store = Mock()
    outbox = Mock()
    return SyncService(store, outbox, remote), store, outbox


def test_sync_service_delegates_counts_and_requires_a_remote() -> None:
    service, _store, outbox = _service()
    outbox.pending_count.return_value = 3
    outbox.blocked_count.return_value = 2
    outbox.get_blocked_changes.return_value = [{"change_id": "blocked-1"}]

    assert service.can_sync() is False
    assert service.pending_count("project-1") == 3
    assert service.blocked_count() == 2
    assert service.blocked_details("project-1") == [{"change_id": "blocked-1"}]
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

    processed, conflicts, errors = service._process_push(
        "project-1", changes, block_conflicts=True
    )

    assert processed == 2
    assert conflicts[0]["change_id"] == "conflict-1"
    assert errors[0]["change_id"] == "error-1"
    assert set(outbox.delete_outbox_ids.call_args.args[0]) == {
        "ok-1",
        "duplicate-1",
    }
    assert outbox.block_outbox_id.call_count == 2
    assert outbox.block_outbox_id.call_args_list[0].args[0] == "conflict-1"
    assert outbox.block_outbox_id.call_args_list[1].args[0] == "error-1"


def test_process_push_leaves_conflicts_pending_for_requeue() -> None:
    remote = Mock()
    remote.sync_push.return_value = {
        "conflicts": [{"change_id": "conflict-1"}],
        "errors": [],
    }
    service, _store, outbox = _service(remote=remote)

    processed, _conflicts, _errors = service._process_push(
        "project-1",
        [{"change_id": "conflict-1"}],
        block_conflicts=False,
    )

    assert processed == 0
    outbox.delete_outbox_ids.assert_not_called()
    outbox.block_outbox_id.assert_not_called()


def test_requeue_conflicts_handles_unusable_and_retryable_records() -> None:
    service, _store, outbox = _service(remote=Mock())
    outbox.requeue_conflict_with_new_id.side_effect = ["retry-1", None]
    conflicts = [
        {},
        {"change_id": "blocked-1"},
        {"change_id": "old-1", "server_version": 7},
        {"change_id": "old-2", "server_version": 8},
    ]

    assert service._requeue_conflicts(conflicts) == ["retry-1"]
    assert outbox.block_outbox_id.call_args.args[0] == "blocked-1"
    assert outbox.requeue_conflict_with_new_id.call_args_list == [
        call("old-1", 7),
        call("old-2", 8),
    ]


def test_sync_project_retries_conflict_then_applies_pull_in_parent_order() -> None:
    remote = Mock()
    remote.sync_push.side_effect = [
        {
            "conflicts": [{"change_id": "old-2", "server_version": 4}],
            "errors": [{"change_id": "bad-1", "reason": "invalid"}],
        },
        {"conflicts": [], "errors": []},
    ]
    remote.sync_pull.return_value = {
        "server_time": "2026-08-10T08:00:00Z",
        "risks": [{"id": "risk-1"}],
        "opportunities": [{"id": "opportunity-1"}],
        "actions": [{"id": "action-1"}],
        "assessments": [{"id": "assessment-1"}],
        "helpdesk_tickets": [{"id": "ticket-1"}],
    }
    service, store, outbox = _service(remote=remote)
    outbox.get_pending_changes.side_effect = [
        [
            {"change_id": "ok-1"},
            {"change_id": "old-2"},
            {"change_id": "bad-1"},
        ],
        [{"change_id": "retry-2"}, {"change_id": "unrelated"}],
    ]
    outbox.requeue_conflict_with_new_id.return_value = "retry-2"
    outbox.get_blocked_changes.return_value = [{"change_id": "bad-1"}]
    store.get_last_server_time.return_value = "2026-08-09T08:00:00Z"

    summary = service.sync_project("project-1")

    assert summary == {
        "pushed": 2,
        "conflicts": 1,
        "errors": 1,
        "blocked": 1,
        "blocked_details": [{"change_id": "bad-1"}],
        "pulled_risks": 1,
        "pulled_opportunities": 1,
        "pulled_actions": 1,
        "pulled_assessments": 1,
        "pulled_helpdesk_tickets": 1,
    }
    assert remote.sync_push.call_args_list[1].args == (
        "project-1",
        [{"change_id": "retry-2"}],
    )
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
            "server_time": "first",
            "risks": [{"id": "risk-1"}],
            "has_more": {"risks": True},
            "cursors": {"risks": "cursor-1"},
        },
        {
            "server_time": "second",
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
    )
    assert remote.sync_pull.call_args_list[2] == call(
        "project-1",
        "since",
        limit_per_entity=2000,
        cursors={"risks": "cursor-1"},
    )

    remote.sync_pull.side_effect = PullError(500)
    with pytest.raises(PullError, match="status 500"):
        service.sync_project("project-1")


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
    store.conn.commit.assert_called_once()
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
