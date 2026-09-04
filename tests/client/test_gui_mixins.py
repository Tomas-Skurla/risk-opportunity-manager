"""Focused interaction tests for handwritten main-window mixins."""

from __future__ import annotations

from unittest.mock import Mock

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidgetItem,
)
from riskapp_client.domain.domain_models import Member, Project
from riskapp_client.ui_v2.mixins.members_mixin import MembersMixin
from riskapp_client.ui_v2.mixins.projects_sync_mixin import ProjectsSyncMixin
from riskapp_client.ui_v2.tabs.members_tab import MembersTab


class ProjectSyncHost(ProjectsSyncMixin):
    def __init__(self, backend) -> None:
        self.backend = backend
        self.current_project_id = "project-1"
        self.current_risk_id = "risk-1"
        self.sync_btn = QPushButton()
        self.sync_status = QLabel()
        self.project_list = QListWidget()
        self._cached_members: list[Member] = []
        self._load_projects_calls: list[str | None] = []
        self._refresh_calls: list[str | None] = []

    def _call_backend(self, _title, fn, *args):
        try:
            return fn(*args)
        except Exception:  # noqa: BLE001 - mirrors the real GUI error boundary
            return None

    def _load_projects(self, *, select_project_id=None) -> None:
        self._load_projects_calls.append(select_project_id)

    def _refresh_all_views(self, *, select_id=None) -> None:
        self._refresh_calls.append(select_id)


class ProjectListHost(ProjectsSyncMixin):
    def __init__(self, backend) -> None:
        self.backend = backend
        self.project_list = QListWidget()
        self._cached_members = [Member("owner-2", "owner@example.test", "admin")]

    def _call_backend(self, _title, fn, *args):
        return fn(*args)


class MembersHost(MembersMixin):
    def __init__(self, backend) -> None:
        self.backend = backend
        self.current_project_id = "project-1"
        self.members_tab = MembersTab(
            on_add_or_update_member=Mock(),
            on_remove_selected_member=Mock(),
            on_refresh_members=Mock(),
            on_member_selected=Mock(),
        )
        self._cached_members: list[Member] = []
        self._role_by_project: dict[str, str] = {}
        self.risk_form = Mock()
        self.opp_form = Mock()
        self.risks_tab = Mock()
        self.opps_tab = Mock()
        self._offline = False
        self._local = False
        self._apply_permissions = Mock()
        self._set_role_status = Mock()

    def _detect_offline_mode(self) -> bool:
        return self._offline

    def _is_local_project(self) -> bool:
        return self._local

    @staticmethod
    def _mk_item(text, *, entity_id=None):
        item = QTableWidgetItem(str(text))
        if entity_id is not None:
            item.setData(Qt.UserRole, entity_id)
        return item


def test_project_sync_status_and_blocked_details(qtbot) -> None:
    class Backend:
        def pending_count(self, project_id):
            assert project_id == "project-1"
            return 4

        def conflict_count(self, project_id):
            assert project_id == "project-1"
            return 2

        def error_count(self, project_id):
            assert project_id == "project-1"
            return 1

        def last_sync_time(self, project_id):
            assert project_id == "project-1"
            return "2026-08-10T08:09:00-04:00"

        def can_sync(self):
            return True

    host = ProjectSyncHost(Backend())
    qtbot.addWidget(host.sync_btn)
    qtbot.addWidget(host.sync_status)

    host._update_sync_status()

    assert host.sync_btn.isEnabled()
    assert host.sync_status.text() == (
        "ONLINE · pending: 4 · conflicts: 2 · errors: 1 "
        "· last sync: 2026-08-10 12:09 UTC"
    )
    assert host._format_last_sync_time(None) == "never"
    assert host._format_last_sync_time("not-a-time") == "unknown"
    assert host._format_last_sync_time("2026-08-10T08:09:00") == (
        "2026-08-10 08:09 UTC"
    )
    assert host._format_blocked_sync_details({}) == ""
    assert host._format_blocked_sync_details({"blocked_details": "invalid"}) == ""
    details = host._format_blocked_sync_details(
        {
            "blocked_details": [
                "invalid",
                {
                    "entity": "risk",
                    "title": "Outage",
                    "op": "upsert",
                    "reason": "Server changed",
                    "server_version": 8,
                },
            ]
        }
    )
    assert "Risk 'Outage' · upsert · Server changed" in details
    assert "server version: 8" in details


def test_project_sync_status_falls_back_when_backend_queries_fail(qtbot) -> None:
    class BrokenBackend:
        def pending_count(self, _project_id):
            raise RuntimeError("offline")

        def conflict_count(self, _project_id):
            raise AttributeError("unsupported")

        def error_count(self, _project_id):
            raise RuntimeError("offline")

        def last_sync_time(self, _project_id):
            raise RuntimeError("offline")

        def can_sync(self):
            raise RuntimeError("offline")

    host = ProjectSyncHost(BrokenBackend())
    qtbot.addWidget(host.sync_btn)
    qtbot.addWidget(host.sync_status)

    host._update_sync_status()

    assert not host.sync_btn.isEnabled()
    assert host.sync_status.text() == (
        "OFFLINE · pending: 0 · conflicts: 0 · errors: 0 · last sync: never"
    )


def test_sync_now_migrates_project_refreshes_and_reports(monkeypatch, qtbot) -> None:
    summary = {
        "project_id_migrated_to": "server-project-1",
        "pushed": 2,
        "conflicts": 1,
        "errors": 1,
        "blocked": 1,
        "pulled_risks": 3,
        "blocked_details": [
            {
                "entity": "risk",
                "entity_id": "risk-2",
                "op": "delete",
                "reason": "Permission denied",
            }
        ],
    }

    class Backend:
        def sync_project(self, project_id):
            assert project_id == "project-1"
            return summary

    messages: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, _title, message, *_args: messages.append(message),
    )
    host = ProjectSyncHost(Backend())
    qtbot.addWidget(host.sync_btn)
    qtbot.addWidget(host.sync_status)

    host._sync_now()

    assert host.current_project_id == "server-project-1"
    assert host._load_projects_calls == ["server-project-1"]
    assert host._refresh_calls == ["risk-1"]
    assert "Pushed: 2" in messages[-1]
    assert "Conflicts blocked: 1" in messages[-1]
    assert "Risk 'risk-2' · delete · Permission denied" in messages[-1]


def test_sync_now_handles_missing_project_unsupported_and_failed_backend(
    monkeypatch, qtbot
) -> None:
    messages: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, _title, message, *_args: messages.append(message),
    )
    host = ProjectSyncHost(object())
    qtbot.addWidget(host.sync_btn)
    qtbot.addWidget(host.sync_status)

    host.current_project_id = None
    host._sync_now()
    assert messages == []

    host.current_project_id = "project-1"
    host._sync_now()
    assert messages == ["This backend does not support sync."]

    class BrokenBackend:
        def sync_project(self, _project_id):
            raise RuntimeError("offline")

        def pending_count(self, _project_id):
            return 1

        def conflict_count(self, _project_id):
            return 0

        def error_count(self, _project_id):
            return 0

        def last_sync_time(self, _project_id):
            return None

        def can_sync(self):
            return False

    host.backend = BrokenBackend()
    host._sync_now()
    assert host.sync_status.text() == (
        "OFFLINE · pending: 1 · conflicts: 0 · errors: 0 · last sync: never"
    )


def test_project_list_labels_local_state_owner_and_selection(qtbot) -> None:
    class Store:
        @staticmethod
        def get_meta(key):
            return {"last_email": "me@example.test", "user_id": "owner-1"}.get(key)

    class Backend:
        store = Store()

        @staticmethod
        def current_user_id():
            return "owner-1"

        @staticmethod
        def list_projects():
            return [
                Project("local-anon", "Private", created_by=""),
                Project("local-user", "Draft", created_by="owner-1"),
                Project("server-1", "Remote", created_by="owner-2"),
            ]

    host = ProjectListHost(Backend())
    qtbot.addWidget(host.project_list)

    host._load_projects(select_project_id="server-1")

    assert host.project_list.count() == 3
    assert host.project_list.item(0).text() == "Private  (local only)"
    assert host.project_list.item(1).text() == "Draft  (offline, will sync)"
    assert host.project_list.item(2).text() == "Remote  (owner@example.test)"
    assert host.project_list.currentItem().data(Qt.UserRole) == "server-1"


def test_members_refresh_populates_widgets_and_protects_superuser(qtbot) -> None:
    members = [
        Member("user-1", "me@example.test", "manager"),
        Member("super-1", "root@example.test", "admin", is_superuser=True),
    ]

    class Backend:
        superuser = False

        @staticmethod
        def list_members(project_id):
            assert project_id == "project-1"
            return members

        @staticmethod
        def current_user_id():
            return "user-1"

        def is_superuser(self):
            return self.superuser

        add_member = Mock()
        remove_member = Mock()

    backend = Backend()
    host = MembersHost(backend)
    qtbot.addWidget(host.members_tab)

    host._refresh_members()

    assert host.members_tab.members_table.rowCount() == 2
    assert host.members_tab.members_table.item(1, 1).text() == "superadmin"
    host.risk_form.set_members.assert_called_once_with(members)
    host.opps_tab.set_owner_filter_members.assert_called_once_with(members)
    host._set_role_status.assert_called_with(
        role="manager", offline=False, assumed=False
    )
    host.members_tab.members_table.selectRow(1)
    host._on_member_selected()
    assert not host.members_tab.member_role.isEnabled()
    assert not host.members_tab.member_remove_btn.isEnabled()

    backend.superuser = True
    host._on_member_selected()
    assert host.members_tab.member_role.isEnabled()
    assert host.members_tab.member_remove_btn.isEnabled()


def test_member_add_remove_validation_and_success(monkeypatch, qtbot) -> None:
    class Backend:
        add_member = Mock()
        remove_member = Mock()

        @staticmethod
        def is_superuser():
            return True

    backend = Backend()
    host = MembersHost(backend)
    qtbot.addWidget(host.members_tab)
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, message, *_args: warnings.append(message),
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    host._refresh_members = Mock()

    host.members_tab.member_email.setText("invalid")
    host._add_or_update_member()
    assert warnings == ["Please enter a valid email."]
    backend.add_member.assert_not_called()

    host.members_tab.member_email.setText("new@example.test")
    host.members_tab.member_role.setCurrentText("manager")
    host._add_or_update_member()
    backend.add_member.assert_called_once_with(
        "project-1", user_email="new@example.test", role="manager"
    )
    assert host.members_tab.member_email.text() == ""

    table = host.members_tab.members_table
    table.setRowCount(1)
    table.setItem(0, 0, host._mk_item("old@example.test", entity_id="user-9"))
    table.selectRow(0)
    host._remove_selected_member()
    backend.remove_member.assert_called_once_with(
        "project-1", member_user_id="user-9"
    )
    assert host._refresh_members.call_count == 2


def test_members_refresh_handles_no_project_and_offline_mode(qtbot) -> None:
    backend = Mock()
    backend.is_superuser.return_value = False
    host = MembersHost(backend)
    qtbot.addWidget(host.members_tab)

    host.current_project_id = None
    host._refresh_members()
    assert host.members_tab.members_hint.text().startswith("Select a project")
    host._apply_permissions.assert_called_once()

    host.current_project_id = "local-1"
    host._offline = True
    host._refresh_members()
    assert host.members_tab.members_hint.text().startswith("Offline mode")
    backend.list_members.assert_not_called()
