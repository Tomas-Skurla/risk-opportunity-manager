"""Behavior-focused coverage for the real main-window mixins."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtWidgets import QFileDialog, QLineEdit, QMessageBox, QWidget
from riskapp_client.domain.domain_models import (
    Action,
    Assessment,
    HelpDeskTicket,
    Member,
    Opportunity,
    Project,
    Risk,
)
from riskapp_client.ui_v2.main_application_window import MainWindow


class FakeStore:
    def __init__(self, project: Project) -> None:
        self.project = project

    @staticmethod
    def get_meta(key: str):
        return {
            "last_email": "manager@example.test",
            "user_id": "user-1",
        }.get(key)

    def get_project(self, _project_id: str) -> Project:
        return self.project


class GuiBackend:
    """In-memory backend implementing every main-window feature."""

    def __init__(self) -> None:
        self.project = Project("project-1", "Interview", created_by="user-1")
        self.store = FakeStore(self.project)
        self.remote = SimpleNamespace(email="manager@example.test")
        self.superuser = False
        self.calls: list[tuple] = []
        self.risks = [
            Risk(
                "risk-1",
                "project-1",
                title="Outage",
                probability=4,
                impact=5,
                category="operations",
                status="active",
                owner_user_id="user-1",
                identified_at="2026-01-02T03:04:05",
            ),
            Risk(
                "risk-2",
                "project-1",
                title="Delay",
                probability=2,
                impact=2,
                status="concept",
            ),
        ]
        self.opportunities = [
            Opportunity(
                "opp-1",
                "project-1",
                title="Automation",
                probability=3,
                impact=4,
                status="active",
            )
        ]
        self.actions = [
            Action(
                "action-1",
                "project-1",
                "risk-1",
                None,
                "mitigation",
                "Fail over",
                status="open",
            ),
            Action(
                "action-2",
                "project-1",
                None,
                "opp-1",
                "exploit",
                "Pilot",
                status="doing",
            ),
        ]
        self.assessments = [
            Assessment("assessment-1", "risk-1", "user-1", 4, 5, "reviewed")
        ]
        self.members = [
            Member("user-1", "manager@example.test", "manager"),
            Member("user-2", "member@example.test", "member"),
        ]
        self.tickets = [
            HelpDeskTicket(
                "ticket-1",
                "project-1",
                "Cannot export",
                "CSV button is disabled",
                "bug",
                "high",
                "open",
                "manager@example.test",
                "2026-01-02T03:04:05",
            ),
            HelpDeskTicket(
                "ticket-2",
                "project-1",
                "Access request",
                category="access",
                priority="low",
                status="closed",
            ),
        ]

    def list_projects(self):
        return [self.project]

    def current_user_id(self):
        return "user-1"

    def is_superuser(self):
        return self.superuser

    def list_risks(self, _project_id):
        return list(self.risks)

    def risks_report(self, _project_id, **_filters):
        return {
            "total": len(self.risks),
            "project_total": len(self.risks),
            "min_score": 4,
            "max_score": 20,
            "avg_score": 12,
            "status_counts": {"active": 1, "concept": 1},
            "category_counts": {"operations": 1},
        }

    def create_risk(self, project_id, **values):
        risk = Risk(f"risk-{len(self.risks) + 1}", project_id, **values)
        self.risks.append(risk)
        self.calls.append(("create_risk", risk.id))
        return risk

    def update_risk(self, project_id, risk_id, **values):
        risk = Risk(risk_id, project_id, **values)
        self.risks = [risk if item.id == risk_id else item for item in self.risks]
        self.calls.append(("update_risk", risk_id))
        return risk

    def delete_risk(self, _project_id, risk_id):
        self.risks = [item for item in self.risks if item.id != risk_id]
        self.calls.append(("delete_risk", risk_id))

    def list_opportunities(self, _project_id):
        return list(self.opportunities)

    def opportunities_report(self, _project_id, **_filters):
        return {
            "total": 1,
            "project_total": 1,
            "min_score": 12,
            "max_score": 12,
            "avg_score": 12,
            "status_counts": {"active": 1},
            "category_counts": {},
        }

    def create_opportunity(self, project_id, **values):
        opportunity = Opportunity(
            f"opp-{len(self.opportunities) + 1}", project_id, **values
        )
        self.opportunities.append(opportunity)
        self.calls.append(("create_opportunity", opportunity.id))
        return opportunity

    def update_opportunity(self, project_id, opportunity_id, **values):
        opportunity = Opportunity(opportunity_id, project_id, **values)
        self.opportunities = [
            opportunity if item.id == opportunity_id else item
            for item in self.opportunities
        ]
        self.calls.append(("update_opportunity", opportunity_id))
        return opportunity

    def delete_opportunity(self, _project_id, opportunity_id):
        self.opportunities = [
            item for item in self.opportunities if item.id != opportunity_id
        ]
        self.calls.append(("delete_opportunity", opportunity_id))

    def list_actions(self, _project_id):
        return list(self.actions)

    def create_action(self, project_id, **values):
        target_type = values.pop("target_type")
        target_id = values.pop("target_id")
        action = Action(
            f"action-{len(self.actions) + 1}",
            project_id,
            target_id if target_type == "risk" else None,
            target_id if target_type == "opportunity" else None,
            **values,
        )
        self.actions.append(action)
        self.calls.append(("create_action", action.id))
        return action

    def update_action(self, project_id, action_id, **values):
        target_type = values.pop("target_type")
        target_id = values.pop("target_id")
        action = Action(
            action_id,
            project_id,
            target_id if target_type == "risk" else None,
            target_id if target_type == "opportunity" else None,
            **values,
        )
        self.actions = [
            action if item.id == action_id else item for item in self.actions
        ]
        self.calls.append(("update_action", action_id))
        return action

    def list_assessments(self, _project_id, _item_type, item_id):
        return [item for item in self.assessments if item.item_id == item_id]

    def upsert_my_assessment(
        self, _project_id, _item_type, item_id, probability, impact, notes
    ):
        assessment = Assessment(
            "assessment-new", item_id, "user-1", probability, impact, notes
        )
        self.assessments = [assessment]
        self.calls.append(("assessment", item_id))
        return assessment

    def list_members(self, _project_id):
        return list(self.members)

    def add_member(self, _project_id, **values):
        self.calls.append(("add_member", values["user_email"]))

    def remove_member(self, _project_id, **values):
        self.calls.append(("remove_member", values["member_user_id"]))

    def list_helpdesk_tickets(self, _project_id):
        return list(self.tickets)

    def create_helpdesk_ticket(self, project_id, **values):
        ticket = HelpDeskTicket(f"ticket-{len(self.tickets) + 1}", project_id, **values)
        self.tickets.append(ticket)
        self.calls.append(("create_ticket", ticket.id))
        return ticket

    def update_helpdesk_ticket(self, ticket_id, **values):
        old = next(ticket for ticket in self.tickets if ticket.id == ticket_id)
        ticket = HelpDeskTicket(
            old.id,
            old.project_id,
            values.get("title") or old.title,
            values.get("description") or old.description,
            values.get("category") or old.category,
            values.get("priority") or old.priority,
            values.get("status") or old.status,
            old.reporter_email,
            old.created_at,
        )
        self.tickets = [
            ticket if item.id == ticket_id else item for item in self.tickets
        ]
        self.calls.append(("update_ticket", ticket_id))
        return ticket

    def delete_helpdesk_ticket(self, ticket_id):
        self.tickets = [ticket for ticket in self.tickets if ticket.id != ticket_id]
        self.calls.append(("delete_ticket", ticket_id))

    @staticmethod
    def pending_count(_project_id=None):
        return 2

    @staticmethod
    def blocked_count(_project_id=None):
        return 1

    @staticmethod
    def can_sync():
        return True

    def sync_project(self, _project_id):
        return {
            "pushed": 2,
            "conflicts": 0,
            "errors": 0,
            "blocked": 0,
            "pulled_risks": 2,
        }

    def create_snapshot(self, project_id, *, kind=None):
        self.calls.append(("snapshot", project_id, kind))
        return {"id": "snapshot-1"}

    @staticmethod
    def top_history(_project_id, **_filters):
        return [
            {
                "captured_at": "2026-01-02T03:04:05",
                "top": [
                    {
                        "title": "Outage",
                        "probability": 4,
                        "impact": 5,
                        "score": 20,
                    },
                    {
                        "title": "Delay",
                        "probability": 2,
                        "impact": 2,
                        "score": 4,
                    },
                ],
            }
        ]

    def create_project(self, *, name, description):
        self.project = Project("project-2", name, description, "user-1")
        self.store.project = self.project
        return self.project

    def delete_project(self, project_id):
        self.calls.append(("delete_project", project_id))


def _window(qtbot):
    backend = GuiBackend()
    window = MainWindow(backend)
    qtbot.addWidget(window)
    window.top_tab.auto_snap_timer.stop()
    return window, backend


def test_real_window_risk_and_opportunity_crud(monkeypatch, qtbot) -> None:
    window, backend = _window(qtbot)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, message, *_args: warnings.append(message),
    )

    assert window.risks_table.rowCount() == 2
    window._on_risk_clicked(0, 1)
    assert window.current_risk_id == "risk-1"
    assert window.risk_form.title.text() == "Outage"

    window.risk_form.title.setText("Updated outage")
    window._editor_dirty = True
    window._commit_editor_changes(refresh=True)
    assert ("update_risk", "risk-1") in backend.calls
    assert window._editor_dirty is False

    window._start_new_risk()
    window._save_risk(
        {
            "title": " New risk ",
            "probability": 3,
            "impact": 4,
            "description": " ",
            "status": "active",
        }
    )
    created_risk = window.current_risk_id
    assert created_risk is not None
    assert ("create_risk", created_risk) in backend.calls
    window._delete_risk()
    assert ("delete_risk", created_risk) in backend.calls

    window._on_opportunity_clicked(0, 1)
    assert window.current_opportunity_id == "opp-1"
    window.opp_form.title.setText("Updated automation")
    window._opp_editor_dirty = True
    window._commit_opp_editor_changes(refresh=True)
    assert ("update_opportunity", "opp-1") in backend.calls

    window._start_new_opportunity()
    window._save_opportunity(
        {"title": "New opportunity", "probability": 5, "impact": 2}
    )
    created_opp = window.current_opportunity_id
    assert created_opp is not None
    window._delete_opportunity()
    assert ("delete_opportunity", created_opp) in backend.calls

    window.current_project_id = None
    window._save_risk({"title": "No project"})
    assert warnings[-1] == "Select a project first."


def test_scored_entity_helpers_permissions_and_export(monkeypatch, qtbot) -> None:
    window, backend = _window(qtbot)
    exports: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *_args: ("/tmp/interview.csv", "CSV"),
    )
    window._export_entity_csv(
        "risks.csv",
        window._risk_cache,
        lambda path, rows: exports.append((path, [row.id for row in rows])),
    )
    assert exports == [("/tmp/interview.csv", ["risk-1", "risk-2"])]

    owner = QLineEdit()
    owner.setText(" user-7 ")
    assert window._owner_filter_value(owner) == ("user-7", False)
    assert window._owner_filter_value(object()) == (None, False)
    window.filter_owner.setCurrentIndex(1)
    assert window._owner_filter_value(window.filter_owner) == (None, True)

    window.current_role = "member"
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, message, *_args: warnings.append(message),
    )
    result = window._save_entity(
        {"title": "Denied", "status": "deleted"},
        None,
        backend.update_risk,
        backend.create_risk,
        None,
        window.risk_form,
        window.editor_label,
        "Editor",
        [],
    )
    assert result is None
    assert "Only managers" in warnings[-1]

    window.current_role = "manager"
    saved = window._save_entity(
        {"title": "Allowed", "status": "deleted"},
        None,
        backend.update_risk,
        backend.create_risk,
        window._refresh_risks,
        window.risk_form,
        window.editor_label,
        "Editor",
        [window._refresh_matrix],
    )
    assert saved is not None

    assert (
        window._commit_entity_editor_changes(
            None, True, window.risk_form, backend.update_risk, None, None
        )
        is False
    )
    window.current_project_id = None
    assert (
        window._commit_entity_editor_changes(
            "risk-1", True, window.risk_form, backend.update_risk, None, None
        )
        is False
    )


def test_actions_assessments_and_matrix_behaviors(monkeypatch, qtbot) -> None:
    window, backend = _window(qtbot)
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, message, *_args: warnings.append(message),
    )

    assert window.actions_tab.actions_table.rowCount() == 2
    window._on_action_clicked(0, 0)
    assert window.current_action_id == "action-1"
    window.actions_tab.action_title.setText("Updated action")
    window._save_action()
    assert ("update_action", "action-1") in backend.calls

    window._start_new_action()
    window.actions_tab.action_title.setText("New mitigation")
    window.actions_tab.action_risk_combo.setCurrentIndex(0)
    window._save_action()
    assert any(call[0] == "create_action" for call in backend.calls)

    window._start_new_action()
    window.actions_tab.action_target_type.setCurrentText("opportunity")
    window.actions_tab.action_opp_combo.setCurrentIndex(0)
    window.actions_tab.action_title.setText("Exploit opportunity")
    window._save_action()
    assert window.actions_tab.action_opp_combo.isEnabled()

    window.actions_tab.action_title.clear()
    window._save_action()
    assert warnings[-1] == "Title is required."
    window.actions_tab.action_opp_combo.setCurrentIndex(-1)
    window._save_action()
    assert warnings[-1] == "Pick an opportunity."

    window._sync_assessment_state("risk", "risk-1", window.risks_tab)
    assert window.assessments_tab.assessments_table.rowCount() == 1
    assert window.assessments_tab.assess_notes.text() == "reviewed"
    window.assessments_tab.assess_p.setValue(2)
    window.assessments_tab.assess_i.setValue(3)
    window.assessments_tab.assess_notes.setText("changed")
    window._save_assessment()
    assert ("assessment", "risk-1") in backend.calls

    window.current_assessment_item_id = None
    window._refresh_assessments()
    assert window.assessments_tab.assess_p.value() == 3

    window.matrix_tab.kind_combo.setCurrentText("Opportunities")
    window._refresh_matrix()
    assert window.opps_matrix_table.item(2, 3).text() == "1"
    window.matrix_tab.kind_combo.setCurrentText("Both")
    window._refresh_matrix()
    assert window.risks_matrix_table.item(3, 4).text() == "1"
    window._render_matrix(
        window.risks_matrix_table,
        [SimpleNamespace(probability=0, impact=99)],
    )
    assert window.risks_matrix_table.item(0, 4).text() == "1"


def test_helpdesk_crud_filters_and_failures(monkeypatch, qtbot) -> None:
    window, backend = _window(qtbot)
    messages: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, message, *_args: messages.append(message),
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, _title, message, *_args: messages.append(message),
    )
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda _parent, _title, message, *_args: messages.append(message),
    )

    assert window.helpdesk_tab.tickets_table.rowCount() == 2
    window.helpdesk_tab.filter_status.setCurrentText("open")
    window.helpdesk_tab.filter_priority.setCurrentText("high")
    window._apply_helpdesk_filters()
    assert window.helpdesk_tab.tickets_table.rowCount() == 1
    window.helpdesk_tab.tickets_table.selectRow(0)
    window._on_helpdesk_ticket_clicked()
    assert window._current_ticket_id == "ticket-1"
    assert window.helpdesk_tab.ticket_title.text() == "Cannot export"

    window.helpdesk_tab.ticket_title.setText("Export fixed")
    window._save_helpdesk_ticket()
    assert ("update_ticket", "ticket-1") in backend.calls

    window._start_new_helpdesk_ticket()
    window.helpdesk_tab.ticket_title.setText("New ticket")
    window.helpdesk_tab.ticket_description.setPlainText("Details")
    window._save_helpdesk_ticket()
    created = window._current_ticket_id
    assert ("create_ticket", created) in backend.calls

    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
    window._delete_helpdesk_ticket()
    assert ("delete_ticket", created) not in backend.calls
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    window._delete_helpdesk_ticket()
    assert ("delete_ticket", created) in backend.calls

    window._delete_helpdesk_ticket()
    assert messages[-1] == "No ticket selected."
    window.current_project_id = None
    window._refresh_helpdesk()
    assert window.helpdesk_tab.tickets_table.rowCount() == 0
    window._save_helpdesk_ticket()
    assert messages[-1] == "Select a project first."

    window.current_project_id = "project-1"
    window.helpdesk_tab.ticket_title.clear()
    window._save_helpdesk_ticket()
    assert messages[-1] == "Title is required."

    window.helpdesk_tab.ticket_title.setText("Broken")
    backend.create_helpdesk_ticket = Mock(side_effect=RuntimeError("offline"))
    window._current_ticket_id = None
    window._save_helpdesk_ticket()
    assert messages[-1] == "Save failed: offline"


def test_history_snapshot_periods_and_auto_snapshot(monkeypatch, qtbot) -> None:
    window, backend = _window(qtbot)
    messages: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, _title, message, *_args: messages.append(message),
    )

    window._refresh_top_history()
    assert window.top_tab.top_table.rowCount() == 2
    assert "2 row(s)" in window.top_tab.top_report.text()
    window._snapshot_now()
    assert any(call[0] == "snapshot" for call in backend.calls)

    window.top_tab.top_period.setCurrentText("Last 7 days")
    window._on_top_period_changed("Last 7 days")
    assert not window.top_tab.top_from.isEnabled()
    window.top_tab.top_period.setCurrentText("Last 30 days")
    window._on_top_period_changed("Last 30 days")
    window.top_tab.top_period.setCurrentText("Custom")
    window._on_top_period_changed("Custom")
    assert window.top_tab.top_from.isEnabled()

    window.current_project_id = "local-1"
    window._snapshot_now()
    assert "Sync this project" in messages[-1]
    window._refresh_top_history()
    assert "Local project" in window.top_tab.top_report.text()

    window.current_project_id = "project-1"
    window.current_role = "member"
    window.top_tab.auto_snapshot_chk.setEnabled(True)
    window.top_tab.auto_snapshot_chk.setChecked(True)
    window._maybe_auto_snapshot()
    assert "manager role" in messages[-1]

    window.current_role = "manager"
    window.top_tab.auto_snapshot_days.setValue(1)
    window.top_tab.auto_snapshot_kind.setCurrentText("Risks")
    window._last_auto_snapshot_by_project.clear()
    window._maybe_auto_snapshot()
    assert "project-1" in window._last_auto_snapshot_by_project
    before = len(backend.calls)
    window._maybe_auto_snapshot()
    assert len(backend.calls) == before


def test_core_permissions_context_and_layout_helpers(monkeypatch, qtbot) -> None:
    window, backend = _window(qtbot)
    window.current_role = "unknown"
    window._offline_mode = True
    window._role_assumed = False
    window._apply_permissions()
    assert window.new_risk_btn.isEnabled()
    assert "assumed" in window.role_status.text()

    window._set_role_status(role="admin", offline=False, assumed=False)
    assert window.role_status.text() == "Role: admin"
    backend.superuser = True
    window._set_role_status(role="admin", offline=False, assumed=False)
    assert window.role_status.text() == "Role: superadmin"

    window.tabs = window.ui.main_stacked_widget
    window.ui.main_stacked_widget.setCurrentWidget(window.risks_tab)
    assert window._active_scored_tab_context()[1] is window.risks_table
    window.ui.main_stacked_widget.setCurrentWidget(window.opps_tab)
    assert window._active_scored_tab_context()[1] is window.opps_table
    window.ui.main_stacked_widget.setCurrentWidget(window.matrix_tab)
    assert window._active_scored_tab_context() is None

    parent = QWidget()
    child = QWidget(parent)
    qtbot.addWidget(parent)
    assert window._is_inside(parent, child) is True
    assert window._is_inside(None, child) is False
    assert window._is_inside(object(), child) is False

    iso = window._dtedit_to_iso_utc_naive(window.top_tab.top_from)
    assert "T" in iso
    window.risks_table.setRowCount(20)
    window._fit_table_to_contents(window.risks_table, max_height=20)
    assert window.risks_table.height() == 20

    window.current_project_id = None
    window._snapshot_now()
    window._refresh_top_history()
    window._maybe_auto_snapshot()
    assert datetime.now(UTC).year >= 2026
