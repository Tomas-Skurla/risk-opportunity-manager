"""Snapshot history helpers for the main window."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import QDateTime  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import (  # pylint: disable=no-name-in-module
    QDateTimeEdit,
    QMessageBox,
    QTableWidgetItem,
    QWidget,
)
from riskapp_client.utils.roles import role_at_least

if TYPE_CHECKING:
    from riskapp_client.ui_v2.tabs.top_history_tab import TopHistoryTab


class TopHistoryMixin:
    """Snapshot history mixin."""

    backend: Any
    current_project_id: str | None
    current_role: str
    top_tab: TopHistoryTab
    _last_auto_snapshot_by_project: dict[str, datetime]
    _detect_offline_mode: Callable[[], bool]
    _is_local_project: Callable[[], bool]
    _mk_item: Callable[..., QTableWidgetItem]
    _start_background_job: Callable[..., bool]

    if TYPE_CHECKING:
        # Implemented by CoreMixin in the concrete MainWindow class.
        # pylint: disable=unused-argument
        def _dtedit_to_iso_utc_naive(self, w: QDateTimeEdit) -> str:
            return ""
        # pylint: enable=unused-argument

    def _history_job_payload(self, project_id: str) -> dict[str, object]:
        tab = self.top_tab
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
        return {
            "project_id": str(project_id),
            "history": {
                "kind": kind,
                "limit": limit,
                "from_ts": from_ts,
                "to_ts": to_ts,
            },
            "display": {"kind": kind, "limit": limit, "period": period},
        }

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
                cast(QWidget, self),
                "Not allowed",
                "You need manager role to create snapshot.",
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
        if not hasattr(self.backend, "create_snapshot"):
            return
        payload = self._history_job_payload(str(pid))
        payload["kind"] = kind
        self._start_background_job(
            "snapshot",
            payload,
            on_success=lambda result, project_id=str(pid), completed_at=now: (
                self._snapshot_succeeded(
                    result,
                    project_id=project_id,
                    automatic=True,
                    completed_at=completed_at,
                )
            ),
            # Automatic work must never interrupt the user with a modal dialog.
            on_failure=lambda _message: None,
        )

    def _snapshot_now(self) -> None:
        pid = self.current_project_id
        if not pid:
            return
        if self._is_local_project():
            QMessageBox.information(
                cast(QWidget, self),
                "Snapshots",
                "Sync this project to the server first.",
            )
            return
        if not hasattr(self.backend, "create_snapshot"):
            QMessageBox.information(
                cast(QWidget, self),
                "Snapshots",
                "This backend does not support snapshots.",
            )
            return
        payload = self._history_job_payload(str(pid))
        # Preserve the manual action's existing meaning: capture both entity
        # types. The automatic timer still honours its configured kind.
        payload["kind"] = None
        if not self._start_background_job(
            "snapshot",
            payload,
            on_success=lambda result, project_id=str(pid): self._snapshot_succeeded(
                result,
                project_id=project_id,
                automatic=False,
            ),
            on_failure=lambda message: QMessageBox.warning(
                cast(QWidget, self),
                "Snapshot failed",
                message,
            ),
        ):
            QMessageBox.information(
                cast(QWidget, self),
                "Snapshots",
                "Another background operation is already running.",
            )

    def _refresh_top_history(self) -> None:
        tab = self.top_tab
        pid = self.current_project_id
        if not pid:
            return
        if self._is_local_project():
            tab.top_table.setRowCount(0)
            tab.top_report.setText(
                "Local project: sync to the server to use top history."
            )
            return
        if not hasattr(self.backend, "top_history"):
            tab.top_table.setRowCount(0)
            tab.top_report.setText("Top history not supported by this backend.")
            return
        if not self._start_background_job(
            "history",
            self._history_job_payload(str(pid)),
            on_success=self._history_succeeded,
            on_failure=lambda message: QMessageBox.warning(
                cast(QWidget, self),
                "Top history failed",
                message,
            ),
        ):
            tab.top_report.setText("Another background operation is already running.")

    def _snapshot_succeeded(
        self,
        result: object,
        *,
        project_id: str,
        automatic: bool,
        completed_at: datetime | None = None,
    ) -> None:
        if automatic:
            self._last_auto_snapshot_by_project[project_id] = (
                completed_at or datetime.now(UTC).replace(tzinfo=None)
            )
        if not isinstance(result, dict):
            return
        if str(self.current_project_id or "") != project_id:
            return
        if result.get("history_error"):
            self.top_tab.top_report.setText(
                "Snapshot created, but history could not be refreshed: "
                + str(result["history_error"])
            )
            return
        self._history_succeeded(result)

    def _history_succeeded(self, result: object) -> None:
        if not isinstance(result, dict):
            return
        if str(result.get("project_id") or "") != str(self.current_project_id or ""):
            return
        batches = result.get("history")
        display = result.get("display") or {}
        if not isinstance(batches, list) or not isinstance(display, dict):
            return
        kind = str(display.get("kind") or "risks")
        limit = int(display.get("limit") or 10)
        period = str(display.get("period") or "All")
        self._render_top_history(
            batches,
            kind=kind,
            limit=limit,
            period=period,
        )

    def _render_top_history(
        self,
        batches: list[dict],
        *,
        kind: str,
        limit: int,
        period: str,
    ) -> None:
        tab = self.top_tab
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
        """Update the date range and its editability for the selected period."""
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
