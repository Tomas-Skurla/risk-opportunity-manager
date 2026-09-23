"""Members tab."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QAbstractScrollArea, QHeaderView, QSizePolicy, QWidget

from riskapp_client.ui_v2.components.custom_gui_widgets import setup_readonly_table
from riskapp_client.ui_v2.ui.ui_members_tab import Ui_Form as Ui_MembersTab


class MembersTab(QWidget):
    """Project members UI."""

    def __init__(
        self,
        *,
        on_add_or_update_member: Callable[[], None],
        on_remove_selected_member: Callable[[], None],
        on_refresh_members: Callable[[], None],
        on_member_selected: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.ui = Ui_MembersTab()
        self.ui.setupUi(self)
        setup_readonly_table(self.ui.members_table, excel_delegate=True)
        hh = self.ui.members_table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.ui.members_table.setSizeAdjustPolicy(
            QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents
        )
        self.ui.members_table.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum
        )
        self.ui.verticalLayout.addStretch()
        tooltips = {
            0: "Member email",
            1: "Project role",
            2: "User ID",
            3: "Added",
        }
        for col, text in tooltips.items():
            header_item = self.ui.members_table.horizontalHeaderItem(col)
            if header_item is not None:
                header_item.setToolTip(text)
        # PySide exposes bound signals dynamically to Pylint.
        # pylint: disable=no-member
        self.ui.members_table.itemSelectionChanged.connect(on_member_selected)
        self.ui.member_add_btn.clicked.connect(on_add_or_update_member)
        self.ui.member_remove_btn.clicked.connect(on_remove_selected_member)
        self.ui.member_refresh_btn.clicked.connect(on_refresh_members)
        # pylint: enable=no-member
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
