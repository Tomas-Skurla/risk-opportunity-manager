"""Top history / snapshots tab widget."""

from __future__ import annotations

from PySide6.QtCore import QDateTime, Qt, QTimer
from PySide6.QtWidgets import QAbstractScrollArea, QHeaderView, QSizePolicy, QWidget

from riskapp_client.ui_v2.components.custom_gui_widgets import setup_readonly_table
from riskapp_client.ui_v2.tabs.ui_top_history_tab import Ui_Form as Ui_TopHistoryTab


class TopHistoryTab(QWidget):
    """Top history (snapshots) tab."""

    def __init__(
        self,
        *,
        on_snapshot_now,
        on_refresh_history,
        on_period_changed,
        on_maybe_auto_snapshot,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.ui = Ui_TopHistoryTab()
        self.ui.setupUi(self)
        setup_readonly_table(self.ui.top_table)
        hh = self.ui.top_table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        self.ui.top_table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        self.ui.top_table.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        self.ui.verticalLayout_2.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.ui.splitter.setStretchFactor(0, 17)
        self.ui.splitter.setStretchFactor(1, 3)
        self.ui.splitter.setSizes([85000, 15000])
        tooltips = {
            0: "Captured: The date and time this snapshot was recorded",
            1: "Rank: The position of this item in the top list based on its score",
            2: "Title: The name or summary of the risk/opportunity",
            3: "P: The assessed Probability (1-5) at the time of the snapshot",
            4: "I: The assessed Impact (1-5) at the time of the snapshot",
            5: "Score: The calculated score (P × I) at the time of the snapshot",
        }
        for col, text in tooltips.items():
            if self.ui.top_table.horizontalHeaderItem(col):
                self.ui.top_table.horizontalHeaderItem(col).setToolTip(text)
        now = QDateTime.currentDateTime()
        self.ui.top_to.setDateTime(now)
        self.ui.top_from.setDateTime(now.addDays(-30))
        self.auto_snap_timer = QTimer(self)
        self.auto_snap_timer.setInterval(60 * 60 * 1000)
        self.auto_snap_timer.timeout.connect(on_maybe_auto_snapshot)
        self.auto_snap_timer.start()
        self.ui.snapshot_btn.clicked.connect(on_snapshot_now)
        self.ui.refresh_top_btn.clicked.connect(on_refresh_history)
        self.ui.top_period.currentTextChanged.connect(on_period_changed)
        self.snapshot_btn = self.ui.snapshot_btn
        self.auto_snapshot_chk = self.ui.auto_snapshot_chk
        self.auto_snapshot_kind = self.ui.auto_snapshot_kind
        self.auto_snapshot_days = self.ui.auto_snapshot_days
        self.top_kind = self.ui.top_kind
        self.top_limit = self.ui.top_limit
        self.top_period = self.ui.top_period
        self.top_from = self.ui.top_from
        self.top_to = self.ui.top_to
        self.refresh_top_btn = self.ui.refresh_top_btn
        self.top_report = self.ui.top_report
        self.top_table = self.ui.top_table
        self.ui.snapshot_btn.setToolTip(
            "Manually capture a snapshot of the current top items"
        )
        self.ui.auto_snapshot_chk.setToolTip("Enable automatic background snapshots")
        self.ui.auto_snapshot_kind.setToolTip(
            "Select whether to auto-snapshot risks, opportunities, or both"
        )
        self.ui.auto_snapshot_days.setToolTip(
            "Set how often (in days) automatic snapshots are taken"
        )
        self.ui.top_kind.setToolTip(
            "Filter history table to show risks, opportunities, or both"
        )
        self.ui.top_limit.setToolTip(
            "Limit the number of top items displayed per snapshot"
        )
        self.ui.top_period.setToolTip(
            "Quickly select a time period for the history view"
        )
        self.ui.top_from.setToolTip("Start date for filtering history")
        self.ui.top_to.setToolTip("End date for filtering history")
        self.ui.refresh_top_btn.setToolTip("Apply filters and reload the history table")
