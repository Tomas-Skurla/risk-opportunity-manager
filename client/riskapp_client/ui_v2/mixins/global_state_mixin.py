"""MainWindow mixin for shared state and common UI behavior."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from riskapp_client.domain.domain_models import Opportunity, Risk

import logging

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QApplication,
    QDateTimeEdit,
    QLabel,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
)
from riskapp_client.domain.scored_entity_fields import ALL_STATUSES, DEFAULT_STATUS
from riskapp_client.utils.roles import role_at_least

T = TypeVar("T")


class CoreMixin:
    """MainWindow mixin: CoreMixin"""

    def _init_state(self) -> None:
        self.current_project_id: str | None = None
        self.current_risk_id: str | None = None
        self.current_opportunity_id: str | None = None
        # Assessments follow the last selected risk or opportunity.
        self.current_assessment_item_type: str = "risk"
        self.current_assessment_item_id: str | None = None
        # Role cache per project.
        self._role_by_project: dict[str, str] = {}
        self.current_role: str = "unknown"
        self._role_assumed: bool = False
        self._offline_mode: bool = False
        # Auto-snapshot throttle.
        self._last_auto_snapshot_by_project: dict[str, datetime] = {}
        self._opp_title_by_id: dict[str, str] = {}
        self._opp_cache: dict[str, Opportunity] = {}
        self._risk_cache: dict[str, Risk] = {}
        self._opp_editor_dirty: bool = False
        self._editor_dirty: bool = False
        self._risks_col_widths: dict[str, list[int]] = {}
        self._risks_last_pid: str | None = None
        self.current_action_id: str | None = None
        self._risk_title_by_id: dict[str, str] = {}
        # Help Desk state.
        self._current_ticket_id: str | None = None
        self._all_tickets: list = []
        # Members cache.
        self._cached_members: list = []

    def _detect_offline_mode(self) -> bool:
        """Return True if this is the OfflineBackend running without connection."""
        return bool(hasattr(self.backend, "remote") and self.backend.remote is None)

    def _is_local_project(self) -> bool:
        """Return True if the current project is local-only (not yet synced to server)."""
        return bool(self.current_project_id and str(self.current_project_id).startswith("local-"))

    def _set_role_status(self, *, role: str, offline: bool, assumed: bool) -> None:
        self.current_role = role or "unknown"
        self._offline_mode = bool(offline)
        self._role_assumed = bool(assumed)
        # Detect superadmin for display.
        is_super = False
        try:
            is_super = self.backend.is_superuser()
        except (AttributeError, RuntimeError):
            logging.getLogger(__name__).debug("Superuser check failed", exc_info=True)
        display_role = "superadmin" if is_super else self.current_role
        suffix = ""
        if offline:
            suffix += " (offline)"
        if assumed:
            suffix += " (assumed)"
        self.role_status.setText(f"Role: {display_role}{suffix}")

    def _role_for_local_edits(self) -> str:
        """Return the role used for local-only UI checks."""
        if self._offline_mode and self.current_role == "unknown":
            return "member"
        return self.current_role

    def _can_mark_deleted(self) -> bool:
        """Return True if the user can set status=deleted in the UI."""
        return bool(self.current_project_id) and role_at_least(
            self._role_for_local_edits(), "manager"
        )

    def _apply_permissions(self) -> None:
        """Enable/disable UI controls based on the user's role and state."""
        pid = self.current_project_id
        role_for_local = self._role_for_local_edits()
        assumed_member_offline = bool(
            self._offline_mode and self.current_role == "unknown"
        )
        can_edit_local = bool(pid) and role_at_least(role_for_local, "member")
        can_take_snapshots = (
            bool(pid)
            and (not self._offline_mode)
            and role_at_least(self.current_role, "manager")
        )
        can_manage_members = (
            bool(pid)
            and (not self._offline_mode)
            and role_at_least(self.current_role, "admin")
        )
        can_set_deleted = self._can_mark_deleted()
        # Update the role label if we assumed member offline.
        if assumed_member_offline and not self._role_assumed:
            suffix = ""
            if self._offline_mode:
                suffix += " (offline)"
            suffix += " (assumed)"
            self.role_status.setText(f"Role: {role_for_local}{suffix}")
            self._role_assumed = True
        # Risks / opportunities editors
        for btn, form in [
            (self.new_risk_btn, self.risk_form),
            (self.new_opp_btn, self.opp_form),
        ]:
            btn.setEnabled(can_edit_local)
            if hasattr(form, "set_editable"):
                form.set_editable(can_edit_local)
            elif hasattr(form, "btn"):
                form.btn.setEnabled(can_edit_local)
            # Only managers and admins can mark items deleted.
            if hasattr(form, "set_allow_deleted_status"):
                with suppress(AttributeError, RuntimeError):
                    form.set_allow_deleted_status(bool(can_set_deleted))
        # Actions editor
        for w in (
            self.actions_tab.action_target_type,
            self.actions_tab.action_risk_combo,
            self.actions_tab.action_opp_combo,
            self.actions_tab.action_kind,
            self.actions_tab.action_status,
            self.actions_tab.action_title,
            self.actions_tab.action_desc,
            self.actions_tab.action_owner,
            self.actions_tab.action_save_btn,
            self.actions_tab.action_new_btn,
        ):
            w.setEnabled(can_edit_local)
        # Assessments
        for w in (
            self.assessments_tab.assess_p,
            self.assessments_tab.assess_i,
            self.assessments_tab.assess_notes,
            self.assessments_tab.assess_save_btn,
        ):
            w.setEnabled(can_edit_local)
        # Snapshots / history
        self.top_tab.snapshot_btn.setEnabled(can_take_snapshots)
        self.top_tab.auto_snapshot_chk.setEnabled(can_take_snapshots)
        self.top_tab.auto_snapshot_kind.setEnabled(can_take_snapshots)
        self.top_tab.auto_snapshot_days.setEnabled(can_take_snapshots)
        # Members management
        self.members_tab.member_email.setEnabled(can_manage_members)
        self.members_tab.member_role.setEnabled(can_manage_members)
        self.members_tab.member_add_btn.setEnabled(can_manage_members)
        self.members_tab.member_remove_btn.setEnabled(can_manage_members)
        # Refresh is allowed even offline.
        self.members_tab.member_refresh_btn.setEnabled(bool(pid))

    def _mk_item(
        self,
        text: str,
        *,
        entity_id: str | None = None,
        align_center: bool = False,
    ) -> QTableWidgetItem:
        """Create a table item with optional entity-id in Qt.UserRole."""
        item = QTableWidgetItem(text)
        if entity_id is not None:
            item.setData(Qt.UserRole, entity_id)
        if align_center:
            item.setTextAlignment(Qt.AlignCenter)
        return item

    def _select_row_by_entity_id(
        self,
        entity_id: str | None,
        *,
        table: QTableWidget,
        id_col: int = 0,
    ) -> None:
        """Select a row in `table` by entity id stored in Qt.UserRole in `id_col`."""
        if not entity_id:
            return
        target = str(entity_id)
        for row in range(table.rowCount()):
            it = table.item(row, id_col)
            if it and str(it.data(Qt.UserRole)) == target:
                table.selectRow(row)
                table.setCurrentCell(row, id_col)
                return

    def _call_backend(
        self,
        error_title: str,
        fn: Callable[..., T],
        *args: Any,
        **kwargs: Any,
    ) -> T | None:
        """Call a backend function and show a modal error if it fails."""
        try:
            return fn(*args, **kwargs)
        except (RuntimeError, OSError) as exc:
            QMessageBox.critical(self, error_title, str(exc))
            return None

    def _update_scored_filter_report(
        self,
        label: QLabel,
        full_count: int,
        filtered: list[object],
        *,
        server_report: dict | None = None,
    ) -> None:
        """Render a common filter report for Risk/Opportunity tabs.

        If `server_report` is provided, prefer its aggregate stats (it reflects the
        full server-side dataset, not only what the UI loaded).
        """
        if not filtered and not server_report:
            label.setText(f"Showing 0/{full_count}")
            return
        if server_report:
            total = server_report.get("total")
            proj_total = server_report.get("project_total")
            mn = server_report.get("min_score")
            mx = server_report.get("max_score")
            avg_raw = server_report.get("avg_score")
            avg = float(avg_raw) if avg_raw is not None else None
            status_counts = server_report.get("status_counts") or {}
            category_counts = server_report.get("category_counts") or {}
            top_cats = [
                f"{c} {n}"
                for c, n in sorted(
                    category_counts.items(),
                    key=lambda kv: int(kv[1] or 0),
                    reverse=True,
                )[:3]
                if c and c != "(none)" and int(n or 0) > 0
            ]
            local_bits = f"Local {len(filtered)}/{full_count}"
            server_bits = (
                f"Server {int(total) if total is not None else '?'}"
                f"/{int(proj_total) if proj_total is not None else '?'}"
            )
            lines = [
                (
                    f"{local_bits} · {server_bits} · score min {mn} · max {mx} · avg {avg:.1f}"
                    if avg is not None
                    else f"{local_bits} · {server_bits}"
                ),
            ]
            order = list(ALL_STATUSES)
            status_bits = [
                f"{st} {status_counts.get(st, 0)}"
                for st in order
                if int(status_counts.get(st, 0) or 0) > 0
            ]
            if status_bits:
                lines.append(f"Status: {', '.join(status_bits)}")
            if top_cats:
                lines.append(f"Top categories: {', '.join(top_cats)}")
            label.setText("<br>".join(lines))
            return
        scores = [int(getattr(x, "score", 0) or 0) for x in filtered]
        avg = sum(scores) / len(scores)
        status_counts = Counter(
            (getattr(x, "status", None) or DEFAULT_STATUS) for x in filtered
        )
        order = list(ALL_STATUSES)
        status_bits = [
            f"{st} {status_counts[st]}" for st in order if status_counts.get(st)
        ]
        for st, n in status_counts.most_common():
            if st not in order:
                status_bits.append(f"{st} {n}")
        cat_counts = Counter(
            (getattr(x, "category", None) or "(none)") for x in filtered
        )
        top_cats = [
            f"{c} {n}" for c, n in cat_counts.most_common(3) if c and c != "(none)"
        ]
        lines = [
            f"Showing {len(filtered)}/{full_count} · score min {min(scores)} · max {max(scores)} · avg {avg:.1f}",
            f"Status: {', '.join(status_bits) if status_bits else '(none)'}",
        ]
        if top_cats:
            lines.append(f"Top categories: {', '.join(top_cats)}")
        label.setText("<br>".join(lines))

    def _clear_table_selection(self, table: QTableWidget) -> None:
        table.clearSelection()
        table.setCurrentItem(None)

    @staticmethod
    def _is_inside(container: object | None, w: object | None) -> bool:
        if not container or not w:
            return False
        try:
            return bool(w is container or container.isAncestorOf(w))  # type: ignore[attr-defined]
        except (AttributeError, RuntimeError):
            logging.getLogger(__name__).debug("Widget ancestry check failed", exc_info=True)
            return False

    def _active_scored_tab_context(self):
        """Return context for the currently active scored-entity tab.
        Returns:
            (tab_widget, table_widget, editor_card, commit_fn, clear_selection_fn)
            or None if the active tab is not a scored-entity tab.
        """
        if not hasattr(self, "tabs"):
            return None
        current = self.tabs.currentWidget()
        if current is getattr(self, "risks_tab", None):
            return (
                current,
                self.risks_table,
                getattr(self, "_editor_card", None),
                lambda: self._commit_editor_changes(refresh=True),
                lambda: self._clear_table_selection(self.risks_table),
            )
        if current is getattr(self, "opps_tab", None):
            editor = getattr(self, "_opp_editor_card", None)
            if editor is None and hasattr(self, "opps_tab"):
                editor = getattr(self.opps_tab, "editor_card", None)
            return (
                current,
                self.opps_table,
                editor,
                lambda: self._commit_opp_editor_changes(refresh=True),
                lambda: self._clear_table_selection(self.opps_table),
            )
        return None

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.MouseButtonPress:
            ctx = self._active_scored_tab_context()
            if ctx:
                tab_w, table_w, editor_w, commit_fn, clear_fn = ctx
                try:
                    gp = event.globalPosition().toPoint()
                except (AttributeError, RuntimeError):
                    gp = event.globalPos()
                w = QApplication.widgetAt(gp)
                inside_table = self._is_inside(table_w, w)
                inside_editor = self._is_inside(editor_w, w)
                inside_tab = self._is_inside(tab_w, w)
                if (not inside_table) and (not inside_editor):
                    commit_fn()
                    if not inside_tab:
                        clear_fn()
        return super().eventFilter(obj, event)

    def _dtedit_to_iso_utc_naive(self, w: QDateTimeEdit) -> str:
        """
        Convert QDateTimeEdit value to ISO string WITHOUT timezone (naive UTC),
        so FastAPI parses it as naive datetime and DB comparisons stay consistent.
        """
        secs = int(w.dateTime().toSecsSinceEpoch())
        return (
            datetime.fromtimestamp(secs, UTC)
            .replace(tzinfo=None, microsecond=0)
            .isoformat()
        )

    def _fit_table_to_contents(
        self, table: QTableWidget, max_height: int = 500
    ) -> None:
        """Dynamically shrink the table border to exactly wrap its rows/columns."""
        table.resizeColumnsToContents()
        table.resizeRowsToContents()
        hh = table.horizontalHeader()
        vh = table.verticalHeader()
        border_px = 2
        w = hh.length() + border_px
        h = hh.height() + vh.length() + border_px
        if h > max_height:
            h = max_height
            table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        else:
            table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.setFixedHeight(h)
        table.setMinimumWidth(w)
