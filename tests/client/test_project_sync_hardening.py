"""GUI regressions for decorated project labels and local-only sync state."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtWidgets import QDialog, QLabel, QListWidget, QMessageBox, QPushButton
from riskapp_client.domain.domain_models import Project
from riskapp_client.ui_v2.mixins import projects_sync_mixin
from riskapp_client.ui_v2.mixins.projects_sync_mixin import ProjectsSyncMixin


class ProjectHost(ProjectsSyncMixin):
    def __init__(self, backend) -> None:
        self.backend = backend
        self.project_list = QListWidget()
        self.sync_btn = QPushButton()
        self.sync_status = QLabel()
        self.conflicts_btn = QPushButton()
        self.current_project_id: str | None = None
        self._cached_members = []

    @staticmethod
    def _call_backend(_title, fn, *args):
        return fn(*args)


def test_duplicate_check_uses_original_name_not_decorated_label(
    monkeypatch, qtbot
) -> None:
    backend = SimpleNamespace(
        list_projects=Mock(
            return_value=[Project("local-anon", "Private", created_by="")]
        ),
        current_user_id=Mock(return_value=None),
        create_project=Mock(),
        store=SimpleNamespace(get_meta=Mock(return_value="")),
    )
    host = ProjectHost(backend)
    qtbot.addWidget(host.project_list)
    qtbot.addWidget(host.sync_btn)
    qtbot.addWidget(host.sync_status)
    qtbot.addWidget(host.conflicts_btn)
    host._load_projects()
    assert host.project_list.item(0).text() == "Private  (local only)"

    class AcceptedDialog:
        def __init__(self, *, parent) -> None:
            self.parent = parent

        @staticmethod
        def exec() -> int:
            return QDialog.Accepted

        @staticmethod
        def values() -> tuple[str, str]:
            return " private ", "duplicate"

    warnings: list[str] = []
    monkeypatch.setattr(projects_sync_mixin, "NewProjectDialog", AcceptedDialog)
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, message, *_args: warnings.append(message),
    )

    host._create_new_project()

    backend.create_project.assert_not_called()
    assert "already exists" in warnings[0]


def test_local_only_status_cannot_be_reenabled_by_online_backend(qtbot) -> None:
    backend = SimpleNamespace(
        store=SimpleNamespace(
            get_project=Mock(
                return_value=Project("local-anon", "Private", created_by="")
            )
        ),
        pending_count=Mock(),
        blocked_count=Mock(),
        can_sync=Mock(return_value=True),
    )
    host = ProjectHost(backend)
    host.current_project_id = "local-anon"
    qtbot.addWidget(host.project_list)
    qtbot.addWidget(host.sync_btn)
    qtbot.addWidget(host.sync_status)
    qtbot.addWidget(host.conflicts_btn)

    host._update_sync_status()

    assert not host.sync_btn.isEnabled()
    assert not host.conflicts_btn.isEnabled()
    assert host.conflicts_btn.text() == "Conflicts (0)"
    assert host.sync_status.text() == "Sync: local-only project, cannot be synced"
    backend.pending_count.assert_not_called()
    backend.blocked_count.assert_not_called()
    backend.can_sync.assert_not_called()
