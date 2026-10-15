"""MainWindow UI construction."""

from __future__ import annotations

import ctypes
import logging
import sys
from collections.abc import Callable
from typing import Any, cast

import qdarktheme  # type: ignore[import-untyped]
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
)
from riskapp_client import __version__
from riskapp_client.ui_v2.tabs.actions_tab import ActionsTab
from riskapp_client.ui_v2.tabs.assessments_tab import AssessmentsTab
from riskapp_client.ui_v2.tabs.helpdesk_tab import HelpDeskTab
from riskapp_client.ui_v2.tabs.matrix_tab import MatrixTab
from riskapp_client.ui_v2.tabs.members_tab import MembersTab
from riskapp_client.ui_v2.tabs.opportunities_tab import OpportunitiesTab
from riskapp_client.ui_v2.tabs.risks_tab import RisksTab
from riskapp_client.ui_v2.tabs.top_history_tab import TopHistoryTab
from riskapp_client.ui_v2.ui.ui_main_window_design import Ui_MainWindow

logger = logging.getLogger(__name__)


def _set_titlebar_dark(window: QMainWindow, dark: bool) -> None:
    """Set the title bar to dark or light mode."""
    # Qt 6.5+ color scheme API
    try:
        app = cast(QApplication | None, QApplication.instance())
        if app and hasattr(app, "styleHints"):
            hints = app.styleHints()
            if hasattr(hints, "setColorScheme"):
                scheme = Qt.ColorScheme.Dark if dark else Qt.ColorScheme.Light
                hints.setColorScheme(scheme)
                return
    except AttributeError, ImportError, RuntimeError:
        logger.debug("Qt ColorScheme API unavailable", exc_info=True)

    # Windows DWM API
    try:
        if sys.platform == "win32":
            hwnd = int(window.winId())
            dark_mode_attribute = 20
            value = ctypes.c_int(1 if dark else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                dark_mode_attribute,
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
            return
    except AttributeError, ImportError, OSError:
        logger.debug("DWM title bar API unavailable", exc_info=True)


class LayoutMixin:
    """Build the main window UI."""

    backend: Any
    current_opportunity_id: str | None
    current_risk_id: str | None

    _add_or_update_member: Callable[..., Any]
    _apply_helpdesk_filters: Callable[..., Any]
    _cancel_background_job: Callable[..., Any]
    _create_new_project: Callable[..., Any]
    _delete_current_project: Callable[..., Any]
    _delete_helpdesk_ticket: Callable[..., Any]
    _delete_opportunity: Callable[..., Any]
    _delete_risk: Callable[..., Any]
    _export_opportunities_csv: Callable[..., Any]
    _export_risks_csv: Callable[..., Any]
    _mark_editor_dirty: Callable[..., Any]
    _mark_opp_editor_dirty: Callable[..., Any]
    _maybe_auto_snapshot: Callable[..., Any]
    _on_action_clicked: Callable[..., Any]
    _on_helpdesk_ticket_clicked: Callable[..., Any]
    _on_matrix_kind_changed: Callable[..., Any]
    _on_member_selected: Callable[..., Any]
    _on_opportunity_clicked: Callable[..., Any]
    _on_project_selected: Callable[..., Any]
    _on_risk_clicked: Callable[..., Any]
    _on_top_period_changed: Callable[..., Any]
    _open_conflict_center: Callable[..., Any]
    _refresh_helpdesk: Callable[..., Any]
    _refresh_members: Callable[..., Any]
    _refresh_opportunities: Callable[..., Any]
    _refresh_risks: Callable[..., Any]
    _refresh_top_history: Callable[..., Any]
    _remove_selected_member: Callable[..., Any]
    _save_action: Callable[..., Any]
    _save_assessment: Callable[..., Any]
    _save_helpdesk_ticket: Callable[..., Any]
    _save_opportunity: Callable[..., Any]
    _save_risk: Callable[..., Any]
    _snapshot_now: Callable[..., Any]
    _start_new_action: Callable[..., Any]
    _start_new_helpdesk_ticket: Callable[..., Any]
    _start_new_opportunity: Callable[..., Any]
    _start_new_risk: Callable[..., Any]
    _sync_now: Callable[..., Any]
    _toggle_action_target_inputs: Callable[..., Any]

    def _build_ui(self) -> None:
        window = cast(QMainWindow, self)
        self.ui = Ui_MainWindow()
        self.ui.setupUi(window)
        window.setWindowTitle(f"RiskApp {__version__}")
        self.project_list = self.ui.project_list
        self.sync_btn = self.ui.sync_btn
        self.new_project_btn = self.ui.new_project_btn
        self.delete_project_btn = self.ui.delete_project_btn
        self._build_status_bar()
        self._set_sidebar_tooltips()
        # pylint: disable-next=no-member
        self.ui.theme_toggle.toggled.connect(self._apply_theme)
        self._apply_theme(self.ui.theme_toggle.isChecked())
        self._build_tabs()
        self._connect_signals()
        self._on_top_period_changed(self.top_tab.top_period.currentText())
        self.ui.sidebar_list.setCurrentRow(0)
        app = cast(QApplication | None, QApplication.instance())
        if app:
            app.installEventFilter(window)

    def _build_status_bar(self) -> None:
        self.role_status = QLabel("Role: Initializing...")
        self.sync_status = QLabel("Sync: Initializing...")
        self.background_progress = QProgressBar()
        self.background_progress.setObjectName("background_progress")
        self.background_progress.setRange(0, 0)
        self.background_progress.setTextVisible(False)
        self.background_progress.setMaximumWidth(120)
        self.background_progress.setVisible(False)
        self.cancel_background_btn = QPushButton("Cancel")
        self.cancel_background_btn.setObjectName("cancel_background_btn")
        self.cancel_background_btn.setToolTip(
            "Cancel after the current network request or local write finishes"
        )
        self.cancel_background_btn.setVisible(False)
        self.conflicts_btn = QPushButton("Conflicts (0)")
        self.conflicts_btn.setObjectName("conflicts_btn")
        self.conflicts_btn.setEnabled(False)
        self.conflicts_btn.setToolTip("Review synchronization conflicts")
        for widget in (
            self.role_status,
            self.sync_status,
            self.background_progress,
            self.cancel_background_btn,
            self.conflicts_btn,
        ):
            self.ui.statusbar.addPermanentWidget(widget)

    def _set_sidebar_tooltips(self) -> None:
        self.project_list.setToolTip("Select a project to load its data")
        self.sync_btn.setToolTip(
            "Manually synchronize local offline changes with the server"
        )
        self.new_project_btn.setToolTip("Create a new project")
        self.delete_project_btn.setToolTip(
            "Permanently delete the selected project (superadmin only)"
        )
        self.ui.theme_toggle.setToolTip("Toggle between Dark Mode and Light Mode")
        self.ui.sidebar_list.setToolTip(
            "Navigate between different views and tools for the current project"
        )

    def _apply_theme(self, is_dark: bool) -> None:
        theme = "dark" if is_dark else "light"
        bg_color = "#1e1e1e" if is_dark else "#ffffff"
        text_color = "#e0e0e0" if is_dark else "#000000"
        extra_css = f"""
            QMainWindow, QWidget, QDialog, QStackedWidget, QTabWidget::pane,
            QGroupBox, QScrollArea {{
                background-color: {bg_color};
                color: {text_color};
            }}
            QTextEdit, QPlainTextEdit, QLineEdit, QSpinBox, QComboBox, QDateTimeEdit {{
                background-color: {bg_color};
                border: 1px solid rgba(128, 128, 128, 0.3);
                border-radius: 4px;
            }}
            QTextEdit, QPlainTextEdit {{
                padding: 4px;
            }}
            """
        try:
            qdarktheme.setup_theme(theme, additional_qss=extra_css)
        except AttributeError:
            app = cast(QApplication | None, QApplication.instance())
            if app:
                app.setStyleSheet(qdarktheme.load_stylesheet(theme) + extra_css)
        _set_titlebar_dark(cast(QMainWindow, self), is_dark)

    def _build_tabs(self) -> None:
        stack = self.ui.main_stacked_widget
        while stack.count() > 0:  # drop the placeholder pages from the .ui file
            widget = stack.widget(0)
            if widget is None:
                break
            stack.removeWidget(widget)
            widget.deleteLater()
        self.risks_tab = RisksTab(
            on_export_csv=self._export_risks_csv,
            on_refresh=lambda: self._refresh_risks(select_id=self.current_risk_id),
            on_risk_clicked=self._on_risk_clicked,
            on_new_risk=self._start_new_risk,
            on_save_risk=self._save_risk,
            on_delete_item=self._delete_risk,
            on_mark_dirty=self._mark_editor_dirty,
        )
        self.opps_tab = OpportunitiesTab(
            on_export_csv=self._export_opportunities_csv,
            on_refresh=lambda: self._refresh_opportunities(
                select_id=self.current_opportunity_id
            ),
            on_opportunity_clicked=self._on_opportunity_clicked,
            on_new_opportunity=self._start_new_opportunity,
            on_save_opportunity=self._save_opportunity,
            on_delete_item=self._delete_opportunity,
            on_mark_dirty=self._mark_opp_editor_dirty,
        )
        self.matrix_tab = MatrixTab(on_kind_changed=self._on_matrix_kind_changed)
        self.top_tab = TopHistoryTab(
            on_snapshot_now=self._snapshot_now,
            on_refresh_history=self._refresh_top_history,
            on_period_changed=self._on_top_period_changed,
            on_maybe_auto_snapshot=self._maybe_auto_snapshot,
        )
        self.actions_tab = ActionsTab(
            on_action_clicked=self._on_action_clicked,
            on_save_action=self._save_action,
            on_new_action=self._start_new_action,
            on_target_type_changed=lambda _: self._toggle_action_target_inputs(),
        )
        self.assessments_tab = AssessmentsTab(on_save_assessment=self._save_assessment)
        self.members_tab = MembersTab(
            on_add_or_update_member=self._add_or_update_member,
            on_remove_selected_member=self._remove_selected_member,
            on_refresh_members=self._refresh_members,
            on_member_selected=self._on_member_selected,
        )
        self.helpdesk_tab = HelpDeskTab(
            on_ticket_clicked=self._on_helpdesk_ticket_clicked,
            on_new_ticket=self._start_new_helpdesk_ticket,
            on_save_ticket=self._save_helpdesk_ticket,
            on_delete_ticket=self._delete_helpdesk_ticket,
            on_refresh=self._refresh_helpdesk,
            on_filter_changed=self._apply_helpdesk_filters,
        )
        self.ui.sidebar_list.clear()

        for label, tab in (
            ("Risks", self.risks_tab),
            ("Opportunities", self.opps_tab),
            ("Matrix", self.matrix_tab),
            ("Top history", self.top_tab),
            ("Actions", self.actions_tab),
            ("Assessments", self.assessments_tab),
            ("Members", self.members_tab),
            ("Help Desk", self.helpdesk_tab),
        ):
            stack.addWidget(tab)
            self.ui.sidebar_list.addItem(label)
        self.risks_table = self.risks_tab.table
        self.risk_form = self.risks_tab.form
        self.new_risk_btn = self.risks_tab.new_btn
        self.editor_label = self.risks_tab.editor_label
        self.opps_table = self.opps_tab.table
        self.opp_form = self.opps_tab.form
        self.new_opp_btn = self.opps_tab.new_btn
        self.opp_editor_label = self.opps_tab.editor_label
        self.risks_matrix_table = self.matrix_tab.risks_matrix_table
        self.opps_matrix_table = self.matrix_tab.opps_matrix_table

    def _connect_signals(self) -> None:

        # PySide signals are runtime descriptors and are invisible to Pylint.
        # pylint: disable=no-member
        self.project_list.itemSelectionChanged.connect(self._on_project_selected)
        self.ui.sidebar_list.currentRowChanged.connect(
            self.ui.main_stacked_widget.setCurrentIndex
        )
        self.sync_btn.clicked.connect(self._sync_now)
        self.cancel_background_btn.clicked.connect(self._cancel_background_job)
        self.conflicts_btn.clicked.connect(self._open_conflict_center)
        self.new_project_btn.clicked.connect(self._create_new_project)
        self.delete_project_btn.clicked.connect(self._delete_current_project)
        # pylint: enable=no-member
