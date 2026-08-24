"""Shared tab for risks and opportunities."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QHeaderView,
    QSizePolicy,
    QWidget,  # pylint: disable=no-name-in-module
)

from riskapp_client.domain.scored_entity_fields import ALL_STATUSES
from riskapp_client.services.entity_filters import ANY_STATUS
from riskapp_client.ui_v2.components.custom_gui_widgets import (
    setup_readonly_table,
)
from riskapp_client.ui_v2.tabs.ui_scored_entities_tab import (
    Ui_Form as Ui_ScoredEntitiesTab,
)

MAX_SCORE_UI = 25


class ScoredEntitiesTab(QWidget):
    """Generic list + editor tab for scored entities."""

    def __init__(
        self,
        *,
        entity_label_singular: str,
        on_export_csv: Callable[[], None],
        on_refresh: Callable[[], None],
        on_item_clicked: Callable[[int, int], None],
        on_new_item: Callable[[], None],
        on_save_item: Callable[[dict], None],
        on_delete_item: Callable[[], None],
        on_mark_dirty: Callable[..., None],
        on_fit_table_card: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_refresh = on_refresh
        self._on_new_item = on_new_item
        self.ui = Ui_ScoredEntitiesTab()
        self.ui.setupUi(self)
        setup_readonly_table(self.ui.table, excel_delegate=True)
        hh = self.ui.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        self.ui.table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        self.ui.table.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        if self.ui.table.horizontalHeaderItem(0):
            self.ui.table.horizontalHeaderItem(0).setToolTip(
                "Code: A unique identifier or short reference"
            )
        if self.ui.table.horizontalHeaderItem(1):
            self.ui.table.horizontalHeaderItem(1).setToolTip(
                "Title: The name or brief summary"
            )
        if self.ui.table.horizontalHeaderItem(2):
            self.ui.table.horizontalHeaderItem(2).setToolTip(
                "Category: The classification or grouping"
            )
        if self.ui.table.horizontalHeaderItem(3):
            self.ui.table.horizontalHeaderItem(3).setToolTip(
                "Status: The current lifecycle state"
            )
        if self.ui.table.horizontalHeaderItem(4):
            self.ui.table.horizontalHeaderItem(4).setToolTip(
                "Owner: The team member assigned to manage this"
            )
        if self.ui.table.horizontalHeaderItem(5):
            self.ui.table.horizontalHeaderItem(5).setToolTip(
                "Probability: The likelihood of this occurring (1-5)"
            )
        if self.ui.table.horizontalHeaderItem(6):
            self.ui.table.horizontalHeaderItem(6).setToolTip(
                "Impact: The severity if this occurs (1-5)"
            )
        if self.ui.table.horizontalHeaderItem(7):
            self.ui.table.horizontalHeaderItem(7).setToolTip(
                "Score: Calculated as Probability × Impact (1-25)"
            )
        self.ui.filter_search.setToolTip("Search by Code, Title, or Description")
        self.ui.filter_min_score.setToolTip("Filter by minimum score")
        self.ui.filter_max_score.setToolTip("Filter by maximum score")
        self.ui.filter_status.setToolTip("Filter by lifecycle status")
        self.ui.filter_category.setToolTip("Filter by category")
        self.ui.filter_owner.setToolTip("Filter by assigned owner")
        self.ui.filter_from.setToolTip(
            "Filter items identified on or after this date (YYYY-MM-DD)"
        )
        self.ui.filter_to.setToolTip(
            "Filter items identified on or before this date (YYYY-MM-DD)"
        )
        self.ui.export_btn.setToolTip("Export the current table view to a CSV file")
        self.ui.clear_btn.setToolTip("Clear all active filters")
        self.ui.new_btn.setToolTip("Create a new blank item")
        self.ui.delete_btn.setToolTip("Delete the currently selected item")
        self.ui.verticalLayout_2.setAlignment(Qt.AlignTop)
        self.ui.table.cellClicked.connect(on_item_clicked)
        self.ui.splitter.setStretchFactor(0, 3)
        self.ui.splitter.setStretchFactor(1, 7)
        self.ui.splitter.setSizes([30000, 70000])

        self.ui.filter_status.addItems([ANY_STATUS, *ALL_STATUSES])
        self.ui.filter_owner.addItem("(any owner)", None)
        self.ui.filter_owner.addItem("(unassigned)", "__unassigned__")

        self.ui.export_btn.clicked.connect(on_export_csv)
        self.ui.clear_btn.clicked.connect(self.clear_filters)
        self.ui.new_btn.clicked.connect(on_new_item)
        self.ui.delete_btn.clicked.connect(on_delete_item)

        for w in (
            self.ui.filter_search,
            self.ui.filter_category,
            self.ui.filter_from,
            self.ui.filter_to,
        ):
            w.textChanged.connect(lambda *_: self._on_refresh())
        for w in (self.ui.filter_min_score, self.ui.filter_max_score):
            w.valueChanged.connect(lambda *_: self._on_refresh())
        self.ui.filter_status.currentTextChanged.connect(lambda *_: self._on_refresh())
        self.ui.filter_owner.currentIndexChanged.connect(lambda *_: self._on_refresh())
        original_mouse_press = self.ui.table.mousePressEvent

        def _table_mouse_press(event):
            item = self.ui.table.itemAt(event.pos())
            if not item:  # No row was clicked
                self.ui.table.clearSelection()
                self._on_new_item()
            original_mouse_press(event)

        self.ui.table.mousePressEvent = _table_mouse_press
        original_card_press = self.ui.table_card.mousePressEvent

        def _card_mouse_press(event):
            self.ui.table.clearSelection()
            self._on_new_item()
            original_card_press(event)

        self.ui.table_card.mousePressEvent = _card_mouse_press
        self.table = self.ui.table
        self.form = self.ui.form
        self.form.on_submit = on_save_item
        # Override the hardcoded "Save Risk" label for non-risk entities
        # and prevent retranslateUi from reverting it.
        self._entity_label = entity_label_singular.capitalize()
        self.form.btn.setText(f"Save {self._entity_label}")
        _original_retranslate = self.form.ui.retranslateUi
        _btn = self.form.btn
        _label = self._entity_label
        def _patched_retranslate(w):
            _original_retranslate(w)
            _btn.setText(f"Save {_label}")
        self.form.ui.retranslateUi = _patched_retranslate
        if hasattr(self.form, "track_dirty_state"):
            self.form.track_dirty_state(on_mark_dirty)
        self.new_btn = self.ui.new_btn
        self.delete_btn = self.ui.delete_btn
        self.filter_search = self.ui.filter_search
        self.filter_min_score = self.ui.filter_min_score
        self.filter_max_score = self.ui.filter_max_score
        self.filter_status = self.ui.filter_status
        self.filter_category = self.ui.filter_category
        self.filter_owner = self.ui.filter_owner
        self.filter_from = self.ui.filter_from
        self.filter_to = self.ui.filter_to
        self.filter_report = self.ui.filter_report
        self.editor_label = self.ui.editor_label
        self.filter_max_score.blockSignals(True)
        self.filter_max_score.setValue(self.filter_max_score.maximum())
        self.filter_max_score.blockSignals(False)

    def clear_filters(self) -> None:
        """Reset all filter widgets to defaults."""
        widgets = [
            self.filter_search,
            self.filter_min_score,
            self.filter_max_score,
            self.filter_status,
            self.filter_category,
            self.filter_owner,
            self.filter_from,
            self.filter_to,
        ]
        for w in widgets:
            w.blockSignals(True)
        self.filter_search.setText("")
        self.filter_min_score.setValue(0)
        self.filter_max_score.setValue(self.filter_max_score.maximum())
        self.filter_status.setCurrentIndex(0)
        self.filter_category.setText("")
        self.filter_owner.setCurrentIndex(0)
        self.filter_from.setText("")
        self.filter_to.setText("")
        for w in widgets:
            w.blockSignals(False)
        self._on_refresh()

    def set_owner_filter_members(self, members) -> None:
        """Populate the Owner filter dropdown with project members.

        Keeps the current selection when possible.
        """
        current = self.filter_owner.currentData()
        self.filter_owner.blockSignals(True)
        self.filter_owner.clear()
        self.filter_owner.addItem("(any owner)", None)
        self.filter_owner.addItem("(unassigned)", "__unassigned__")
        try:
            sorted_members = sorted(members or [], key=lambda m: m.email or "")
        except (AttributeError, TypeError):
            sorted_members = list(members or [])
        for m in sorted_members:
            uid = getattr(m, "user_id", None)
            email = getattr(m, "email", "")
            if uid and email:
                self.filter_owner.addItem(str(email), str(uid))
        if current is not None:
            idx = self.filter_owner.findData(current)
            if idx >= 0:
                self.filter_owner.setCurrentIndex(idx)
        self.filter_owner.blockSignals(False)
