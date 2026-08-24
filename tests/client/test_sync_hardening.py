"""Regression tests for malformed and retrying synchronization responses."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from riskapp_client.services.synchronization_service import SyncService


def _empty_pull() -> dict[str, object]:
    return {
        "server_time": "2026-08-11T12:00:00Z",
        "risks": [],
        "opportunities": [],
        "actions": [],
        "assessments": [],
        "helpdesk_tickets": [],
    }


def test_retry_errors_are_counted_and_blocked() -> None:
    store, outbox, remote = Mock(), Mock(), Mock()
    service = SyncService(store, outbox, remote)
    remote.sync_push.side_effect = [
        {
            "conflicts": [{"change_id": "old", "server_version": 4}],
            "errors": [],
        },
        {
            "conflicts": [],
            "errors": [{"change_id": "retry", "reason": "invalid"}],
        },
    ]
    remote.sync_pull.return_value = _empty_pull()
    outbox.get_pending_changes.side_effect = [
        [{"change_id": "old"}],
        [{"change_id": "retry"}],
    ]
    outbox.requeue_conflict_with_new_id.return_value = "retry"
    outbox.get_blocked_changes.return_value = [{"change_id": "retry"}]
    store.get_last_server_time.return_value = "since"

    summary = service.sync_project("project-1")

    assert summary["conflicts"] == 1
    assert summary["errors"] == 1
    assert summary["blocked"] == 1
    outbox.block_outbox_id.assert_called_once()


def test_malformed_conflict_version_is_blocked_instead_of_crashing() -> None:
    outbox = Mock()
    service = SyncService(Mock(), outbox, Mock())
    conflict = {"change_id": "bad-version", "server_version": "not-an-int"}

    assert service._requeue_conflicts([conflict]) == []
    outbox.block_outbox_id.assert_called_once()
    outbox.requeue_conflict_with_new_id.assert_not_called()


def test_paginated_pull_rejects_a_cursor_that_does_not_advance() -> None:
    remote = Mock()
    service = SyncService(Mock(), Mock(), remote)
    remote.sync_pull.side_effect = [
        {
            **_empty_pull(),
            "has_more": {"risks": True},
            "cursors": {"risks": "cursor-1"},
        },
        {
            **_empty_pull(),
            "has_more": {"risks": True},
            "cursors": {"risks": "cursor-1"},
        },
    ]

    with pytest.raises(RuntimeError, match="did not advance for: risks"):
        service._pull_paginated("project-1", "since")

    assert remote.sync_pull.call_count == 2


@pytest.mark.parametrize(
    "pagination",
    [
        {"has_more": ["risks"], "cursors": {"risks": "cursor-1"}},
        {"has_more": {"risks": True}, "cursors": ["cursor-1"]},
    ],
)
def test_paginated_pull_rejects_invalid_metadata(pagination) -> None:
    remote = Mock()
    service = SyncService(Mock(), Mock(), remote)
    remote.sync_pull.return_value = {**_empty_pull(), **pagination}

    with pytest.raises(RuntimeError, match="Invalid sync pagination metadata"):
        service._pull_paginated("project-1", "since")


def test_paginated_pull_rejects_missing_cursor_for_more_data() -> None:
    remote = Mock()
    service = SyncService(Mock(), Mock(), remote)
    remote.sync_pull.return_value = {
        **_empty_pull(),
        "has_more": {"risks": True},
        "cursors": {},
    }

    with pytest.raises(RuntimeError, match="did not advance for: risks"):
        service._pull_paginated("project-1", "since")
