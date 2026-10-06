"""Manual reconnect keeps queued edits and adopts the recovered worker session."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QListWidget, QMessageBox, QPushButton, QWidget
from riskapp_client.domain.domain_models import Project
from riskapp_client.services.offline_first_facade import OfflineFirstBackend
from riskapp_client.ui_v2.mixins.projects_sync_mixin import ProjectsSyncMixin
from riskapp_client.ui_v2.workers import BackgroundJobRunner
from riskapp_client.ui_v2.workers import background_jobs as jobs
from support import InProcessRemote, create_project, register_user

# Exercise the real mixin/runner boundary without unrelated editor widgets.
# pylint: disable=protected-access


class _SyncHost(QWidget, ProjectsSyncMixin):
    def __init__(self, backend, project_id) -> None:
        super().__init__()
        self.backend = backend
        self.current_project_id = project_id
        self.current_risk_id = None
        self._offline_mode = True
        self._role_assumed = True
        self.project_list = QListWidget(self)
        self.sync_btn = QPushButton(self)
        self.sync_status = QLabel(self)
        self.conflicts_btn = QPushButton(self)
        self._background_jobs = BackgroundJobRunner(
            backend.create_background_backend, owns_backend=True, parent=self
        )
        # PySide signal descriptors cannot be inferred by Pylint.
        # pylint: disable=no-member
        self.sync_btn.clicked.connect(self._sync_now)
        self._background_jobs.busy_changed.connect(self._busy_changed)
        # pylint: enable=no-member

    def _busy_changed(self, busy, _kind) -> None:
        if busy:
            self.sync_btn.setEnabled(False)
        else:
            self._update_sync_status()

    def _start_background_job(self, *args, **kwargs):
        return self._background_jobs.start(*args, **kwargs)

    def _refresh_all_views(self, **options) -> None:
        assert options["include_remote"] is False
        self._update_sync_status()

    def _observe_manual_sync_result(self, _result: object) -> None:
        pass

    def _record_automatic_sync_success(self, _result: object) -> None:
        # This test host disables automatic scheduling.
        pass

    @staticmethod
    def _schedule_automatic_sync() -> None:
        # Automatic scheduling is disabled for this manual-only session.
        pass


@pytest.fixture(name="reconnect_case")
def _reconnect_case(tmp_path, local_store, isolated_app_factory):
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'server.sqlite3'}")
    with TestClient(app) as client:
        user = register_user(client)
        project = create_project(client, user, name="Manual reconnect")
        local_store.upsert_projects([Project(project.id, "Manual reconnect")])
        local_store.set_meta("user_id", user.id)
        remote = InProcessRemote(client, user)
        online = OfflineFirstBackend(local_store, remote)
        risk = online.create_risk(
            project.id, title="Before restart", probability=2, impact=3
        )
        assert online.sync_project(project.id)["state"] == "complete"
        online.update_risk(
            project.id, risk.id, title="Saved offline", probability=4, impact=3
        )
        yield local_store, remote, project.id, risk.id


@pytest.mark.parametrize("fail_first", [False, True])
def test_manual_reconnect_without_scheduler_preserves_and_pushes_draft(
    reconnect_case, qtbot, monkeypatch, fail_first
) -> None:
    store, remote, project_id, risk_id = reconnect_case
    main_thread = threading.get_ident()
    attempts = []

    def reconnect():
        attempts.append(threading.get_ident())
        if fail_first and len(attempts) == 1:
            raise RuntimeError("Server still unavailable")
        return remote

    backend = OfflineFirstBackend(store, remote_factory=reconnect)
    pending = backend.outbox.get_pending_changes(project_id)[0]
    host = _SyncHost(backend, project_id)
    qtbot.addWidget(host)
    messages = []
    for method in ("information", "warning", "critical"):
        monkeypatch.setattr(
            QMessageBox,
            method,
            lambda _parent, title, *_args: messages.append(title),
        )

    try:
        host._update_sync_status()
        assert not backend.can_sync()
        assert host.sync_status.text().startswith("OFFLINE")
        assert host.sync_btn.isEnabled()
        qtbot.mouseClick(host.sync_btn, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: bool(messages) and not host._background_jobs.is_busy)

        if fail_first:
            assert messages == ["Sync failed"]
            assert backend.remote is None
            assert backend.outbox.get_pending_changes(project_id)[0] == pending
            assert store.get_risk_row(risk_id)["title"] == "Saved offline"
            assert host.sync_btn.isEnabled()
            messages.clear()
            qtbot.mouseClick(host.sync_btn, Qt.MouseButton.LeftButton)
            qtbot.waitUntil(
                lambda: bool(messages) and not host._background_jobs.is_busy
            )

        assert messages == ["Sync complete"]
        assert backend.remote is remote
        assert backend.can_sync()
        assert not host._offline_mode
        assert not host._role_assumed
        assert host.sync_status.text().startswith("ONLINE")
        assert backend.pending_count(project_id) == 0
        assert all(thread_id != main_thread for thread_id in attempts)
        restored = remote.sync_pull(project_id, since_sequence=0)
        row = next(item for item in restored["risks"] if item["id"] == risk_id)
        assert row["title"] == "Saved offline"
        assert row["probability"] == 4
    finally:
        assert host._background_jobs.shutdown()


def test_offline_session_without_reconnect_factory_keeps_sync_disabled(
    reconnect_case, qtbot
) -> None:
    store, _remote, project_id, _risk_id = reconnect_case
    backend = OfflineFirstBackend(store, anonymous_offline=True)
    host = _SyncHost(backend, project_id)
    qtbot.addWidget(host)
    host._update_sync_status()
    assert not host.sync_btn.isEnabled()
    assert not backend.can_auto_sync()


@pytest.mark.usefixtures("qtbot")
@pytest.mark.parametrize("state", ["authentication_required", "cancelled"])
def test_manual_authentication_or_cancellation_does_not_export_a_session(
    state: str,
) -> None:
    class Backend:
        @staticmethod
        def list_projects() -> list[Project]:
            raise AssertionError("Project listing must not run in this sync-only test")

        @staticmethod
        def sync_project(
            project_id: str,
            *,
            should_cancel: Callable[[], bool] | None = None,
            progress: Callable[[str], None] | None = None,
        ) -> dict[str, Any]:
            assert project_id == "project-1"
            del should_cancel, progress
            return {"state": state}

        @staticmethod
        def create_snapshot(
            project_id: str, *, kind: str | None = None
        ) -> dict[str, Any]:
            raise AssertionError(f"Unexpected snapshot for {project_id}: {kind}")

        @staticmethod
        def top_history(
            project_id: str,
            *,
            kind: str = "risks",
            limit: int = 10,
            from_ts: str | None = None,
            to_ts: str | None = None,
        ) -> list[dict[str, Any]]:
            raise AssertionError(
                f"Unexpected history for {project_id}: {kind}, {limit}, "
                f"{from_ts}, {to_ts}"
            )

        @staticmethod
        def export_authenticated_remote() -> object | None:
            raise AssertionError("An authentication failure must not be adopted")

    worker = jobs._BackgroundJobWorker(
        Backend,
        owns_backend=False,
        kind="sync",
        payload={"project_id": "project-1", "export_remote": True},
        cancel_event=threading.Event(),
    )
    results = []
    failures = []
    cancelled = []
    worker.succeeded.connect(lambda _kind, result: results.append(result))
    worker.failed.connect(lambda _kind, message: failures.append(message))
    worker.cancelled.connect(cancelled.append)
    worker.run()
    assert not failures
    if state == "cancelled":
        assert not results
        assert cancelled == ["sync"]
    else:
        assert results == [{"state": "authentication_required"}]
        assert not cancelled
