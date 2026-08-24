"""Headless interaction tests for the PySide6 desktop interface."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QDialog, QLineEdit, QMessageBox, QTableWidget
from riskapp_client.domain.domain_models import Member, Risk
from riskapp_client.ui_v2.components.custom_gui_widgets import (
    LoginDialog,
    NewProjectDialog,
    RegisterDialog,
    RiskForm,
    ServerDownDialog,
    setup_readonly_table,
)
from riskapp_client.ui_v2.main_application_window import MainWindow
from riskapp_client.ui_v2.tabs.actions_tab import ActionsTab
from riskapp_client.ui_v2.tabs.assessments_tab import AssessmentsTab
from riskapp_client.ui_v2.tabs.helpdesk_tab import HelpDeskTab
from riskapp_client.ui_v2.tabs.matrix_tab import MatrixTab
from riskapp_client.ui_v2.tabs.members_tab import MembersTab
from riskapp_client.ui_v2.tabs.opportunities_tab import OpportunitiesTab
from riskapp_client.ui_v2.tabs.risks_tab import RisksTab
from riskapp_client.ui_v2.tabs.top_history_tab import TopHistoryTab


def test_login_and_server_down_dialog_choices(qtbot) -> None:
    login = LoginDialog(
        default_url="https://api.example.test", cached_email="cached@example.test"
    )
    qtbot.addWidget(login)
    login.ui.password.setText("secret")
    assert login.values() == (
        "https://api.example.test",
        "cached@example.test",
        "secret",
    )
    login._on_register_clicked()
    assert login.wants_register is True

    local_login = LoginDialog()
    qtbot.addWidget(local_login)
    local_login._on_local_clicked()
    assert local_login.wants_local is True

    down = ServerDownDialog(
        "connection refused", has_credentials=True, email="cached@example.test"
    )
    qtbot.addWidget(down)
    down._choose_with_account()
    assert down.result() == QDialog.Accepted
    assert down.choice == ServerDownDialog.OFFLINE_WITH_ACCOUNT

    anonymous = ServerDownDialog("offline")
    qtbot.addWidget(anonymous)
    anonymous._choose_fully_local()
    assert anonymous.choice == ServerDownDialog.FULLY_LOCAL


@pytest.mark.parametrize(
    ("password", "message"),
    [
        ("short", "at least 12"),
        ("lowercaseonly1!", "uppercase"),
        ("UPPERCASEONLY1!", "lowercase"),
        ("NoDigitsHere!", "digit"),
        ("NoSymbolsHere1", "symbol"),
        ("A" * 129 + "a1!", "at most 128"),
    ],
)
def test_registration_password_policy(password, message) -> None:
    assert any(
        message in issue for issue in RegisterDialog._check_password_policy(password)
    )
    assert RegisterDialog._check_password_policy("StrongPassword1!") == []


def test_registration_dialog_validates_each_field(monkeypatch, qtbot) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, message, *_args: warnings.append(message),
    )
    dialog = RegisterDialog(default_url="https://api.example.test")
    qtbot.addWidget(dialog)

    dialog._validate_and_accept()
    assert warnings[-1] == "Email is required."
    dialog.ui.email.setText("invalid")
    dialog._validate_and_accept()
    assert "valid email" in warnings[-1]
    dialog.ui.email.setText("new@example.test")
    dialog._validate_and_accept()
    assert warnings[-1] == "Password is required."
    dialog.ui.password.setText("StrongPassword1!")
    dialog.ui.confirm_password.setText("different")
    dialog._validate_and_accept()
    assert warnings[-1] == "Passwords do not match."
    dialog.ui.confirm_password.setText("short")
    dialog.ui.password.setText("short")
    dialog._validate_and_accept()
    assert "at least 12" in warnings[-1]

    dialog.ui.password.setText("StrongPassword1!")
    dialog.ui.confirm_password.setText("StrongPassword1!")
    assert dialog.values()[0] == "https://api.example.test"
    dialog._validate_and_accept()
    assert dialog.result() == QDialog.Accepted


def test_new_project_dialog_requires_a_name(monkeypatch, qtbot) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, message, *_args: warnings.append(message),
    )
    dialog = NewProjectDialog()
    qtbot.addWidget(dialog)
    dialog._validate_and_accept()
    assert warnings == ["Project name is required."]

    dialog.name_edit.setText("  Migration  ")
    dialog.desc_edit.setPlainText("  Move the system  ")
    assert dialog.values() == ("Migration", "Move the system")
    dialog._validate_and_accept()
    assert dialog.result() == QDialog.Accepted


def test_risk_form_round_trips_values_permissions_and_members(qtbot) -> None:
    submitted: list[dict] = []
    dirty = Mock()
    form = RiskForm(on_submit=submitted.append)
    qtbot.addWidget(form)
    form.track_dirty_state(dirty)
    form.set_members(
        [
            Member("user-1", "one@example.test", "member"),
            {"user_id": "user-2", "email": "two@example.test", "role": "manager"},
            {"email": "missing-id@example.test"},
            object(),
        ]
    )
    assert form.owner_user_id.count() == 3

    form.set_values(
        title="  Major risk  ",
        probability=4,
        impact=2,
        impact_cost=2,
        impact_time=5,
        impact_scope=3,
        impact_quality=1,
        code="R-1",
        description=" Description ",
        owner_user_id="user-2",
        status="active",
        identified_at="2026-02-03T04:05:06",
        response_at=None,
    )
    payload = form.get_payload()
    assert payload["title"] == "Major risk"
    assert payload["owner_user_id"] == "user-2"
    assert payload["impact"] == 5
    assert payload["identified_at"].startswith("2026-02-03T04:05:06")
    assert payload["response_at"] is None

    form.set_allow_deleted_status(False)
    assert form.status.findText("deleted") == -1
    form.set_allow_deleted_status(False)
    form.set_allow_deleted_status(True)
    assert form.status.findText("deleted") >= 0

    form.set_editable(False)
    assert form.btn.isEnabled() is False
    assert form.title.isReadOnly() is True
    form.set_editable(True)
    assert form.btn.isEnabled() is True

    form.title.setText("Changed title")
    assert dirty.called
    form._submit()
    assert submitted[-1]["title"] == "Changed title"

    fallback_date = QLineEdit()
    fallback_date.setText(" 2026-01-01 ")
    assert form._read_date(fallback_date) == "2026-01-01"
    form._set_date(fallback_date, None)
    assert fallback_date.text() == ""


def test_risk_form_rejects_missing_title(monkeypatch, qtbot) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, message, *_args: warnings.append(message),
    )
    submitted = Mock()
    form = RiskForm(on_submit=submitted)
    qtbot.addWidget(form)
    form.title.clear()
    form._submit()
    assert warnings == ["Title is required."]
    submitted.assert_not_called()


def test_readonly_table_setup_configures_selection_and_delegate(qtbot) -> None:
    table = QTableWidget(1, 2)
    qtbot.addWidget(table)
    setup_readonly_table(table, excel_delegate=True)
    assert table.editTriggers() == table.EditTrigger.NoEditTriggers
    assert table.selectionBehavior() == table.SelectionBehavior.SelectRows
    assert table.itemDelegate() is not None


def test_main_window_builds_all_views_and_common_gui_helpers(monkeypatch, qtbot) -> None:
    class EmptyBackend:
        def list_projects(self):
            return []

    critical: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda _parent, _title, message, *_args: critical.append(message),
    )
    window = MainWindow(EmptyBackend())
    qtbot.addWidget(window)
    window.top_tab.auto_snap_timer.stop()

    assert window.windowTitle() == "RiskApp"
    assert window.ui.main_stacked_widget.count() == 8
    assert window.ui.sidebar_list.count() == 8
    assert window.risk_form.btn.text() == "Save Risk"
    assert window.opp_form.btn.text() == "Save Opportunity"

    item = window._mk_item("Risk", entity_id="risk-1", align_center=True)
    window.risks_table.setRowCount(1)
    window.risks_table.setItem(0, 0, item)
    window._select_row_by_entity_id("risk-1", table=window.risks_table)
    assert window.risks_table.currentRow() == 0
    window._select_row_by_entity_id(None, table=window.risks_table)

    assert window._call_backend("Failure", lambda: 42) == 42
    assert window._call_backend("Failure", Mock(side_effect=RuntimeError("boom"))) is None
    assert critical == ["boom"]

    window._update_scored_filter_report(window.filter_report, 0, [])
    assert window.filter_report.text() == "Showing 0/0"
    scored = [
        Risk(
            id="r1",
            project_id="p1",
            title="A",
            probability=2,
            impact=3,
            category="ops",
            status="active",
        )
    ]
    window._update_scored_filter_report(window.filter_report, 2, scored)
    assert "Showing 1/2" in window.filter_report.text()
    window._update_scored_filter_report(
        window.filter_report,
        2,
        scored,
        server_report={
            "total": 1,
            "project_total": 2,
            "min_score": 6,
            "max_score": 6,
            "avg_score": 6,
            "status_counts": {"active": 1},
            "category_counts": {"ops": 1},
        },
    )
    assert "Server 1/2" in window.filter_report.text()


def test_tab_widgets_wire_callbacks_filters_and_visibility(qtbot) -> None:
    action_clicked = Mock()
    action_save = Mock()
    action_new = Mock()
    target_changed = Mock()
    actions = ActionsTab(
        on_action_clicked=action_clicked,
        on_save_action=action_save,
        on_new_action=action_new,
        on_target_type_changed=target_changed,
    )
    qtbot.addWidget(actions)
    actions.action_save_btn.click()
    actions.action_new_btn.click()
    actions.action_target_type.setCurrentText("opportunity")
    action_save.assert_called_once()
    action_new.assert_called_once()
    target_changed.assert_called_with("opportunity")

    assessment_save = Mock()
    assessments = AssessmentsTab(on_save_assessment=assessment_save)
    qtbot.addWidget(assessments)
    assessments.assess_save_btn.click()
    assessment_save.assert_called_once()

    callbacks = [Mock() for _ in range(6)]
    helpdesk = HelpDeskTab(
        on_ticket_clicked=Mock(),
        on_new_ticket=callbacks[0],
        on_save_ticket=callbacks[1],
        on_delete_ticket=callbacks[2],
        on_refresh=callbacks[3],
        on_filter_changed=callbacks[4],
    )
    qtbot.addWidget(helpdesk)
    helpdesk.new_btn.click()
    helpdesk.save_btn.click()
    helpdesk.delete_btn.click()
    helpdesk.refresh_btn.click()
    helpdesk.filter_status.setCurrentText("open")
    for callback in callbacks[:5]:
        assert callback.called
    assert helpdesk.tickets_table.isColumnHidden(6)

    kind_changed = Mock()
    matrix = MatrixTab(on_kind_changed=kind_changed)
    qtbot.addWidget(matrix)
    matrix.set_kind("opportunities")
    assert matrix.risks_matrix_table.isHidden()
    assert not matrix.opps_matrix_table.isHidden()
    matrix.set_kind("both")
    assert not matrix.risks_matrix_table.isHidden()
    matrix.set_kind("unexpected")
    assert matrix.opps_matrix_table.isHidden()
    matrix.kind_combo.setCurrentText("Both")
    assert kind_changed.called

    member_callbacks = [Mock() for _ in range(4)]
    members = MembersTab(
        on_add_or_update_member=member_callbacks[0],
        on_remove_selected_member=member_callbacks[1],
        on_refresh_members=member_callbacks[2],
        on_member_selected=member_callbacks[3],
    )
    qtbot.addWidget(members)
    members.member_add_btn.click()
    members.member_remove_btn.click()
    members.member_refresh_btn.click()
    for callback in member_callbacks[:3]:
        callback.assert_called_once()


def test_scored_tabs_and_history_reset_state_and_emit_callbacks(qtbot) -> None:
    refresh = Mock()
    exported = Mock()
    new_item = Mock()
    saved = Mock()
    deleted = Mock()
    dirty = Mock()
    risk_tab = RisksTab(
        on_export_csv=exported,
        on_refresh=refresh,
        on_risk_clicked=Mock(),
        on_new_risk=new_item,
        on_save_risk=saved,
        on_delete_item=deleted,
        on_mark_dirty=dirty,
        on_fit_table_card=Mock(),
    )
    qtbot.addWidget(risk_tab)
    risk_tab.filter_search.setText("needle")
    assert refresh.called
    refresh.reset_mock()
    risk_tab.clear_filters()
    refresh.assert_called_once()
    assert risk_tab.filter_search.text() == ""
    assert risk_tab.filter_max_score.value() == risk_tab.filter_max_score.maximum()

    risk_tab.set_owner_filter_members(
        [
            Member("u2", "z@example.test", "member"),
            Member("u1", "a@example.test", "manager"),
        ]
    )
    assert risk_tab.filter_owner.itemText(2) == "a@example.test"
    risk_tab.filter_owner.setCurrentIndex(2)
    risk_tab.set_owner_filter_members(
        [
            Member("u1", "a@example.test", "manager"),
            Member("u2", "z@example.test", "member"),
        ]
    )
    assert risk_tab.filter_owner.currentData() == "u1"
    risk_tab.set_owner_filter_members([SimpleNamespace()])

    opportunity_tab = OpportunitiesTab(
        on_export_csv=Mock(),
        on_refresh=Mock(),
        on_opportunity_clicked=Mock(),
        on_new_opportunity=Mock(),
        on_save_opportunity=Mock(),
        on_delete_item=Mock(),
        on_mark_dirty=Mock(),
    )
    qtbot.addWidget(opportunity_tab)
    assert opportunity_tab.form.btn.text() == "Save Opportunity"

    snapshot = Mock()
    history_refresh = Mock()
    period_changed = Mock()
    auto_snapshot = Mock()
    history = TopHistoryTab(
        on_snapshot_now=snapshot,
        on_refresh_history=history_refresh,
        on_period_changed=period_changed,
        on_maybe_auto_snapshot=auto_snapshot,
    )
    qtbot.addWidget(history)
    history.auto_snap_timer.stop()
    history.snapshot_btn.click()
    history.refresh_top_btn.click()
    history.top_period.setCurrentIndex(1)
    snapshot.assert_called_once()
    history_refresh.assert_called_once()
    assert period_changed.called
