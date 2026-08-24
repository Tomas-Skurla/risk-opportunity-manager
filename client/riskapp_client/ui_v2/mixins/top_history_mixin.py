"""Snapshot history helpers for the main window."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from PySide6.QtCore import QDateTime  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import QMessageBox  # pylint: disable=no-name-in-module
from riskapp_client.utils.roles import role_at_least


class TopHistoryMixin:
    """Snapshot history mixin."""

    def _maybe_auto_snapshot(self) -> None:
        """Take a snapshot automatically if enabled and the interval has elapsed."""
        tab = self.top_tab
        pid = self.current_project_id
        if not pid or self._detect_offline_mode() or self._is_local_project():
            return
        if (
            not tab.auto_snapshot_chk.isEnabled()
            or not tab.auto_snapshot_chk.isChecked()
        ):
            return
        if not role_at_least(self.current_role, "manager"):
            QMessageBox.information(
                self, "Not allowed", "You need manager role to create snapshot."
            )
            return
        days = int(tab.auto_snapshot_days.value())
        if days <= 0:
            return
        now = datetime.now(UTC).replace(tzinfo=None)
        last = self._last_auto_snapshot_by_project.get(pid)
        if last is not None and (now - last) < timedelta(days=days):
            return
        # Map the UI value to the API value.
        kind_ui = (tab.auto_snapshot_kind.currentText() or "Both").strip().lower()
        kind = (
            "risks"
            if kind_ui.startswith("risk")
            else ("opportunities" if kind_ui.startswith("opp") else "both")
        )
        try:
            if hasattr(self.backend, "create_snapshot"):
                self.backend.create_snapshot(pid, kind=kind)  # type: ignore[attr-defined]
        except (RuntimeError, OSError):
            # Avoid modal dialogs from the background timer.
            return
        self._last_auto_snapshot_by_project[pid] = now
        self._refresh_top_history()

    def _snapshot_now(self) -> None:
        pid = self.current_project_id
        if not pid:
            return
        if self._is_local_project():
            QMessageBox.information(
                self, "Snapshots", "Sync this project to the server first."
            )
            return
        if not hasattr(self.backend, "create_snapshot"):
            QMessageBox.information(
                self, "Snapshots", "This backend does not support snapshots."
            )
            return
        if (
            self._call_backend("Snapshot failed", self.backend.create_snapshot, pid)
            is None
        ):  # type: ignore[attr-defined]
            return
        self._refresh_top_history()

    def _refresh_top_history(self) -> None:
        tab = self.top_tab
        pid = self.current_project_id
        if not pid:
            return
        if self._is_local_project():
            tab.top_table.setRowCount(0)
            tab.top_report.setText("Local project: sync to the server to use top history.")
            return
        if not hasattr(self.backend, "top_history"):
            tab.top_table.setRowCount(0)
            tab.top_report.setText("Top history not supported by this backend.")
            return
        kind_ui = tab.top_kind.currentText().strip().lower()
        kind = "risks" if kind_ui.startswith("risk") else "opportunities"
        limit = int(tab.top_limit.value())
        period = tab.top_period.currentText()
        from_ts = None
        to_ts = None
        if period != "All":
            from_ts = self._dtedit_to_iso_utc_naive(tab.top_from)
            to_ts = self._dtedit_to_iso_utc_naive(tab.top_to)
            if from_ts and to_ts and from_ts > to_ts:
                from_ts, to_ts = to_ts, from_ts
        batches = self._call_backend(
            "Top history failed",
            self.backend.top_history,  # type: ignore[attr-defined]
            pid,
            kind=kind,
            limit=limit,
            from_ts=from_ts,
            to_ts=to_ts,
        )
        if batches is None:
            return
        tab.top_table.setRowCount(0)
        total_items = 0
        total_batches = 0
        for batch in batches or []:
            total_batches += 1
            captured_raw = str(batch.get("captured_at", ""))
            captured = captured_raw.replace("T", " ")[:19] if captured_raw else ""
            top = batch.get("top") or []
            for idx, item in enumerate(top, start=1):
                total_items += 1
                row = tab.top_table.rowCount()
                tab.top_table.insertRow(row)
                tab.top_table.setItem(
                    row, 0, self._mk_item(captured if idx == 1 else "")
                )
                tab.top_table.setItem(
                    row, 1, self._mk_item(str(idx), align_center=True)
                )
                tab.top_table.setItem(row, 2, self._mk_item(str(item.get("title", ""))))
                tab.top_table.setItem(
                    row,
                    3,
                    self._mk_item(str(item.get("probability", "")), align_center=True),
                )
                tab.top_table.setItem(
                    row,
                    4,
                    self._mk_item(str(item.get("impact", "")), align_center=True),
                )
                tab.top_table.setItem(
                    row, 5, self._mk_item(str(item.get("score", "")), align_center=True)
                )
        tab.top_report.setText(
            f"{kind.capitalize()} · Top {limit} · {period}"
            + (
                f" · {total_batches} snapshot(s) · {total_items} row(s)"
                if total_batches
                else " · (no data)"
            )
        )
        tab.top_table.resizeColumnsToContents()

    def _on_top_period_changed(self, _text: str) -> None:
        """Update the From/To widgets and toggle editability based on selected period."""
        tab = self.top_tab
        period = tab.top_period.currentText()
        now = QDateTime.currentDateTime()
        if period == "Last 7 days":
            tab.top_to.setDateTime(now)
            tab.top_from.setDateTime(now.addDays(-7))
        elif period == "Last 30 days":
            tab.top_to.setDateTime(now)
            tab.top_from.setDateTime(now.addDays(-30))
        custom = period == "Custom"
        tab.top_from.setEnabled(custom)
        tab.top_to.setEnabled(custom)
