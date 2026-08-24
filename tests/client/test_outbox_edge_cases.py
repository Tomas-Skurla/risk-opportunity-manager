"""Outbox recovery and malformed-payload boundaries."""

from __future__ import annotations


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
        blocked = outbox.get_blocked_changes(limit=0)
        assert len(blocked) == 1
        assert blocked[0]["title"] == "Queued risk"
        assert blocked[0]["reason"] == "unstructured server error"

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
