"""Outbox recovery and malformed-payload boundaries."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest


def test_outbox_recovery_helpers_handle_invalid_and_missing_inputs(tmp_path) -> None:
    from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore
    from riskapp_client.adapters.local_storage.sync_outbox_queue import OutboxStore

    with LocalStore(str(tmp_path / "outbox-edges.db")) as store:
        project = store.create_local_project(name="Offline", project_id="project-1")
        store.upsert_local_risk(
            risk_id="risk-1",
            project_id=project.id,
            title="Queued risk",
            probability=2,
            impact=3,
            version=3,
        )
        outbox = OutboxStore(store)
        outbox.queue_risk_upsert(
            project.id,
            {"id": "risk-1", "title": "Queued risk", "probability": 2, "impact": 3},
        )
        change_id = outbox.get_pending_changes(project.id)[0]["change_id"]

        assert outbox.pending_count() == 1
        assert outbox.blocked_count() == 0
        assert outbox._safe_json_loads(None) == {}
        assert outbox._safe_json_loads("not-json") == {"detail": "not-json"}
        assert outbox._safe_json_loads('["server", "busy"]') == {
            "detail": "['server', 'busy']"
        }

        outbox.override_base_version(
            project.id, entity="risk", entity_id="risk-1", base_version=None
        )
        outbox.override_base_version(
            project.id,
            entity="risk",
            entity_id="risk-1",
            base_version="invalid",  # type: ignore[arg-type]
        )
        outbox.override_base_version(
            project.id, entity="risk", entity_id="risk-1", base_version=0
        )
        assert outbox.get_pending_changes(project.id)[0]["base_version"] is None
        outbox.override_base_version(
            project.id, entity="risk", entity_id="risk-1", base_version=8
        )
        assert outbox.get_pending_changes(project.id)[0]["base_version"] == 8

        outbox.block_outbox_id(change_id, "unstructured server error")
        assert outbox.blocked_count() == 1
        assert outbox.conflict_count() == 0
        assert outbox.error_count() == 1
        blocked = outbox.get_blocked_changes(limit=0)
        assert len(blocked) == 1
        assert blocked[0]["title"] == "Queued risk"
        assert blocked[0]["reason"] == "unstructured server error"

        with pytest.raises(ValueError, match="Unknown outbox failure kind"):
            outbox.block_outbox_id(change_id, "bad", failure_kind="unknown")

        assert outbox.requeue_conflict_with_new_id("missing", server_version=4) is None
        outbox.delete_outbox_ids([])
        outbox.delete_outbox_ids([change_id])
        assert outbox.blocked_count(project.id) == 0


def test_all_delete_queue_entry_points_preserve_local_versions(tmp_path) -> None:
    from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore
    from riskapp_client.adapters.local_storage.sync_outbox_queue import OutboxStore

    with LocalStore(str(tmp_path / "outbox-deletes.db")) as store:
        project = store.create_local_project(name="Offline", project_id="project-1")
        store.upsert_local_risk(
            risk_id="risk-1",
            project_id=project.id,
            title="Risk",
            probability=2,
            impact=3,
            version=2,
        )
        store.upsert_local_opportunity(
            opportunity_id="opportunity-1",
            project_id=project.id,
            title="Opportunity",
            probability=4,
            impact=2,
            version=5,
        )
        ticket = store.create_helpdesk_ticket(project.id, title="Ticket")
        store.conn.execute(
            "UPDATE helpdesk_tickets SET version=7 WHERE id=?", (ticket.id,)
        )
        store.conn.commit()

        outbox = OutboxStore(store)
        outbox.queue_risk_delete(project.id, "risk-1")
        outbox.queue_opportunity_upsert(
            project.id,
            {
                "id": "opportunity-1",
                "title": "Opportunity",
                "probability": 4,
                "impact": 2,
            },
        )
        outbox.queue_opportunity_delete(project.id, "opportunity-1")
        outbox.queue_helpdesk_delete(ticket.id, project.id)

        changes = outbox.get_pending_changes(project.id, limit=5000)
        by_entity = {change["entity"]: change for change in changes}
        assert by_entity["risk"]["base_version"] == 2
        assert by_entity["opportunity"]["op"] == "delete"
        assert by_entity["opportunity"]["base_version"] == 5
        assert by_entity["helpdesk_ticket"]["base_version"] == 7


def test_transient_retry_backoff_is_persistent_and_filters_until_due(tmp_path) -> None:
    from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore
    from riskapp_client.adapters.local_storage.sync_outbox_queue import OutboxStore

    with LocalStore(str(tmp_path / "outbox-retry.db")) as store:
        project = store.create_local_project(name="Offline", project_id="project-1")
        store.upsert_local_risk(
            risk_id="risk-1",
            project_id=project.id,
            title="Queued risk",
            probability=2,
            impact=3,
            version=1,
        )
        outbox = OutboxStore(store)
        outbox.queue_risk_upsert(
            project.id,
            {"id": "risk-1", "title": "Queued risk", "probability": 2, "impact": 3},
        )
        change_id = outbox.get_pending_changes(project.id)[0]["change_id"]
        start = datetime(2026, 9, 4, 12, 0, 0, tzinfo=UTC)

        first_retry = outbox.defer_outbox_id(
            change_id,
            {
                "reason": "push_request_failed",
                "failure_kind": "transient",
                "retryable": True,
            },
            now=start,
        )

        assert first_retry == "2026-09-04T12:00:02"
        assert outbox.pending_count(project.id) == 1
        assert outbox.deferred_count(project.id) == 1
        assert outbox.next_retry_at(project.id) == first_retry
        assert outbox.get_pending_changes(
            project.id, now="2026-09-04T12:00:01"
        ) == []
        assert outbox.get_pending_changes(
            project.id, now="2026-09-04T12:00:02"
        )[0]["change_id"] == change_id

        second_retry = outbox.defer_outbox_id(
            change_id,
            "server busy",
            now=datetime(2026, 9, 4, 12, 0, 2, tzinfo=UTC),
        )
        assert second_retry == "2026-09-04T12:00:07"
        row = store.conn.execute(
            "SELECT status, retry_count, failure_kind FROM outbox WHERE change_id=?;",
            (change_id,),
        ).fetchone()
        assert tuple(row) == ("retry", 2, "transient")


def test_authentication_block_is_released_for_a_new_online_session(tmp_path) -> None:
    from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore
    from riskapp_client.adapters.local_storage.sync_outbox_queue import OutboxStore

    with LocalStore(str(tmp_path / "outbox-auth.db")) as store:
        project = store.create_local_project(name="Offline", project_id="project-1")
        store.upsert_local_risk(
            risk_id="risk-1",
            project_id=project.id,
            title="Queued risk",
            probability=2,
            impact=3,
            version=1,
        )
        outbox = OutboxStore(store)
        outbox.queue_risk_upsert(
            project.id,
            {"id": "risk-1", "title": "Queued risk", "probability": 2, "impact": 3},
        )
        change_id = outbox.get_pending_changes(project.id)[0]["change_id"]
        outbox.block_outbox_id(
            change_id,
            {"reason": "push_request_failed", "http_status": 401},
            failure_kind="authentication",
        )

        assert outbox.blocked_count(project.id) == 1
        assert outbox.release_authentication_blocks(project.id) == 1
        assert outbox.blocked_count(project.id) == 0
        assert outbox.get_pending_changes(project.id)[0]["change_id"] == change_id


@pytest.mark.parametrize("outbox_state", ["retry", "blocked"])
def test_pull_does_not_overwrite_an_unresolved_local_change(
    tmp_path, outbox_state: str
) -> None:
    from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore
    from riskapp_client.adapters.local_storage.sync_outbox_queue import OutboxStore

    with LocalStore(str(tmp_path / f"pull-{outbox_state}.db")) as store:
        project = store.create_local_project(name="Offline", project_id="project-1")
        store.upsert_local_risk(
            risk_id="risk-1",
            project_id=project.id,
            title="Unsynced local title",
            probability=5,
            impact=4,
            version=2,
        )
        outbox = OutboxStore(store)
        outbox.queue_risk_upsert(
            project.id,
            {
                "id": "risk-1",
                "title": "Unsynced local title",
                "probability": 5,
                "impact": 4,
            },
        )
        change_id = outbox.get_pending_changes(project.id)[0]["change_id"]
        if outbox_state == "retry":
            outbox.defer_outbox_id(change_id, "network unavailable")
        else:
            outbox.block_outbox_id(
                change_id,
                {"reason": "version_mismatch", "server_version": 7},
                failure_kind="conflict",
            )

        store.apply_pull_risks(
            project.id,
            [
                {
                    "id": "risk-1",
                    "project_id": project.id,
                    "title": "Server title",
                    "probability": 1,
                    "impact": 1,
                    "version": 7,
                    "updated_at": "2026-09-04T12:00:00",
                }
            ],
        )

        row = store.get_risk_row("risk-1")
        assert row["title"] == "Unsynced local title"
        assert row["probability"] == 5
        assert row["version"] == 7
