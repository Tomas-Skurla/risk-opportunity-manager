"""Risk/Opportunity matrix tab widget."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QFrame,
    QHeaderView,
    QSizePolicy,
    QTableWidget,
    QWidget,
)  # pylint: disable=no-name-in-module

from riskapp_client.ui_v2.components.custom_gui_widgets import (
    CrispHeader,
    setup_readonly_table,
)
from riskapp_client.ui_v2.tabs.ui_matrix_tab import Ui_Form as Ui_MatrixTab


class MatrixTab(QWidget):
    """Probability x Impact matrix view."""

    def __init__(self, *, on_kind_changed=None, parent=None) -> None:
        super().__init__(parent)
        self.ui = Ui_MatrixTab()
        self.ui.setupUi(self)
        if on_kind_changed:
            self.ui.kind_combo.currentTextChanged.connect(on_kind_changed)

        def style_matrix(table: QTableWidget) -> None:
            setup_readonly_table(table)
            table.setFrameShape(QFrame.Box)
            table.setFrameShadow(QFrame.Plain)
            table.setLineWidth(0)
            table.setHorizontalHeader(CrispHeader(Qt.Horizontal, table))
            hh, vh = table.horizontalHeader(), table.verticalHeader()
            hh.setSectionsClickable(False)
            hh.setHighlightSections(False)
            hh.setSectionResizeMode(QHeaderView.Fixed)
            hh.setDefaultSectionSize(70)
            vh.setVisible(True)
            vh.setSectionsClickable(False)
            vh.setHighlightSections(False)
            vh.setSectionResizeMode(QHeaderView.Fixed)
            vh.setDefaultSectionSize(50)
            vh.setDefaultAlignment(Qt.AlignCenter)
            table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
            table.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
            table.setCornerButtonEnabled(True)
            table.setShowGrid(True)

        style_matrix(self.ui.risks_matrix_table)
        style_matrix(self.ui.opps_matrix_table)
        self.kind_combo = self.ui.kind_combo
        self.risks_label = self.ui.risks_label
        self.risks_matrix_table = self.ui.risks_matrix_table
        self.opps_label = self.ui.opps_label
        self.opps_matrix_table = self.ui.opps_matrix_table
        self.set_kind(self.kind_combo.currentText())
        self.kind_combo.setToolTip(
            "Select which matrices to display: Risks, Opportunities, or Both"
        )
        self.risks_matrix_table.setToolTip(
            "Risk Matrix: Displays the count of risks mapped by Probability (rows) and Impact (columns)"
        )
        self.opps_matrix_table.setToolTip(
            "Opportunity Matrix: Displays the count of opportunities mapped by Probability (rows) and Impact (columns)"
        )

    def set_kind(self, text: str) -> None:
        kind = (text or "Risks").strip().lower()
        if kind == "opportunities":
            self.risks_label.hide()
            self.risks_matrix_table.hide()
            self.opps_label.show()
            self.opps_matrix_table.show()
        elif kind == "both":
            self.risks_label.show()
            self.risks_matrix_table.show()
            self.opps_label.show()
            self.opps_matrix_table.show()
        else:
            self.risks_label.show()
            self.risks_matrix_table.show()
            self.opps_label.hide()
            self.opps_matrix_table.hide()
