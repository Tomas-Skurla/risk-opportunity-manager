"""Minimal synchronization conflict-resolution dialog."""

from __future__ import annotations

import json
import sqlite3
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

from riskapp_client.services.conflict_merge import mergeable_fields
from riskapp_client.ui_v2.components.conflict_field_merge_dialog import (
    ConflictFieldMergeDialog,
)
from riskapp_client.ui_v2.ui.ui_conflict_center_dialog import (
    Ui_conflict_center_dialog as Ui_ConflictCenterDialog,
)

ResolveCallback = Callable[..., dict[str, Any]]


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
        self.merge_btn = self.ui.merge_btn
        self.use_server_btn = self.ui.use_server_btn
        self.later_btn = self.ui.later_btn
        self.merge_btn.setAccessibleName("Merge selected fields")
        self.merge_btn.setToolTip(
            "Choose values from both copies, then queue an update at the "
            "saved server version"
        )

        header = self.table.horizontalHeader()
        resize_mode = QHeaderView.ResizeMode
        header.setSectionResizeMode(resize_mode.ResizeToContents)
        header.setSectionResizeMode(1, resize_mode.Stretch)
        header.setSectionResizeMode(3, resize_mode.Stretch)

        # PySide signals are runtime descriptors that Pylint cannot infer.
        # pylint: disable=no-member
        self.table.itemSelectionChanged.connect(self._show_selection)
        self.keep_mine_btn.clicked.connect(lambda: self._resolve_selected("keep_mine"))
        self.use_server_btn.clicked.connect(
            lambda: self._resolve_selected("use_server")
        )
        self.merge_btn.clicked.connect(self._open_merge_dialog)
        self.later_btn.clicked.connect(self.reject)
        # pylint: enable=no-member

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
                    item.setData(
                        Qt.ItemDataRole.UserRole,
                        str(conflict.get("change_id") or ""),
                    )
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
        displayed_version = self._displayed_server_version(conflict)
        self.keep_mine_btn.setEnabled(
            bool(conflict and displayed_version is not None)
        )
        self.use_server_btn.setEnabled(
            bool(
                conflict
                and displayed_version is not None
                and conflict.get("server_record")
            )
        )
        self.merge_btn.setEnabled(bool(conflict and mergeable_fields(conflict)))
        if self.use_server_btn.isEnabled():
            self.use_server_btn.setToolTip(
                "Discard this queued local write and replace it with the saved server copy"
            )
        elif conflict:
            self.use_server_btn.setToolTip(
                "The saved server copy is unavailable for this conflict"
            )

    @staticmethod
    def _displayed_server_version(
        conflict: dict[str, Any] | None,
    ) -> int | None:
        if not conflict:
            return None
        raw = conflict.get("server_version")
        if raw is None and isinstance(conflict.get("server_record"), dict):
            raw = conflict["server_record"].get("version")
        return raw if isinstance(raw, int) and not isinstance(raw, bool) else None

    def _show_selection(self) -> None:
        conflict = self._selected_conflict()
        self._set_action_state(conflict)
        if conflict is None:
            self.local_copy.clear()
            self.server_copy.clear()
            return
        self.local_copy.setPlainText(self._pretty_json(conflict.get("record")))
        self.server_copy.setPlainText(self._pretty_json(conflict.get("server_record")))

    def _open_merge_dialog(self) -> None:
        conflict = self._selected_conflict()
        if conflict is None or not mergeable_fields(conflict):
            return
        dialog = ConflictFieldMergeDialog(conflict, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._resolve_selected("merge", dialog.choices())

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
        yes = QMessageBox.StandardButton.Yes
        no = QMessageBox.StandardButton.No
        return (
            QMessageBox.question(
                self,
                "Resolve synchronization conflict",
                prompt,
                yes | no,
                no,
            )
            == yes
        )

    def _resolve_selected(
        self, resolution: str, choices: dict[str, str] | None = None
    ) -> None:
        conflict = self._selected_conflict()
        if conflict is None:
            return
        change_id = str(conflict.get("change_id") or "")
        title = str(conflict.get("title") or conflict.get("entity_id") or "item")
        if not change_id or (
            resolution != "merge" and not self._confirm_resolution(resolution, title)
        ):
            return
        try:
            expected_server_version = self._displayed_server_version(conflict)
            if resolution == "merge":
                if not choices or "mine" not in choices.values():
                    raise ValueError("Choose at least one of your values")
                result = self._resolve_conflict(
                    change_id,
                    resolution,
                    choices,
                    expected_server_version=expected_server_version,
                )
            else:
                result = self._resolve_conflict(
                    change_id,
                    resolution,
                    expected_server_version=expected_server_version,
                )
            if not isinstance(result, dict) or not bool(result.get("resolved")):
                raise RuntimeError("The conflict was not resolved")
        except (KeyError, RuntimeError, ValueError, sqlite3.Error) as exc:
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
