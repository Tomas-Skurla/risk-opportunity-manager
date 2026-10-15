"""Assessments tab widget."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QAbstractScrollArea, QHeaderView, QSizePolicy, QWidget

from riskapp_client.ui_v2.components.custom_gui_widgets import (
    set_header_tooltips,
    setup_readonly_table,
)
from riskapp_client.ui_v2.ui.ui_assessments_tab import Ui_Form as Ui_AssessmentsTab


class AssessmentsTab(QWidget):
    """Assessments view + 'my assessment' editor."""

    def __init__(
        self,
        *,
        on_save_assessment: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.ui = Ui_AssessmentsTab()
        self.ui.setupUi(self)
        self.assessments_table = self.ui.assessments_table
        setup_readonly_table(self.assessments_table)
        hh = self.ui.assessments_table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.ui.assessments_table.setSizeAdjustPolicy(
            QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents
        )
        self.ui.assessments_table.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum
        )
        self.ui.verticalLayout_2.addStretch()
        self.ui.verticalLayout_3.addStretch()
        self.ui.splitter.setStretchFactor(0, 3)
        self.ui.splitter.setStretchFactor(1, 1)
        self.ui.splitter.setSizes([75000, 25000])
        set_header_tooltips(
            self.assessments_table,
            [
                "Assessor: The team member who submitted this assessment",
                "P: The assessed Probability (1-5)",
                "I: The assessed Impact (1-5)",
                "Score: Calculated as Probability × Impact (1-25)",
                "Notes: Additional context provided by the assessor",
                "Updated: When this assessment was last modified",
            ],
        )
        # PySide exposes bound signals dynamically to Pylint.
        # pylint: disable-next=no-member
        self.ui.assess_save_btn.clicked.connect(on_save_assessment)
        self.target_label = self.ui.target_label
        self.assess_p = self.ui.assess_p
        self.assess_i = self.ui.assess_i
        self.assess_notes = self.ui.assess_notes
        self.assess_save_btn = self.ui.assess_save_btn
        self.assess_p.setToolTip("Your independent assessment of Probability (1-5)")
        self.assess_i.setToolTip("Your independent assessment of Impact (1-5)")
        self.assess_notes.setToolTip(
            "Provide reasoning or evidence for your assessment scores"
        )
        self.assess_save_btn.setToolTip("Submit or update your personal assessment")
