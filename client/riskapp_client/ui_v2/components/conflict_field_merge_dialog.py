"""Choose local or saved server values for one synchronization conflict."""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import Qt  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import (  # pylint: disable=no-name-in-module
    QComboBox,
    QDialog,
    QHeaderView,
    QTableWidgetItem,
    QWidget,
)

from riskapp_client.services.conflict_merge import mergeable_fields
from riskapp_client.ui_v2.ui.ui_conflict_field_merge_dialog import (
    Ui_conflict_field_merge_dialog as Ui_ConflictFieldMergeDialog,
)


class ConflictFieldMergeDialog(QDialog):
    """Present the differing fields of one selected conflict."""

    def __init__(
        self, conflict: dict[str, Any], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.fields = mergeable_fields(conflict)
        if not self.fields:
            raise ValueError("This conflict cannot be merged field by field")

        self.ui = Ui_ConflictFieldMergeDialog()
        self.ui.setupUi(self)
        self.ui.item_label.setTextFormat(Qt.TextFormat.PlainText)
        self.ui.item_label.setText(
            str(conflict.get("title") or conflict.get("entity_id") or "Selected item")
        )
        self.ui.version_label.setText(
            f"Based on saved server version {conflict['server_version']}"
        )

        table = self.ui.field_table
        table.setAccessibleName("Choose the copy to keep for each differing field")
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        table.setRowCount(len(self.fields))

        self._selectors: dict[str, QComboBox] = {}
        for row, field in enumerate(self.fields):
            local_value = conflict["record"][field]
            server_value = conflict["server_record"][field]
            for column, value in enumerate(
                (field.replace("_", " ").title(), local_value, server_value)
            ):
                item = QTableWidgetItem(
                    value if column == 0 else self._display_value(value)
                )
                if column != 0:
                    item.setToolTip(self._display_value(value))
                table.setItem(row, column, item)
            selector = QComboBox(table)
            selector.setAccessibleName(f"Keep a value for {field.replace('_', ' ')}")
            selector.addItem("Server", "server")
            selector.addItem("Mine", "mine")
            # PySide signals are runtime descriptors that Pylint cannot infer.
            # pylint: disable=no-member
            selector.currentIndexChanged.connect(self._update_queue_state)
            # pylint: enable=no-member
            table.setCellWidget(row, 3, selector)
            self._selectors[field] = selector

        self._update_queue_state()
        # pylint: disable=no-member
        self.ui.cancel_btn.clicked.connect(self.reject)
        self.ui.queue_merge_btn.clicked.connect(self.accept)
        # pylint: enable=no-member

    @staticmethod
    def _display_value(value: Any) -> str:
        if value is None:
            return "(empty)"
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, default=str)

    def _update_queue_state(self, *_args: object) -> None:
        has_local_choice = any(
            selector.currentData() == "mine" for selector in self._selectors.values()
        )
        self.ui.queue_merge_btn.setEnabled(has_local_choice)

    def choices(self) -> dict[str, str]:
        """Return the explicit choice for every differing field."""
        return {
            field: str(selector.currentData())
            for field, selector in self._selectors.items()
        }
