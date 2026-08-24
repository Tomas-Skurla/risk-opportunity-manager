"""Members tab."""

from __future__ import annotations

from PySide6.QtWidgets import QAbstractScrollArea, QHeaderView, QSizePolicy, QWidget

from riskapp_client.ui_v2.components.custom_gui_widgets import setup_readonly_table
from riskapp_client.ui_v2.tabs.ui_members_tab import Ui_Form as Ui_MembersTab


class MembersTab(QWidget):
    """Project members UI."""

    def __init__(
        self,
        *,
        on_add_or_update_member,
        on_remove_selected_member,
        on_refresh_members,
        on_member_selected,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.ui = Ui_MembersTab()
        self.ui.setupUi(self)
        setup_readonly_table(self.ui.members_table, excel_delegate=True)
        hh = self.ui.members_table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        self.ui.members_table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        self.ui.members_table.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        self.ui.verticalLayout.addStretch()
        tooltips = {
            0: "Member email",
            1: "Project role",
            2: "User ID",
            3: "Added",
        }
        for col, text in tooltips.items():
            if self.ui.members_table.horizontalHeaderItem(col):
                self.ui.members_table.horizontalHeaderItem(col).setToolTip(text)
        self.ui.members_table.itemSelectionChanged.connect(on_member_selected)
        self.ui.member_add_btn.clicked.connect(on_add_or_update_member)
        self.ui.member_remove_btn.clicked.connect(on_remove_selected_member)
        self.ui.member_refresh_btn.clicked.connect(on_refresh_members)
        self.members_hint = self.ui.members_hint
        self.member_email = self.ui.member_email
        self.member_role = self.ui.member_role
        self.member_add_btn = self.ui.member_add_btn
        self.member_remove_btn = self.ui.member_remove_btn
        self.member_refresh_btn = self.ui.member_refresh_btn
        self.members_table = self.ui.members_table
        self.member_email.setToolTip(
            "Email to add or update"
        )
        self.member_role.setToolTip(
            "Role to assign"
        )
        self.member_add_btn.setToolTip(
            "Add member or update role"
        )
        self.member_remove_btn.setToolTip("Remove selected member")
        self.member_refresh_btn.setToolTip("Reload members")
