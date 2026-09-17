"""Main-window orchestration for blocking background backend jobs."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QLabel, QListWidget, QProgressBar, QPushButton
from riskapp_client.ui_v2.workers import (
    AutomaticSyncScheduler,
    BackgroundJobRunner,
)

if TYPE_CHECKING:
    from riskapp_client.ui_v2.tabs.top_history_tab import TopHistoryTab


class BackgroundJobsMixin:
    """Own the worker runner and reflect its state in the status bar."""

    backend: Any
    background_progress: QProgressBar
    cancel_background_btn: QPushButton
    conflicts_btn: QPushButton
    project_list: QListWidget
    sync_btn: QPushButton
    sync_status: QLabel
    top_tab: TopHistoryTab
    _automatic_sync_scheduler: AutomaticSyncScheduler
    _background_jobs: BackgroundJobRunner
    _apply_permissions: Callable[[], None]
    _automatic_sync_requested: Callable[[], bool]
    _update_sync_status: Callable[[], None]

    def _init_background_jobs(
        self,
        *,
        auto_sync_interval_seconds: int = 0,
        auto_sync_max_backoff_seconds: int = 300,
        auto_sync_initial_delay_seconds: int = 5,
    ) -> None:
        candidate_factory = getattr(self.backend, "create_background_backend", None)
        factory: Callable[[], Any]
        if callable(candidate_factory):
            owns_backend = True
            factory = cast(Callable[[], Any], candidate_factory)
        else:
            owns_backend = False
            # Test or alternate backends without SQLite can still run outside
            # the event loop. Production OfflineFirstBackend always supplies a
            # factory which constructs a worker-owned LocalStore.
            shared_backend = self.backend

            def shared_backend_factory() -> Any:
                return shared_backend

            factory = shared_backend_factory

        self._background_jobs = BackgroundJobRunner(
            factory,
            owns_backend=owns_backend,
            parent=cast(QObject, self),
        )
        self._background_jobs.busy_changed.connect(self._on_background_busy_changed)
        self._background_jobs.progress_changed.connect(
            self._on_background_progress_changed
        )
        self._automatic_sync_scheduler = AutomaticSyncScheduler(
            self._automatic_sync_requested,
            interval_seconds=auto_sync_interval_seconds,
            initial_delay_seconds=auto_sync_initial_delay_seconds,
            max_backoff_seconds=auto_sync_max_backoff_seconds,
            parent=cast(QObject, self),
        )

    def _start_automatic_sync_scheduler(self) -> None:
        available = getattr(self.backend, "can_auto_sync", None)
        if callable(available) and not bool(available()):
            return
        self._automatic_sync_scheduler.start()

    def _schedule_automatic_sync(self) -> None:
        self._automatic_sync_scheduler.request_soon()

    def _record_automatic_sync_success(self, result: object) -> None:
        self._automatic_sync_scheduler.job_succeeded(result)

    def _record_automatic_sync_failure(self) -> None:
        self._automatic_sync_scheduler.job_failed()

    def _observe_manual_sync_result(self, result: object) -> None:
        self._automatic_sync_scheduler.observe_result(result)

    def _start_background_job(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        on_success: Callable[[object], None] | None = None,
        on_failure: Callable[[str], None] | None = None,
        on_cancelled: Callable[[], None] | None = None,
    ) -> bool:
        return self._background_jobs.start(
            kind,
            payload,
            on_success=on_success,
            on_failure=on_failure,
            on_cancelled=on_cancelled,
        )

    def _on_background_busy_changed(self, busy: bool, kind: str) -> None:
        self.background_progress.setVisible(busy)
        cancellable = busy and kind == "sync"
        self.cancel_background_btn.setVisible(cancellable)
        self.cancel_background_btn.setEnabled(cancellable)
        if busy:
            if kind == "sync":
                self.project_list.setEnabled(False)
            self.sync_btn.setEnabled(False)
            if hasattr(self, "conflicts_btn"):
                self.conflicts_btn.setEnabled(False)
            if hasattr(self, "top_tab"):
                self.top_tab.snapshot_btn.setEnabled(False)
                self.top_tab.refresh_top_btn.setEnabled(False)
            label = {
                "sync": "Synchronizing",
                "automatic_sync": "Synchronizing automatically",
                "snapshot": "Creating snapshot",
                "history": "Loading history",
            }.get(kind, "Working")
            self.sync_status.setText(f"Sync: {label}…")
        else:
            self.project_list.setEnabled(True)
            if hasattr(self, "top_tab"):
                self.top_tab.refresh_top_btn.setEnabled(True)
            self._update_sync_status()
            self._apply_permissions()

    def _on_background_progress_changed(self, message: str) -> None:
        self.sync_status.setText(f"Sync: {message}")

    def _cancel_background_job(self) -> None:
        self.cancel_background_btn.setEnabled(False)
        self._background_jobs.cancel()

    def _shutdown_background_jobs(self) -> bool:
        self._automatic_sync_scheduler.stop()
        stopped = self._background_jobs.shutdown()
        if not stopped:
            # closeEvent() keeps the window alive when a request outlasts the
            # bounded wait, so restore periodic scheduling for that live window.
            self._automatic_sync_scheduler.start()
        return stopped
