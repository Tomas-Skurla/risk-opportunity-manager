"""MainWindow mixin for shared state and common UI behavior."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypeVar, cast

from PySide6.QtCore import QEvent, QModelIndex, QObject, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QDateTimeEdit,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)
from riskapp_client.domain.scored_entity_fields import ALL_STATUSES, DEFAULT_STATUS
from riskapp_client.ui_v2.window_state import MainWindowState
from riskapp_client.utils.roles import role_at_least

if TYPE_CHECKING:
    from riskapp_client.domain.domain_models import Opportunity, Risk
    from riskapp_client.ui_v2.components.custom_gui_widgets import RiskForm
    from riskapp_client.ui_v2.tabs.actions_tab import ActionsTab
    from riskapp_client.ui_v2.tabs.assessments_tab import AssessmentsTab
    from riskapp_client.ui_v2.tabs.members_tab import MembersTab
    from riskapp_client.ui_v2.tabs.opportunities_tab import OpportunitiesTab
    from riskapp_client.ui_v2.tabs.risks_tab import RisksTab
    from riskapp_client.ui_v2.tabs.top_history_tab import TopHistoryTab

T = TypeVar("T")


class CoreMixin:
    """MainWindow mixin: CoreMixin"""

    # MainWindow and LayoutMixin provide these objects before CoreMixin uses them.
    # These are declarations only: they neither construct nor overwrite anything.
    backend: Any
    role_status: QLabel
    new_risk_btn: QPushButton
    new_opp_btn: QPushButton
    risk_form: RiskForm
    opp_form: RiskForm
    risks_table: QTableWidget
    opps_table: QTableWidget
    risks_tab: RisksTab
    opps_tab: OpportunitiesTab
    actions_tab: ActionsTab
    assessments_tab: AssessmentsTab
    members_tab: MembersTab
    top_tab: TopHistoryTab

    if TYPE_CHECKING:
        # Implemented by sibling mixins in the concrete MainWindow class. Keeping
        # these declarations behind TYPE_CHECKING avoids shadowing those methods
        # at runtime through MainWindow's multiple-inheritance method order.
        # pylint: disable=unused-argument
        def _commit_editor_changes(
            self, *, refresh: bool, select_id: str | None = None
        ) -> None: ...

        def _commit_opp_editor_changes(
            self, *, refresh: bool, select_id: str | None = None
        ) -> None: ...

        # pylint: enable=unused-argument

    state: MainWindowState

    # Compatibility aliases keep existing mixins and external callers stable
    # while new cross-cutting state is made explicit through ``self.state``.
    @property
    def current_project_id(self) -> str | None:
        return self.state.project_id

    @current_project_id.setter
    def current_project_id(self, value: str | None) -> None:
        self.state.project_id = value

    @property
    def current_risk_id(self) -> str | None:
        return self.state.risk_id

    @current_risk_id.setter
    def current_risk_id(self, value: str | None) -> None:
        if value != self.state.risk_id:
            self.state.risk_editor_base_version = None
        self.state.risk_id = value

    @property
    def _risk_editor_base_version(self) -> int | None:
        return self.state.risk_editor_base_version

    @_risk_editor_base_version.setter
    def _risk_editor_base_version(self, value: int | None) -> None:
        self.state.risk_editor_base_version = value

    @property
    def current_opportunity_id(self) -> str | None:
        return self.state.opportunity_id

    @current_opportunity_id.setter
    def current_opportunity_id(self, value: str | None) -> None:
        if value != self.state.opportunity_id:
            self.state.opportunity_editor_base_version = None
        self.state.opportunity_id = value

    @property
    def _opportunity_editor_base_version(self) -> int | None:
        return self.state.opportunity_editor_base_version

    @_opportunity_editor_base_version.setter
    def _opportunity_editor_base_version(self, value: int | None) -> None:
        self.state.opportunity_editor_base_version = value

    @property
    def current_action_id(self) -> str | None:
        return self.state.action_id

    @current_action_id.setter
    def current_action_id(self, value: str | None) -> None:
        self.state.action_id = value

    @property
    def current_assessment_item_type(self) -> str:
        return self.state.assessment_item_type

    @current_assessment_item_type.setter
    def current_assessment_item_type(self, value: str) -> None:
        self.state.assessment_item_type = value

    @property
    def current_assessment_item_id(self) -> str | None:
        return self.state.assessment_item_id

    @current_assessment_item_id.setter
    def current_assessment_item_id(self, value: str | None) -> None:
        self.state.assessment_item_id = value

    @property
    def current_role(self) -> str:
        return self.state.role

    @current_role.setter
    def current_role(self, value: str) -> None:
        self.state.role = value

    @property
    def _offline_mode(self) -> bool:
        return self.state.offline_mode

    @_offline_mode.setter
    def _offline_mode(self, value: bool) -> None:
        self.state.offline_mode = value

    @property
    def _role_assumed(self) -> bool:
        return self.state.role_assumed

    @_role_assumed.setter
    def _role_assumed(self, value: bool) -> None:
        self.state.role_assumed = value

    def _init_state(self) -> None:
        """Initialize state owned by individual features, not shared context."""
        if not hasattr(self, "state"):
            self.state = MainWindowState()
        # Role cache per project.
        self._role_by_project: dict[str, str] = {}
        # Auto-snapshot throttle.
        self._last_auto_snapshot_by_project: dict[str, datetime] = {}
        self._opp_title_by_id: dict[str, str] = {}
        self._opp_cache: dict[str, Opportunity] = {}
        self._risk_cache: dict[str, Risk] = {}
        self._opp_editor_dirty: bool = False
        self._editor_dirty: bool = False
        self._risks_col_widths: dict[str, list[int]] = {}
        self._risks_last_pid: str | None = None
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
        """Return whether the selected project is local-only."""
        return bool(
            self.state.project_id and str(self.state.project_id).startswith("local-")
        )

    def _set_role_status(self, *, role: str, offline: bool, assumed: bool) -> None:
        self.state.role = role or "unknown"
        self.state.offline_mode = bool(offline)
        self.state.role_assumed = bool(assumed)
        # Detect superadmin for display.
        is_super = False
        try:
            is_super = self.backend.is_superuser()
        except (AttributeError, RuntimeError):
            logging.getLogger(__name__).debug("Superuser check failed", exc_info=True)
        display_role = "superadmin" if is_super else self.state.role
        suffix = ""
        if offline:
            suffix += " (offline)"
        if assumed:
            suffix += " (assumed)"
        self.role_status.setText(f"Role: {display_role}{suffix}")

    def _role_for_local_edits(self) -> str:
        """Return the role used for local-only UI checks."""
        if self.state.offline_mode and self.state.role == "unknown":
            return "member"
        return self.state.role

    def _can_mark_deleted(self) -> bool:
        """Return True if the user can set status=deleted in the UI."""
        return bool(self.state.project_id) and role_at_least(
            self._role_for_local_edits(), "manager"
        )

    def _apply_permissions(self) -> None:
        """Enable/disable UI controls based on the user's role and state."""
        pid = self.state.project_id
        role_for_local = self._role_for_local_edits()
        assumed_member_offline = bool(
            self.state.offline_mode and self.state.role == "unknown"
        )
        can_edit_local = bool(pid) and role_at_least(role_for_local, "member")
        can_take_snapshots = (
            bool(pid)
            and (not self.state.offline_mode)
            and role_at_least(self.state.role, "manager")
        )
        can_manage_members = (
            bool(pid)
            and (not self.state.offline_mode)
            and role_at_least(self.state.role, "admin")
        )
        can_set_deleted = self._can_mark_deleted()
        # Update the role label if we assumed member offline.
        if assumed_member_offline and not self.state.role_assumed:
            suffix = ""
            if self.state.offline_mode:
                suffix += " (offline)"
            suffix += " (assumed)"
            self.role_status.setText(f"Role: {role_for_local}{suffix}")
            self.state.role_assumed = True
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
        for action_widget in (
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
            action_widget.setEnabled(can_edit_local)
        # Assessments
        for assessment_widget in (
            self.assessments_tab.assess_p,
            self.assessments_tab.assess_i,
            self.assessments_tab.assess_notes,
            self.assessments_tab.assess_save_btn,
        ):
            assessment_widget.setEnabled(can_edit_local)
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
            item.setData(Qt.ItemDataRole.UserRole, entity_id)
        if align_center:
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
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
            if it and str(it.data(Qt.ItemDataRole.UserRole)) == target:
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
            QMessageBox.critical(cast(QWidget, self), error_title, str(exc))
            return None

    def _update_scored_filter_report(
        self,
        label: QLabel,
        full_count: int,
        filtered: Sequence[object],
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
        table.setCurrentIndex(QModelIndex())

    @staticmethod
    def _is_inside(container: object | None, w: object | None) -> bool:
        if not container or not w:
            return False
        try:
            return bool(w is container or container.isAncestorOf(w))  # type: ignore[attr-defined]
        except (AttributeError, RuntimeError):
            logging.getLogger(__name__).debug("Widget ancestry check failed", exc_info=True)
            return False

    def _active_scored_tab_context(
        self,
    ) -> tuple[
        QWidget,
        QTableWidget,
        QWidget | None,
        Callable[[], None],
        Callable[[], None],
    ] | None:
        """Return context for the currently active scored-entity tab.
        Returns:
            (tab_widget, table_widget, editor_card, commit_fn, clear_selection_fn)
            or None if the active tab is not a scored-entity tab.
        """
        ui = getattr(self, "ui", None)
        if ui is None:
            return None
        current = ui.main_stacked_widget.currentWidget()
        if current is getattr(self, "risks_tab", None):
            return (
                self.risks_tab,
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
                self.opps_tab,
                self.opps_table,
                editor,
                lambda: self._commit_opp_editor_changes(refresh=True),
                lambda: self._clear_table_selection(self.opps_table),
            )
        return None

    # pylint: disable-next=invalid-name
    def eventFilter(self, _obj: QObject, event: QEvent, /) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress and isinstance(
            event, QMouseEvent
        ):
            ctx = self._active_scored_tab_context()
            if ctx:
                tab_w, table_w, editor_w, commit_fn, clear_fn = ctx
                gp = event.globalPosition().toPoint()
                w = QApplication.widgetAt(gp)
                inside_table = self._is_inside(table_w, w)
                inside_editor = self._is_inside(editor_w, w)
                inside_tab = self._is_inside(tab_w, w)
                if (not inside_table) and (not inside_editor):
                    commit_fn()
                    if not inside_tab:
                        clear_fn()
        # This filter performs side effects but never consumes the event.
        return False

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
            table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        else:
            table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        table.setFixedHeight(h)
        table.setMinimumWidth(w)
