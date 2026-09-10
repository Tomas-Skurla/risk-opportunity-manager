"""Main-window orchestration for blocking background backend jobs."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QLabel, QListWidget, QProgressBar, QPushButton
from riskapp_client.ui_v2.workers import BackgroundJobRunner

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
    _background_jobs: BackgroundJobRunner
    _apply_permissions: Callable[[], None]
    _update_sync_status: Callable[[], None]

    def _init_background_jobs(self) -> None:
        factory = getattr(self.backend, "create_background_backend", None)
        owns_backend = callable(factory)
        if not owns_backend:
            # Test or alternate backends without SQLite can still run outside
            # the event loop. Production OfflineFirstBackend always supplies a
            # factory which constructs a worker-owned LocalStore.
            shared_backend = self.backend

            def shared_backend_factory():
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
        return self._background_jobs.shutdown()
