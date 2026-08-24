"""MainWindow UI construction."""

from __future__ import annotations

import logging
import sys

import qdarktheme
from PySide6.QtWidgets import QApplication, QLabel
from riskapp_client.ui_v2.tabs.actions_tab import ActionsTab
from riskapp_client.ui_v2.tabs.assessments_tab import AssessmentsTab
from riskapp_client.ui_v2.tabs.helpdesk_tab import HelpDeskTab
from riskapp_client.ui_v2.tabs.matrix_tab import MatrixTab
from riskapp_client.ui_v2.tabs.members_tab import MembersTab
from riskapp_client.ui_v2.tabs.opportunities_tab import OpportunitiesTab
from riskapp_client.ui_v2.tabs.risks_tab import RisksTab
from riskapp_client.ui_v2.tabs.top_history_tab import TopHistoryTab
from riskapp_client.ui_v2.ui_main_window_design import Ui_MainWindow

logger = logging.getLogger(__name__)

_RISKS_ALIASES = (
    "filter_search",
    "filter_min_score",
    "filter_max_score",
    "filter_report",
    "filter_status",
    "filter_category",
    "filter_owner",
    "filter_from",
    "filter_to",
)

_OPPS_ALIASES = (
    "opp_filter_search",
    "opp_filter_min_score",
    "opp_filter_max_score",
    "opp_filter_status",
    "opp_filter_category",
    "opp_filter_owner",
    "opp_filter_from",
    "opp_filter_to",
    "opp_filter_report",
)


def _set_titlebar_dark(window, dark: bool) -> None:
    """Set the title bar to dark or light mode."""
    # Qt 6.5+ color scheme API
    try:
        from PySide6.QtCore import Qt as QtCore_Qt
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app and hasattr(app, "styleHints"):
            hints = app.styleHints()
            if hasattr(hints, "setColorScheme"):
                scheme = QtCore_Qt.ColorScheme.Dark if dark else QtCore_Qt.ColorScheme.Light
                hints.setColorScheme(scheme)
                return
    except (AttributeError, ImportError, RuntimeError):
        logger.debug("Qt ColorScheme API unavailable", exc_info=True)

    # Windows DWM API
    try:
        if sys.platform == "win32":
            import ctypes
            hwnd = int(window.winId())
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            value = ctypes.c_int(1 if dark else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                ctypes.byref(value), ctypes.sizeof(value),
            )
            return
    except (AttributeError, ImportError, OSError):
        logger.debug("DWM title bar API unavailable", exc_info=True)


class LayoutMixin:
    """Build the main window UI."""

    def _build_ui(self) -> None:
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.setWindowTitle("RiskApp")
        self.project_list = self.ui.project_list
        self.sync_btn = self.ui.sync_btn
        self.new_project_btn = self.ui.new_project_btn
        self.delete_project_btn = self.ui.delete_project_btn
        self.role_status = QLabel("Role: Initializing...")
        self.sync_status = QLabel("Sync: Initializing...")
        self.ui.statusbar.addPermanentWidget(self.role_status)
        self.ui.statusbar.addPermanentWidget(self.sync_status)
        self.project_list.setToolTip("Select a project to load its data")
        self.sync_btn.setToolTip(
            "Manually synchronize local offline changes with the server"
        )
        self.new_project_btn.setToolTip("Create a new project")
        self.delete_project_btn.setToolTip("Permanently delete the selected project (superadmin only)")
        self.ui.theme_toggle.setToolTip("Toggle between Dark Mode and Light Mode")
        self.ui.sidebar_list.setToolTip(
            "Navigate between different views and tools for the current project"
        )

        def apply_theme(is_dark: bool):
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
                app = QApplication.instance()
                if app:
                    app.setStyleSheet(qdarktheme.load_stylesheet(theme) + extra_css)
            _set_titlebar_dark(self, is_dark)

        self.ui.theme_toggle.toggled.connect(apply_theme)
        apply_theme(self.ui.theme_toggle.isChecked())

        def bind(src: object, names: tuple[str, ...], **renamed: str) -> None:
            """Bind item."""
            for name in names:
                setattr(self, name, getattr(src, name))
            for dst, src_name in renamed.items():
                setattr(self, dst, getattr(src, src_name))

        while self.ui.main_stacked_widget.count() > 0:
            widget = self.ui.main_stacked_widget.widget(0)
            self.ui.main_stacked_widget.removeWidget(widget)
            widget.deleteLater()
        self.risks_tab = RisksTab(
            on_export_csv=self._export_risks_csv,
            on_refresh=lambda: self._refresh_risks(select_id=self.current_risk_id),
            on_risk_clicked=self._on_risk_clicked,
            on_new_risk=self._start_new_risk,
            on_save_risk=self._save_risk,
            on_delete_item=lambda: self._delete_entity(
                self.current_risk_id,
                self.backend.delete_risk,
                self._refresh_risks,
                self._start_new_risk,
            ),
            on_mark_dirty=self._mark_editor_dirty,
            on_fit_table_card=lambda: self._fit_table_card(),
        )
        self.ui.main_stacked_widget.addWidget(self.risks_tab)
        bind(
            self.risks_tab,
            _RISKS_ALIASES,
            risks_table="table",
            risk_form="form",
            new_risk_btn="new_btn",
            editor_label="editor_label",
            _table_card="table_card",
            _editor_card="editor_card",
        )
        self.opps_tab = OpportunitiesTab(
            on_export_csv=self._export_opportunities_csv,
            on_refresh=lambda: self._refresh_opportunities(
                select_id=self.current_opportunity_id
            ),
            on_opportunity_clicked=self._on_opportunity_clicked,
            on_new_opportunity=self._start_new_opportunity,
            on_save_opportunity=self._save_opportunity,
            on_delete_item=lambda: self._delete_entity(
                self.current_opportunity_id,
                self.backend.delete_opportunity,
                self._refresh_opportunities,
                self._start_new_opportunity,
            ),
            on_mark_dirty=self._mark_opp_editor_dirty,
        )
        self.ui.main_stacked_widget.addWidget(self.opps_tab)
        bind(
            self.opps_tab,
            _OPPS_ALIASES,
            opps_table="table",
            opp_form="form",
            new_opp_btn="new_btn",
            opp_editor_label="editor_label",
            _opp_editor_card="editor_card",
        )
        self.matrix_tab = MatrixTab(on_kind_changed=self._on_matrix_kind_changed)
        self.ui.main_stacked_widget.addWidget(self.matrix_tab)
        self.risks_matrix_table = self.matrix_tab.risks_matrix_table
        self.opps_matrix_table = self.matrix_tab.opps_matrix_table
        self.top_tab = TopHistoryTab(
            on_snapshot_now=self._snapshot_now,
            on_refresh_history=self._refresh_top_history,
            on_period_changed=self._on_top_period_changed,
            on_maybe_auto_snapshot=self._maybe_auto_snapshot,
        )
        self.ui.main_stacked_widget.addWidget(self.top_tab)
        self.actions_tab = ActionsTab(
            on_action_clicked=self._on_action_clicked,
            on_save_action=self._save_action,
            on_new_action=self._start_new_action,
            on_target_type_changed=lambda _: self._toggle_action_target_inputs(),
        )
        self.ui.main_stacked_widget.addWidget(self.actions_tab)
        self.assessments_tab = AssessmentsTab(on_save_assessment=self._save_assessment)
        self.ui.main_stacked_widget.addWidget(self.assessments_tab)
        self.members_tab = MembersTab(
            on_add_or_update_member=self._add_or_update_member,
            on_remove_selected_member=self._remove_selected_member,
            on_refresh_members=self._refresh_members,
            on_member_selected=self._on_member_selected,
        )
        self.ui.main_stacked_widget.addWidget(self.members_tab)
        self.helpdesk_tab = HelpDeskTab(
            on_ticket_clicked=self._on_helpdesk_ticket_clicked,
            on_new_ticket=self._start_new_helpdesk_ticket,
            on_save_ticket=self._save_helpdesk_ticket,
            on_delete_ticket=self._delete_helpdesk_ticket,
            on_refresh=self._refresh_helpdesk,
            on_filter_changed=self._apply_helpdesk_filters,
        )
        self.ui.main_stacked_widget.addWidget(self.helpdesk_tab)
        self.ui.sidebar_list.clear()
        self.ui.sidebar_list.addItems(
            [
                "Risks",
                "Opportunities",
                "Matrix",
                "Top history",
                "Actions",
                "Assessments",
                "Members",
                "Help Desk",
            ]
        )
        self.project_list.itemSelectionChanged.connect(self._on_project_selected)
        self.ui.sidebar_list.currentRowChanged.connect(
            self.ui.main_stacked_widget.setCurrentIndex
        )
        self.sync_btn.clicked.connect(self._sync_now)
        self.new_project_btn.clicked.connect(self._create_new_project)
        self.delete_project_btn.clicked.connect(self._delete_current_project)
        if hasattr(self.top_tab, "top_period"):
            self._on_top_period_changed(self.top_tab.top_period.currentText())
        self.ui.sidebar_list.setCurrentRow(0)
        app = QApplication.instance()
        if app:
            app.installEventFilter(self)
