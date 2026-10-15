"""MainWindow mixin for shared state and common UI behavior."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from sqlite3 import Error as SQLiteError
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
    from riskapp_client.ui_v2.ui.ui_main_window_design import Ui_MainWindow

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
    ui: Ui_MainWindow

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

    # Shorthand properties for the mixins; the state itself lives in
    # ``self.state``, and some setters keep related fields consistent.
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
        if value != self.state.action_id:
            self.state.action_editor_base_version = None
        self.state.action_id = value

    @property
    def _action_editor_base_version(self) -> int | None:
        return self.state.action_editor_base_version

    @_action_editor_base_version.setter
    def _action_editor_base_version(self, value: int | None) -> None:
        self.state.action_editor_base_version = value

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
        # Role cache per project.
        self._role_by_project: dict[str, str] = {}
        # Auto-snapshot throttle.
        self._last_auto_snapshot_by_project: dict[str, datetime] = {}
        self._opp_title_by_id: dict[str, str] = {}
        self._opp_cache: dict[str, Opportunity] = {}
        self._risk_cache: dict[str, Risk] = {}
        self._opp_editor_dirty: bool = False
        self._editor_dirty: bool = False
        self._risk_title_by_id: dict[str, str] = {}
        # Help Desk state.
        self._current_ticket_id: str | None = None
        self._all_tickets: list = []
        # Members cache.
        self._cached_members: list = []
        self._action_by_id: dict = {}

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
        except AttributeError, RuntimeError:
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
        has_project = bool(self.state.project_id)
        online = not self.state.offline_mode
        can_edit = has_project and role_at_least(self._role_for_local_edits(), "member")
        can_snapshot = (
            has_project and online and role_at_least(self.state.role, "manager")
        )
        can_manage = has_project and online and role_at_least(self.state.role, "admin")
        can_delete = self._can_mark_deleted()
        if not online and self.state.role == "unknown" and not self.state.role_assumed:
            self.role_status.setText("Role: member (offline) (assumed)")
            self.state.role_assumed = True
        for btn, form in (
            (self.new_risk_btn, self.risk_form),
            (self.new_opp_btn, self.opp_form),
        ):
            btn.setEnabled(can_edit)
            form.set_editable(can_edit)
            form.set_allow_deleted_status(can_delete)
        actions, assess = self.actions_tab, self.assessments_tab
        top, members = self.top_tab, self.members_tab
        for enabled, widgets in (
            (
                can_edit,
                (
                    actions.action_target_type,
                    actions.action_risk_combo,
                    actions.action_opp_combo,
                    actions.action_kind,
                    actions.action_status,
                    actions.action_title,
                    actions.action_desc,
                    actions.action_owner,
                    actions.action_save_btn,
                    actions.action_new_btn,
                    assess.assess_p,
                    assess.assess_i,
                    assess.assess_notes,
                    assess.assess_save_btn,
                ),
            ),
            (
                can_snapshot,
                (
                    top.snapshot_btn,
                    top.auto_snapshot_chk,
                    top.auto_snapshot_kind,
                    top.auto_snapshot_days,
                ),
            ),
            (
                can_manage,
                (
                    members.member_email,
                    members.member_role,
                    members.member_add_btn,
                    members.member_remove_btn,
                ),
            ),
            (has_project, (members.member_refresh_btn,)),
        ):
            for widget in widgets:
                widget.setEnabled(enabled)

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
        except (RuntimeError, OSError, SQLiteError) as exc:
            QMessageBox.critical(cast(QWidget, self), error_title, str(exc))
            return None

    def _clear_table_selection(self, table: QTableWidget) -> None:
        table.clearSelection()
        table.setCurrentIndex(QModelIndex())

    @staticmethod
    def _is_inside(container: object | None, w: object | None) -> bool:
        if not container or not w:
            return False
        try:
            return bool(w is container or container.isAncestorOf(w))  # type: ignore[attr-defined]
        except AttributeError, RuntimeError:
            logging.getLogger(__name__).debug(
                "Widget ancestry check failed", exc_info=True
            )
            return False

    def _active_scored_tab_context(
        self,
    ) -> (
        tuple[
            QWidget,
            QTableWidget,
            QWidget | None,
            Callable[[], None],
            Callable[[], None],
        ]
        | None
    ):
        """Return context for the currently active scored-entity tab.
        Returns:
            (tab_widget, table_widget, editor_card, commit_fn, clear_selection_fn)
            or None if the active tab is not a scored-entity tab.
        """
        current = self.ui.main_stacked_widget.currentWidget()
        if current is self.risks_tab:
            return (
                self.risks_tab,
                self.risks_table,
                self.risks_tab.editor_card,
                lambda: self._commit_editor_changes(refresh=True),
                lambda: self._clear_table_selection(self.risks_table),
            )
        if current is self.opps_tab:
            return (
                self.opps_tab,
                self.opps_table,
                self.opps_tab.editor_card,
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
