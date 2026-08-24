"""Help-desk ticket write operations for offline-first mode."""

from __future__ import annotations

from typing import Any

from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore
from riskapp_client.adapters.local_storage.sync_outbox_queue import OutboxStore
from riskapp_client.domain.domain_models import HelpDeskTicket


class HelpDeskService:
    """Create / update / delete help-desk tickets locally and queue sync."""

    def __init__(self, store: LocalStore, outbox: OutboxStore) -> None:
        self._store = store
        self._outbox = outbox

    def list(self, project_id: str) -> list[HelpDeskTicket]:
        return self._store.list_helpdesk_tickets(project_id)

    def create(
        self,
        project_id: str,
        *,
        title: str,
        description: str = "",
        category: str = "other",
        priority: str = "medium",
        reporter_email: str = "",
    ) -> HelpDeskTicket:
        ticket = self._store.create_helpdesk_ticket(
            project_id,
            title=title,
            description=description,
            category=category,
            priority=priority,
            reporter_email=reporter_email,
        )
        self._outbox.queue_helpdesk_upsert(
            ticket.id, project_id, **self._ticket_fields(ticket)
        )
        return ticket

    def update(
        self,
        ticket_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        category: str | None = None,
        priority: str | None = None,
        status: str | None = None,
    ) -> HelpDeskTicket:
        ticket = self._store.update_helpdesk_ticket(
            ticket_id,
            title=title,
            description=description,
            category=category,
            priority=priority,
            status=status,
        )
        project_id = ticket.project_id
        self._outbox.queue_helpdesk_upsert(
            ticket.id, project_id, **self._ticket_fields(ticket)
        )
        return ticket

    def delete(self, ticket_id: str) -> None:
        project_id, version = self._store.get_helpdesk_ticket_project_and_version(
            ticket_id
        )

        # Ticket never reached the server: drop any queued local upsert/delete and
        # remove the row entirely so there is no stale tombstone in local storage.
        if int(version) < 1:
            self._store.delete_helpdesk_ticket(ticket_id)
            self._outbox.discard_entity_changes(
                project_id,
                entity="helpdesk_ticket",
                entity_id=ticket_id,
            )
            return

        self._store.soft_delete_helpdesk_ticket(ticket_id)
        self._outbox.queue_helpdesk_delete(ticket_id, project_id)

    # ---- private helpers ---------------------------------------------------

    @staticmethod
    def _ticket_fields(ticket: HelpDeskTicket) -> dict[str, Any]:
        return {
            "title": ticket.title,
            "description": ticket.description,
            "category": ticket.category,
            "priority": ticket.priority,
            "status": ticket.status,
            "reporter_email": ticket.reporter_email,
        }
