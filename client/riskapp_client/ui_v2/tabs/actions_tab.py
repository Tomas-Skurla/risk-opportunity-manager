"""Actions tab widget."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractScrollArea, QHeaderView, QSizePolicy, QWidget

from riskapp_client.ui_v2.components.custom_gui_widgets import setup_readonly_table
from riskapp_client.ui_v2.tabs.ui_actions_tab import Ui_Form as Ui_ActionsTab


class ActionsTab(QWidget):
    """Actions list + editor tab."""

    def __init__(
        self,
        *,
        on_action_clicked: Callable[[int, int], None],
        on_save_action: Callable[[], None],
        on_new_action: Callable[[], None],
        on_target_type_changed: Callable[[str], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.ui = Ui_ActionsTab()
        self.ui.setupUi(self)
        self.actions_table = self.ui.actions_table
        setup_readonly_table(self.actions_table)
        hh = self.actions_table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        self.actions_table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        self.actions_table.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        self.ui.verticalLayout_2.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.ui.splitter.setStretchFactor(0, 3)
        self.ui.splitter.setStretchFactor(1, 1)
        self.ui.splitter.setSizes([75000, 25000])
        tooltips = {
            0: "Title: The name or description of the action",
            1: "Kind: The type of action (e.g., mitigation, contingency)",
            2: "Status: The current progress of the action",
            3: "Target: The specific risk or opportunity this addresses",
            4: "Owner: The person responsible for this action",
        }
        for col, text in tooltips.items():
            if self.actions_table.horizontalHeaderItem(col):
                self.actions_table.horizontalHeaderItem(col).setToolTip(text)
        self.actions_table.cellClicked.connect(on_action_clicked)
        self.ui.action_target_type.addItems(["risk", "opportunity"])
        self.ui.action_kind.addItems(["mitigation", "contingency", "exploit"])
        self.ui.action_status.addItems(["open", "doing", "done"])
        self.ui.action_target_type.currentTextChanged.connect(on_target_type_changed)
        self.ui.action_save_btn.clicked.connect(on_save_action)
        self.ui.action_new_btn.clicked.connect(on_new_action)
        self.action_editor_label = self.ui.action_editor_label
        self.action_target_type = self.ui.action_target_type
        self.action_risk_combo = self.ui.action_risk_combo
        self.action_opp_combo = self.ui.action_opp_combo
        self.action_kind = self.ui.action_kind
        self.action_status = self.ui.action_status
        self.action_title = self.ui.action_title
        self.action_desc = self.ui.action_desc
        self.action_owner = self.ui.action_owner
        self.action_save_btn = self.ui.action_save_btn
        self.action_new_btn = self.ui.action_new_btn
        self.ui.action_target_type.setToolTip(
            "Select whether this action addresses a Risk or an Opportunity"
        )
        self.ui.action_risk_combo.setToolTip(
            "Select the specific Risk this action addresses"
        )
        self.ui.action_opp_combo.setToolTip(
            "Select the specific Opportunity this action addresses"
        )
        self.ui.action_kind.setToolTip(
            "Mitigation (reduce risk), Contingency (fallback plan), or Exploit (maximize opportunity)"
        )
        self.ui.action_status.setToolTip(
            "Track the current execution status of this action"
        )
        self.ui.action_title.setToolTip("A short, clear name for this action")
        self.ui.action_desc.setToolTip(
            "Detailed steps or explanation of the action plan"
        )
        self.ui.action_owner.setToolTip(
            "The team member responsible for executing this action"
        )
        self.ui.action_save_btn.setToolTip("Save the current action")
        self.ui.action_new_btn.setToolTip("Clear the form to create a new action")
