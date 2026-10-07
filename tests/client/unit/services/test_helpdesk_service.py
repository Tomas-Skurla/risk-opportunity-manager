"""Help Desk deletion must preserve intent after a create was sent."""

import pytest
from riskapp_client.adapters.local_storage.sync_outbox_queue import OutboxStore
from riskapp_client.services.helpdesk_service import HelpDeskService


@pytest.mark.parametrize("create_state", ["pending", "retry", "blocked", "edited"])
def test_delete_attempted_create_stays_deleted_when_server_record_is_pulled(
    local_store, create_state: str
) -> None:
    project = local_store.create_local_project(name="Project", project_id="project-1")
    outbox = OutboxStore(local_store)
    service = HelpDeskService(local_store, outbox)
    ticket = service.create(project.id, title="Possibly on the server")
    create = outbox.get_pending_changes(project.id)[0]
    outbox.mark_outbox_ids_attempted([create["change_id"]])
    if create_state == "retry":
        outbox.defer_outbox_id(create["change_id"], {"reason": "push_request_failed"})
    elif create_state == "blocked":
        outbox.block_outbox_id(
            create["change_id"],
            {"reason": "base_version_required", "server_version": 1},
            failure_kind="conflict",
        )
    elif create_state == "edited":
        service.update(ticket.id, title="Edited after the lost response")

    service.delete(ticket.id)
    local_store.apply_pull_helpdesk_tickets(
        project.id,
        [
            {
                "id": ticket.id,
                "project_id": project.id,
                "title": ticket.title,
                "version": 1,
                "is_deleted": False,
            }
        ],
    )

    assert service.list(project.id) == []
    pending = outbox.get_pending_changes(project.id)
    assert len(pending) == 1
    assert pending[0]["entity"] == "helpdesk_ticket"
    assert pending[0]["op"] == "delete"
    assert pending[0]["record"] == {"id": ticket.id}
    assert pending[0]["base_version"] == 1
    assert outbox.blocked_count(project.id) == 0
