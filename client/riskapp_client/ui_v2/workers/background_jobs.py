"""Run blocking backend jobs without blocking the Qt event loop."""

from __future__ import annotations

import dataclasses
import logging
import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

from riskapp_client.adapters.remote_api.rest_api_client import ApiError
from riskapp_client.domain.background_job_contracts import (
    BackendFactory,
    BackgroundJobBackend,
)
from riskapp_client.domain.domain_models import Project
from riskapp_client.domain.sync_protocol import (
    FailureKind,
    SyncState,
    classify_http_status,
    sync_state_for_failure,
)

logger = logging.getLogger(__name__)

SuccessCallback = Callable[[object], None]
FailureCallback = Callable[[str], None]
CancelledCallback = Callable[[], None]


def _is_syncable(project: Project) -> bool:
    """Anonymous local projects have no owner and can never be published."""
    return bool(project.id) and not (
        project.id.startswith("local-") and not project.created_by
    )


def _failed_project_summary(exc: Exception) -> dict[str, Any]:
    """Summarize an exception that escaped one project's synchronization."""
    request_failed = isinstance(exc, (ApiError, OSError))
    if request_failed:
        status = exc.status if isinstance(exc, ApiError) else 0
        failure_kind, retryable = classify_http_status(status)
    else:
        failure_kind, retryable = FailureKind.ERROR, False
    return {
        "state": sync_state_for_failure(failure_kind),
        "sync_error": {
            "reason": "project_sync_failed",
            "failure_kind": failure_kind,
            "retryable": retryable,
            "request_failed": request_failed,
            "detail": str(exc),
        },
    }


def _ends_automatic_pass(summary: dict[str, Any]) -> bool:
    """Transport and authentication failures normally affect every project."""
    sync_error = summary.get("sync_error")
    return (
        str(summary.get("state") or "")
        in {SyncState.AUTHENTICATION_REQUIRED, SyncState.RETRY_WAIT}
        and isinstance(sync_error, dict)
        and bool(sync_error.get("request_failed"))
    )


def _combined_state(summaries: list[dict[str, Any]]) -> str:
    """The most urgent state across projects decides the pass's state."""
    states = {str(item.get("state") or SyncState.COMPLETE) for item in summaries}
    for state in (SyncState.AUTHENTICATION_REQUIRED, SyncState.RETRY_WAIT):
        if state in states:
            return state
    if states - {SyncState.COMPLETE}:
        return SyncState.ATTENTION_REQUIRED
    return SyncState.COMPLETE


def _earliest_retry(summaries: list[dict[str, Any]]) -> str | None:
    return min(
        (str(item["next_retry_at"]) for item in summaries if item.get("next_retry_at")),
        default=None,
    )


class _BackgroundJobWorker(QObject):
    """Execute exactly one job inside a worker thread."""

    progress = Signal(str)
    succeeded = Signal(str, object)
    failed = Signal(str, str)
    cancelled = Signal(str)
    finished = Signal()

    def __init__(
        self,
        backend_factory: BackendFactory,
        *,
        owns_backend: bool,
        kind: str,
        payload: dict[str, Any],
        cancel_event: threading.Event,
    ) -> None:
        super().__init__()
        self._backend_factory = backend_factory
        self._owns_backend = owns_backend
        self._kind = kind
        self._payload = dict(payload)
        self._cancel_event = cancel_event

    def _is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def _sync_project(
        self, backend: BackgroundJobBackend, project_id: str
    ) -> dict[str, Any]:
        result = backend.sync_project(
            project_id,
            should_cancel=self._is_cancelled,
            progress=self.progress.emit,
        )
        if not isinstance(result, dict):
            raise RuntimeError("Synchronization returned an invalid result")
        return result

    def _run_sync(self, backend: BackgroundJobBackend) -> dict[str, Any]:
        result = self._sync_project(
            backend,
            str(self._payload["project_id"]),
        )

        # A local project promotion changes the sidebar identity. Fetch the
        # authoritative visible project list here, not from the GUI thread.
        if result.get("project_id_migrated_to") and not self._is_cancelled():
            try:
                self.progress.emit("Refreshing project list")
                result["_visible_projects"] = backend.list_projects()
            # Refresh is secondary and must not turn a successful sync into failure.
            # pylint: disable-next=broad-exception-caught
            except Exception:  # sync itself already succeeded
                logger.warning(
                    "Could not refresh projects after synchronization",
                    exc_info=True,
                )
        self._export_authenticated_remote(backend, result)
        return result

    def _export_authenticated_remote(
        self, backend: BackgroundJobBackend, result: dict[str, Any]
    ) -> None:
        if not self._payload.get("export_remote") or result.get("state") in {
            SyncState.AUTHENTICATION_REQUIRED,
            SyncState.CANCELLED,
        }:
            return
        authenticated_remote = backend.export_authenticated_remote()
        if authenticated_remote is not None:
            result["_authenticated_remote"] = authenticated_remote

    def _run_automatic_sync(self, backend: BackgroundJobBackend) -> dict[str, Any]:
        """Synchronize every visible, syncable project in one worker session."""
        self.progress.emit("Checking projects for automatic sync")
        projects = backend.list_sync_projects()
        syncable = [project for project in projects if _is_syncable(project)]
        summaries: list[dict[str, Any]] = []
        migrations: dict[str, str] = {}
        for index, project in enumerate(syncable, start=1):
            if self._is_cancelled():
                if migrations:
                    break  # promotions that already happened must reach the window
                return {
                    "state": SyncState.CANCELLED,
                    "cancelled": True,
                    "projects": summaries,
                }

            summary = self._sync_isolated(backend, project, f"{index}/{len(syncable)}")
            summaries.append(summary)
            if summary.get("project_id_migrated_to"):
                migrations[str(project.id)] = str(summary["project_id_migrated_to"])
            if _ends_automatic_pass(summary):
                # Stop rather than hammer the same broken connection once per
                # project; the scheduler will retry later.
                break

        if migrations:
            projects = self._refresh_after_migrations(
                backend.list_sync_projects, projects, migrations
            )
        result: dict[str, Any] = {
            "state": _combined_state(summaries),
            "projects": summaries,
            "project_id_migrations": migrations,
            "next_retry_at": _earliest_retry(summaries),
            "_visible_projects": projects,
        }
        self._export_authenticated_remote(backend, result)
        return result

    def _sync_isolated(
        self, backend: BackgroundJobBackend, project: Project, position: str
    ) -> dict[str, Any]:
        """Sync one project; its failure must not starve later projects."""
        project_id = str(project.id)
        project_name = project.name or project_id
        self.progress.emit(f"Automatically synchronizing {position}: {project_name}")
        try:
            summary = self._sync_project(backend, project_id)
        # A corrupt local row or project-specific server failure is reported in
        # this project's summary instead of ending the automatic pass.
        # pylint: disable-next=broad-exception-caught
        except Exception as exc:  # isolate this project and continue
            logger.exception(
                "Automatic synchronization failed for project %s (%s)",
                project_id,
                project_name,
            )
            summary = _failed_project_summary(exc)
        summary.setdefault("project_id", project_id)
        return summary

    def _refresh_after_migrations(
        self,
        list_projects: Callable[[], list[Project]],
        projects: list[Project],
        migrations: dict[str, str],
    ) -> list[Project]:

        if not self._is_cancelled():
            try:
                self.progress.emit("Refreshing project list")
                return list_projects()
            # A secondary refresh must not discard completed synchronization.
            # pylint: disable-next=broad-exception-caught
            except Exception:
                logger.warning(
                    "Could not refresh projects after automatic synchronization",
                    exc_info=True,
                )
        # Skipped or failed: keep the sidebar IDs aligned with the already-promoted
        # local rows.
        return [
            dataclasses.replace(project, id=migrations.get(str(project.id), project.id))
            for project in projects
        ]

    def _run_history(self, backend: BackgroundJobBackend) -> dict[str, Any]:
        self.progress.emit("Loading snapshot history")
        project_id = str(self._payload["project_id"])
        request = dict(self._payload.get("history") or {})
        batches = backend.top_history(
            project_id,
            **request,
        )
        return {
            "project_id": project_id,
            "history": list(batches or []),
            "history_request": request,
            "display": dict(self._payload.get("display") or {}),
        }

    def _run_snapshot(self, backend: BackgroundJobBackend) -> dict[str, Any]:
        self.progress.emit("Creating snapshot")
        project_id = str(self._payload["project_id"])
        kind = self._payload.get("kind")
        snapshot = backend.create_snapshot(
            project_id,
            kind=str(kind) if kind else None,
        )
        result: dict[str, Any] = {
            "project_id": project_id,
            "snapshot": snapshot,
        }
        history = self._payload.get("history")
        if isinstance(history, dict):
            try:
                result.update(self._run_history(backend))
            # The snapshot is already committed; preserve that successful result.
            # pylint: disable-next=broad-exception-caught
            except Exception as exc:  # snapshot already committed
                logger.warning(
                    "Snapshot succeeded but history refresh failed",
                    exc_info=True,
                )
                result["history_error"] = str(exc)
        return result

    def _execute(self, backend: BackgroundJobBackend) -> object:
        if self._kind == "sync":
            return self._run_sync(backend)
        if self._kind == "automatic_sync":
            return self._run_automatic_sync(backend)
        if self._kind == "history":
            return self._run_history(backend)
        if self._kind == "snapshot":
            return self._run_snapshot(backend)
        raise ValueError(f"Unknown background job: {self._kind!r}")

    @Slot()
    def run(self) -> None:
        """Create worker-owned dependencies, execute, and release them."""
        backend: BackgroundJobBackend | None = None
        try:
            if self._is_cancelled():
                self.cancelled.emit(self._kind)
                return
            backend = self._backend_factory()
            result = self._execute(backend)
            if isinstance(result, dict) and result.get("state") == SyncState.CANCELLED:
                self.cancelled.emit(self._kind)
            else:
                self.succeeded.emit(self._kind, result)
        # Nothing may escape the worker-thread boundary into Qt's event loop.
        # pylint: disable-next=broad-exception-caught
        except Exception as exc:  # thread boundary
            if self._kind == "automatic_sync":
                logger.info("Automatic synchronization attempt failed: %s", exc)
            else:
                logger.exception("Background %s job failed", self._kind)
            self.failed.emit(self._kind, str(exc))
        finally:
            if backend is not None and self._owns_backend:
                try:
                    backend.close()
                # Cleanup must not discard the completed job result.
                # pylint: disable-next=broad-exception-caught
                except Exception:  # best-effort cleanup
                    logger.warning(
                        "Could not close background backend",
                        exc_info=True,
                    )
            self.finished.emit()


class BackgroundJobRunner(QObject):
    """Own one-shot worker threads and marshal their results to the GUI thread."""

    busy_changed = Signal(bool, str)
    progress_changed = Signal(str)

    def __init__(
        self,
        backend_factory: BackendFactory,
        *,
        owns_backend: bool,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._backend_factory = backend_factory
        self._owns_backend = owns_backend
        self._thread: QThread | None = None
        self._worker: _BackgroundJobWorker | None = None
        self._cancel_event: threading.Event | None = None
        self._on_success: SuccessCallback | None = None
        self._on_failure: FailureCallback | None = None
        self._on_cancelled: CancelledCallback | None = None
        self._shutting_down = False

    @property
    def is_busy(self) -> bool:
        # Reserving a thread is already busy, even in the narrow interval
        # before QThread.start() marks it as running.
        return self._thread is not None

    def start(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        on_success: SuccessCallback | None = None,
        on_failure: FailureCallback | None = None,
        on_cancelled: CancelledCallback | None = None,
    ) -> bool:
        """Start a job, returning false when another job already owns the worker."""
        if self._shutting_down or self.is_busy:
            return False

        cancel_event = threading.Event()
        thread = QThread(self)
        thread.setObjectName(f"riskapp-{kind}-worker")
        worker = _BackgroundJobWorker(
            self._backend_factory,
            owns_backend=self._owns_backend,
            kind=kind,
            payload=payload,
            cancel_event=cancel_event,
        )
        worker.moveToThread(thread)

        self._thread = thread
        self._worker = worker
        self._cancel_event = cancel_event
        self._on_success = on_success
        self._on_failure = on_failure
        self._on_cancelled = on_cancelled

        # PySide exposes these bound signals dynamically to Pylint.
        # pylint: disable=no-member
        thread.started.connect(worker.run)
        worker.progress.connect(self.progress_changed)
        worker.succeeded.connect(self._handle_success)
        worker.failed.connect(self._handle_failure)
        worker.cancelled.connect(self._handle_cancelled)
        # Delete the worker in its own thread after run() has returned, then
        # stop the event loop. Waiting for destruction avoids a PySide race
        # between a still-unwinding Python slot and QThread shutdown.
        worker.finished.connect(worker.deleteLater)
        worker.destroyed.connect(
            thread.quit,
            Qt.ConnectionType.DirectConnection,
        )
        thread.finished.connect(self._handle_thread_finished)
        # pylint: enable=no-member

        self.busy_changed.emit(True, kind)
        thread.start()
        return True

    def cancel(self) -> None:
        """Request cooperative cancellation of the active job."""
        if self._cancel_event is not None:
            self._cancel_event.set()
        if self._thread is not None:
            self._thread.requestInterruption()
        if self.is_busy:
            self.progress_changed.emit("Cancelling after the current request…")

    def shutdown(self, *, timeout_ms: int = 8_000) -> bool:
        """Cancel active work and wait for its thread before window destruction."""
        self._shutting_down = True
        self.cancel()
        thread = self._thread
        if thread is None or not thread.isRunning():
            return True
        stopped = bool(thread.wait(timeout_ms))
        if not stopped:
            # closeEvent() will be ignored, so let the eventual result restore
            # the UI instead of leaving the still-open window permanently busy.
            self._shutting_down = False
        return stopped

    @Slot(str, object)
    def _handle_success(self, _kind: str, result: object) -> None:
        if not self._shutting_down and self._on_success is not None:
            self._on_success(result)

    @Slot(str, str)
    def _handle_failure(self, _kind: str, message: str) -> None:
        if not self._shutting_down and self._on_failure is not None:
            self._on_failure(message)

    @Slot(str)
    def _handle_cancelled(self, _kind: str) -> None:
        if not self._shutting_down and self._on_cancelled is not None:
            self._on_cancelled()

    @Slot()
    def _handle_thread_finished(self) -> None:
        thread = self._thread
        self._thread = None
        self._worker = None
        self._cancel_event = None
        self._on_success = None
        self._on_failure = None
        self._on_cancelled = None
        if thread is not None:
            thread.deleteLater()
        if not self._shutting_down:
            self.busy_changed.emit(False, "")
