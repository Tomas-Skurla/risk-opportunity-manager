"""Help Desk tab widget."""

from __future__ import annotations

from PySide6.QtWidgets import QHeaderView, QWidget

from riskapp_client.domain.domain_models import (
    TICKET_CATEGORIES,
    TICKET_PRIORITIES,
    TICKET_STATUSES,
)
from riskapp_client.ui_v2.components.custom_gui_widgets import setup_readonly_table
from riskapp_client.ui_v2.tabs.ui_helpdesk_tab import Ui_HelpDeskTab


class HelpDeskTab(QWidget):
    """Project help-desk / support-ticket UI."""

    def __init__(
        self,
        *,
        on_ticket_clicked,
        on_new_ticket,
        on_save_ticket,
        on_delete_ticket,
        on_refresh,
        on_filter_changed,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.ui = Ui_HelpDeskTab()
        self.ui.setupUi(self)

        # --- Table setup ---
        setup_readonly_table(self.ui.tickets_table, excel_delegate=False)
        hh = self.ui.tickets_table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Stretch)
        # Hide the internal ID column.
        self.ui.tickets_table.setColumnHidden(6, True)

        # --- Populate combo boxes ---
        self.ui.filter_status.addItem("(all)")
        self.ui.filter_status.addItems(TICKET_STATUSES)
        self.ui.filter_priority.addItem("(all)")
        self.ui.filter_priority.addItems(TICKET_PRIORITIES)

        self.ui.ticket_category.addItems(TICKET_CATEGORIES)
        self.ui.ticket_priority.addItems(TICKET_PRIORITIES)
        # Default priority to "medium".
        idx = self.ui.ticket_priority.findText("medium")
        if idx >= 0:
            self.ui.ticket_priority.setCurrentIndex(idx)
        self.ui.ticket_status.addItems(TICKET_STATUSES)

        # --- Expose widgets as top-level attributes for the mixin ---
        self.tickets_table = self.ui.tickets_table
        self.ticket_title = self.ui.ticket_title
        self.ticket_category = self.ui.ticket_category
        self.ticket_priority = self.ui.ticket_priority
        self.ticket_status = self.ui.ticket_status
        self.ticket_description = self.ui.ticket_description
        self.new_btn = self.ui.new_btn
        self.save_btn = self.ui.save_btn
        self.delete_btn = self.ui.delete_btn
        self.refresh_btn = self.ui.refresh_btn
        self.filter_status = self.ui.filter_status
        self.filter_priority = self.ui.filter_priority

        # --- Tooltips ---
        self.ticket_title.setToolTip("A short summary of the issue or request")
        self.ticket_description.setToolTip("Detailed description of the issue")
        self.ticket_category.setToolTip("Type of ticket: bug, question, feature request, access, or other")
        self.ticket_priority.setToolTip("Urgency: low, medium, high, or critical")
        self.ticket_status.setToolTip("Current status: open, in_progress, resolved, or closed")
        self.new_btn.setToolTip("Clear the form and start a new ticket")
        self.save_btn.setToolTip("Save the current ticket (create or update)")
        self.delete_btn.setToolTip("Permanently delete the selected ticket")
        self.refresh_btn.setToolTip("Reload the ticket list")

        # --- Wire signals ---
        self.ui.tickets_table.itemSelectionChanged.connect(on_ticket_clicked)
        self.ui.new_btn.clicked.connect(on_new_ticket)
        self.ui.save_btn.clicked.connect(on_save_ticket)
        self.ui.delete_btn.clicked.connect(on_delete_ticket)
        self.ui.refresh_btn.clicked.connect(on_refresh)
        self.ui.filter_status.currentTextChanged.connect(lambda _: on_filter_changed())
        self.ui.filter_priority.currentTextChanged.connect(lambda _: on_filter_changed())
