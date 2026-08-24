"""MainWindow mixin for the Actions tab."""

from __future__ import annotations

from PySide6.QtCore import Qt  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import QMessageBox  # pylint: disable=no-name-in-module
from riskapp_client.domain.scored_entity_fields import ACTION_DEFAULT_STATUS


class ActionsMixin:
    """MainWindow mixin: ActionsMixin"""

    def _toggle_action_target_inputs(self) -> None:
        tab = self.actions_tab
        is_risk = tab.action_target_type.currentText() == "risk"
        tab.action_risk_combo.setEnabled(is_risk)
        tab.action_opp_combo.setEnabled(not is_risk)

    def _refresh_target_combo(self, combo, fetch_method, cache_attr: str) -> None:
        combo.setCurrentIndex(-1)
        pid = self.current_project_id
        if not pid:
            return
        items = self._call_backend("Backend error", fetch_method, pid)
        if items is None:
            return
        setattr(self, cache_attr, {item.id: item.title for item in items})
        combo.blockSignals(True)
        combo.clear()
        for item in items:
            combo.addItem(item.title, item.id)
        combo.blockSignals(False)

    def _refresh_action_risk_combo(self) -> None:
        self._refresh_target_combo(
            self.actions_tab.action_risk_combo,
            self.backend.list_risks,
            "_risk_title_by_id",
        )

    def _refresh_action_opp_combo(self) -> None:
        self._refresh_target_combo(
            self.actions_tab.action_opp_combo,
            self.backend.list_opportunities,
            "_opp_title_by_id",
        )

    def _refresh_actions(self, select_action_id: str | None = None) -> None:
        tab = self.actions_tab
        pid = self.current_project_id
        if not pid:
            return
        actions = self._call_backend("Backend error", self.backend.list_actions, pid)
        if actions is None:
            return
        self._action_by_id = {a.id: a for a in actions}  # cache for row clicks
        tab.actions_table.setRowCount(0)
        for a in actions:
            row = tab.actions_table.rowCount()
            tab.actions_table.insertRow(row)
            tab.actions_table.setItem(row, 0, self._mk_item(a.title, entity_id=a.id))
            tab.actions_table.setItem(row, 1, self._mk_item(a.kind))
            tab.actions_table.setItem(row, 2, self._mk_item(a.status))
            target = ""
            if a.risk_id:
                target = f"risk: {self._risk_title_by_id.get(a.risk_id, a.risk_id)}"
            elif a.opportunity_id:
                target = f"opp: {self._opp_title_by_id.get(a.opportunity_id, a.opportunity_id)}"
            tab.actions_table.setItem(row, 3, self._mk_item(target))
            tab.actions_table.setItem(row, 4, self._mk_item(a.owner_user_id or ""))
        self._select_row_by_entity_id(select_action_id, table=tab.actions_table)

    def _on_action_clicked(self, row: int, _col: int) -> None:
        tab = self.actions_tab
        it = tab.actions_table.item(row, 0)
        if not it:
            return
        aid = str(it.data(Qt.UserRole))
        a = getattr(self, "_action_by_id", {}).get(aid)
        if not a:
            return
        self.current_action_id = a.id
        tab.action_editor_label.setText(f"Editor (editing: {a.title})")
        if a.risk_id:
            tab.action_target_type.setCurrentText("risk")
            idx = tab.action_risk_combo.findData(a.risk_id)
            if idx >= 0:
                tab.action_risk_combo.setCurrentIndex(idx)
        else:
            tab.action_target_type.setCurrentText("opportunity")
            idx = tab.action_opp_combo.findData(a.opportunity_id)
            if idx >= 0:
                tab.action_opp_combo.setCurrentIndex(idx)
        tab.action_kind.setCurrentText(a.kind)
        tab.action_status.setCurrentText(a.status)
        tab.action_title.setText(a.title)
        tab.action_desc.setPlainText(a.description or "")
        tab.action_owner.setText(a.owner_user_id or "")
        self._toggle_action_target_inputs()

    def _start_new_action(self) -> None:
        tab = self.actions_tab
        self.current_action_id = None
        tab.action_editor_label.setText("Editor (new action)")
        tab.action_target_type.setCurrentText("risk")
        tab.action_kind.setCurrentText("mitigation")
        tab.action_status.setCurrentText(ACTION_DEFAULT_STATUS)
        tab.action_title.setText("")
        tab.action_desc.setPlainText("")
        tab.action_owner.setText("")
        tab.action_opp_combo.setCurrentIndex(-1)
        self._toggle_action_target_inputs()
        tab.actions_table.clearSelection()

    def _save_action(self) -> None:
        tab = self.actions_tab
        pid = self.current_project_id
        if not pid:
            QMessageBox.warning(self, "No project", "Select a project first.")
            return
        target_type = tab.action_target_type.currentText()
        if target_type == "risk":
            target_id = str(tab.action_risk_combo.currentData())
            if not target_id or target_id == "None":
                QMessageBox.warning(self, "Validation", "Pick a risk.")
                return
        else:
            target_id = str(tab.action_opp_combo.currentData())
            if not target_id or target_id == "None":
                QMessageBox.warning(self, "Validation", "Pick an opportunity.")
                return
        kind = tab.action_kind.currentText()
        status = tab.action_status.currentText()
        title = tab.action_title.text().strip()
        desc = tab.action_desc.toPlainText().strip()
        owner = tab.action_owner.text().strip() or None
        if not title:
            QMessageBox.warning(self, "Validation", "Title is required.")
            return
        kwargs = {
            "target_type": target_type,
            "target_id": target_id,
            "kind": kind,
            "title": title,
            "description": desc,
            "status": status,
            "owner_user_id": owner,
        }
        if self.current_action_id:
            a = self._call_backend(
                "Backend error",
                self.backend.update_action,
                pid,
                self.current_action_id,
                **kwargs,
            )
        else:
            a = self._call_backend(
                "Backend error", self.backend.create_action, pid, **kwargs
            )
        if a is None:
            return
        self._refresh_actions(select_action_id=a.id)
        self._update_sync_status()
