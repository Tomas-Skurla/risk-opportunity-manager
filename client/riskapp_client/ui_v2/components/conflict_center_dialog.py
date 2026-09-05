"""Minimal synchronization conflict-resolution dialog."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt, Signal  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import (  # pylint: disable=no-name-in-module
    QDialog,
    QHeaderView,
    QMessageBox,
    QTableWidgetItem,
    QWidget,
)

from riskapp_client.ui_v2.components.ui_conflict_center_dialog import (
    Ui_ConflictCenterDialog,
)

ResolveCallback = Callable[[str, str], dict[str, Any]]


class ConflictCenterDialog(QDialog):
    """List persisted conflicts and apply an explicit user decision."""

    conflict_resolved = Signal(str, str)

    def __init__(
        self,
        conflicts: list[dict[str, Any]],
        resolve_conflict: ResolveCallback,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.ui = Ui_ConflictCenterDialog()
        self.ui.setupUi(self)
        self._conflicts = [dict(item) for item in conflicts]
        self._resolve_conflict = resolve_conflict
        self.table = self.ui.conflict_table
        self.local_copy = self.ui.local_copy
        self.server_copy = self.ui.server_copy
        self.keep_mine_btn = self.ui.keep_mine_btn
        self.use_server_btn = self.ui.use_server_btn
        self.later_btn = self.ui.later_btn

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)

        self.table.itemSelectionChanged.connect(self._show_selection)
        self.keep_mine_btn.clicked.connect(lambda: self._resolve_selected("keep_mine"))
        self.use_server_btn.clicked.connect(
            lambda: self._resolve_selected("use_server")
        )
        self.later_btn.clicked.connect(self.reject)

        self._populate_table()

    @staticmethod
    def _pretty_json(value: object) -> str:
        if value is None:
            return "Server copy unavailable for this conflict."
        try:
            return json.dumps(value, indent=2, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return str(value)

    def _populate_table(self) -> None:
        self.table.setRowCount(0)
        for row, conflict in enumerate(self._conflicts):
            self.table.insertRow(row)
            values = (
                str(conflict.get("entity") or "item").replace("_", " ").title(),
                str(conflict.get("title") or conflict.get("entity_id") or ""),
                str(conflict.get("op") or ""),
                str(conflict.get("reason") or "Conflict"),
                str(conflict.get("server_version") or "Unavailable"),
                str(conflict.get("server_updated_at") or "Unavailable"),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.UserRole, str(conflict.get("change_id") or ""))
                self.table.setItem(row, column, item)
        if self._conflicts:
            self.table.selectRow(0)
        else:
            self.local_copy.clear()
            self.server_copy.clear()
            self._set_action_state(None)

    def _selected_conflict(self) -> dict[str, Any] | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._conflicts):
            return None
        return self._conflicts[row]

    def _set_action_state(self, conflict: dict[str, Any] | None) -> None:
        self.keep_mine_btn.setEnabled(
            bool(conflict and conflict.get("server_version") is not None)
        )
        self.use_server_btn.setEnabled(bool(conflict and conflict.get("server_record")))
        if self.use_server_btn.isEnabled():
            self.use_server_btn.setToolTip(
                "Discard this queued local write and replace it with the saved server copy"
            )
        elif conflict:
            self.use_server_btn.setToolTip(
                "The saved server copy is unavailable for this conflict"
            )

    def _show_selection(self) -> None:
        conflict = self._selected_conflict()
        self._set_action_state(conflict)
        if conflict is None:
            self.local_copy.clear()
            self.server_copy.clear()
            return
        self.local_copy.setPlainText(self._pretty_json(conflict.get("record")))
        self.server_copy.setPlainText(self._pretty_json(conflict.get("server_record")))

    def _confirm_resolution(self, resolution: str, title: str) -> bool:
        if resolution == "keep_mine":
            prompt = (
                f"Keep your local version of “{title}”?\n\n"
                "It will be queued as a new update and may conflict again if "
                "the server changes before the next synchronization."
            )
        else:
            prompt = (
                f"Use the server version of “{title}”?\n\n"
                "Your queued local edits for this item will be discarded."
            )
        return (
            QMessageBox.question(
                self,
                "Resolve synchronization conflict",
                prompt,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            == QMessageBox.Yes
        )

    def _resolve_selected(self, resolution: str) -> None:
        conflict = self._selected_conflict()
        if conflict is None:
            return
        change_id = str(conflict.get("change_id") or "")
        title = str(conflict.get("title") or conflict.get("entity_id") or "item")
        if not change_id or not self._confirm_resolution(resolution, title):
            return
        try:
            result = self._resolve_conflict(change_id, resolution)
            if not isinstance(result, dict) or not bool(result.get("resolved")):
                raise RuntimeError("The conflict was not resolved")
        except (KeyError, RuntimeError, ValueError) as exc:
            QMessageBox.critical(self, "Conflict resolution failed", str(exc))
            return

        row = self.table.currentRow()
        self._conflicts.pop(row)
        self.conflict_resolved.emit(change_id, resolution)
        self._populate_table()
        if not self._conflicts:
            self.accept()

    def conflicts_remaining(self) -> int:
        """Return the number of conflicts still displayed."""
        return len(self._conflicts)
