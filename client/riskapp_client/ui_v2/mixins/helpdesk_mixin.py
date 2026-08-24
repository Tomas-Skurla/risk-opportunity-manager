"""MainWindow mixin for Help Desk ticket management."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox
from riskapp_client.domain.domain_models import HelpDeskTicket


class HelpDeskMixin:
    """MainWindow mixin: HelpDeskMixin

    Manages help-desk tickets via the backend (offline-first with server sync).
    """

    # ---- public entry points (called from layout wiring) -------------------

    def _refresh_helpdesk(self) -> None:
        """Reload tickets from the backend and reapply filters."""
        pid = self.current_project_id
        if not pid:
            self.helpdesk_tab.tickets_table.setRowCount(0)
            self._all_tickets = []
            return
        self._all_tickets = self.backend.list_helpdesk_tickets(pid)
        self._apply_helpdesk_filters()

    def _apply_helpdesk_filters(self) -> None:
        """Filter the cached ticket list and repopulate the table."""
        status_filter = self.helpdesk_tab.filter_status.currentText()
        priority_filter = self.helpdesk_tab.filter_priority.currentText()

        filtered = self._all_tickets
        if status_filter and status_filter != "(all)":
            filtered = [t for t in filtered if t.status == status_filter]
        if priority_filter and priority_filter != "(all)":
            filtered = [t for t in filtered if t.priority == priority_filter]

        table = self.helpdesk_tab.tickets_table
        table.setRowCount(len(filtered))
        for row, ticket in enumerate(filtered):
            table.setItem(row, 0, self._mk_item(ticket.title, entity_id=ticket.id))
            table.setItem(row, 1, self._mk_item(ticket.category, align_center=True))
            table.setItem(row, 2, self._mk_item(ticket.priority, align_center=True))
            table.setItem(row, 3, self._mk_item(ticket.status, align_center=True))
            table.setItem(row, 4, self._mk_item(ticket.reporter_email))
            table.setItem(row, 5, self._mk_item(ticket.created_at[:16] if ticket.created_at else ""))
            table.setItem(row, 6, self._mk_item(ticket.id))

        if self._current_ticket_id:
            self._select_row_by_entity_id(
                self._current_ticket_id, table=table, id_col=0
            )

    def _on_helpdesk_ticket_clicked(self) -> None:
        table = self.helpdesk_tab.tickets_table
        row = table.currentRow()
        if row < 0:
            return
        item = table.item(row, 0)
        if not item:
            return
        ticket_id = item.data(Qt.UserRole)
        if not ticket_id:
            return
        self._current_ticket_id = str(ticket_id)
        ticket = self._find_ticket(ticket_id)
        if ticket:
            self._populate_helpdesk_editor(ticket)

    def _start_new_helpdesk_ticket(self) -> None:
        """Clear the editor for a new ticket."""
        self._current_ticket_id = None
        self.helpdesk_tab.ticket_title.clear()
        self.helpdesk_tab.ticket_description.clear()
        idx = self.helpdesk_tab.ticket_category.findText("other")
        if idx >= 0:
            self.helpdesk_tab.ticket_category.setCurrentIndex(idx)
        idx = self.helpdesk_tab.ticket_priority.findText("medium")
        if idx >= 0:
            self.helpdesk_tab.ticket_priority.setCurrentIndex(idx)
        idx = self.helpdesk_tab.ticket_status.findText("open")
        if idx >= 0:
            self.helpdesk_tab.ticket_status.setCurrentIndex(idx)
        self.helpdesk_tab.ticket_title.setFocus()

    def _save_helpdesk_ticket(self) -> None:
        """Create or update a ticket via the backend."""
        pid = self.current_project_id
        if not pid:
            QMessageBox.warning(self, "Help Desk", "Select a project first.")
            return
        title = self.helpdesk_tab.ticket_title.text().strip()
        if not title:
            QMessageBox.warning(self, "Validation", "Title is required.")
            return

        category = self.helpdesk_tab.ticket_category.currentText()
        priority = self.helpdesk_tab.ticket_priority.currentText()
        status = self.helpdesk_tab.ticket_status.currentText()
        description = self.helpdesk_tab.ticket_description.toPlainText().strip()

        try:
            if self._current_ticket_id:
                ticket = self.backend.update_helpdesk_ticket(
                    self._current_ticket_id,
                    title=title,
                    description=description,
                    category=category,
                    priority=priority,
                    status=status,
                )
            else:
                reporter = ""
                if hasattr(self.backend, "remote") and self.backend.remote:
                    reporter = getattr(self.backend.remote, "email", "") or ""
                ticket = self.backend.create_helpdesk_ticket(
                    pid,
                    title=title,
                    description=description,
                    category=category,
                    priority=priority,
                    reporter_email=reporter,
                )
                self._current_ticket_id = ticket.id
        except (RuntimeError, OSError, ValueError) as exc:
            QMessageBox.critical(self, "Help Desk", f"Save failed: {exc}")
            return

        self._refresh_helpdesk()

    def _delete_helpdesk_ticket(self) -> None:
        """Delete the currently selected ticket via the backend."""
        if not self._current_ticket_id:
            QMessageBox.information(self, "Help Desk", "No ticket selected.")
            return
        reply = QMessageBox.question(
            self,
            "Confirm delete",
            "Permanently delete this ticket?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            self.backend.delete_helpdesk_ticket(self._current_ticket_id)
        except (RuntimeError, OSError) as exc:
            QMessageBox.critical(self, "Help Desk", f"Delete failed: {exc}")
            return
        self._current_ticket_id = None
        self._start_new_helpdesk_ticket()
        self._refresh_helpdesk()

    # ---- private helpers ---------------------------------------------------

    def _find_ticket(self, ticket_id: str) -> HelpDeskTicket | None:
        """Look up a ticket by id in the cached list."""
        for t in self._all_tickets:
            if t.id == ticket_id:
                return t
        return None

    def _populate_helpdesk_editor(self, ticket: HelpDeskTicket) -> None:
        """Fill the editor form with a ticket's data."""
        self.helpdesk_tab.ticket_title.setText(ticket.title)
        self.helpdesk_tab.ticket_description.setPlainText(ticket.description)

        for combo, value in [
            (self.helpdesk_tab.ticket_category, ticket.category),
            (self.helpdesk_tab.ticket_priority, ticket.priority),
            (self.helpdesk_tab.ticket_status, ticket.status),
        ]:
            idx = combo.findText(value)
            if idx >= 0:
                combo.setCurrentIndex(idx)
