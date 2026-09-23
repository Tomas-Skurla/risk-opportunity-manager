"""Run blocking backend jobs without blocking the Qt event loop."""

from __future__ import annotations

import inspect
import logging
import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

logger = logging.getLogger(__name__)

BackendFactory = Callable[[], Any]
SuccessCallback = Callable[[object], None]
FailureCallback = Callable[[str], None]
CancelledCallback = Callable[[], None]


def _accepts_keyword(fn: Callable[..., object], keyword: str) -> bool:
    """Return whether a callable accepts a named keyword argument."""
    try:
        parameters = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        or parameter.name == keyword
        for parameter in parameters
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

    def _sync_project(self, backend: Any, project_id: str) -> dict[str, Any]:
        method = backend.sync_project
        kwargs: dict[str, object] = {}
        if _accepts_keyword(method, "should_cancel"):
            kwargs["should_cancel"] = self._is_cancelled
        if _accepts_keyword(method, "progress"):
            kwargs["progress"] = self.progress.emit
        result = method(project_id, **kwargs)
        if not isinstance(result, dict):
            raise RuntimeError("Synchronization returned an invalid result")
        return result

    def _run_sync(self, backend: Any) -> dict[str, Any]:
        result = self._sync_project(
            backend,
            str(self._payload["project_id"]),
        )

        # A local project promotion changes the sidebar identity. Fetch the
        # authoritative visible project list here, not from the GUI thread.
        if result.get("project_id_migrated_to") and not self._is_cancelled():
            try:
                self.progress.emit("Refreshing project list")
                result["_visible_projects"] = list(backend.list_projects() or [])
            # Refresh is secondary and must not turn a successful sync into failure.
            # pylint: disable-next=broad-exception-caught
            except Exception:  # noqa: BLE001 - sync itself already succeeded
                logger.warning(
                    "Could not refresh projects after synchronization",
                    exc_info=True,
                )
        return result

    def _run_automatic_sync(self, backend: Any) -> dict[str, Any]:
        """Synchronize every visible, syncable project in one worker session."""
        self.progress.emit("Checking projects for automatic sync")
        list_projects = getattr(
            backend,
            "list_sync_projects",
            backend.list_projects,
        )
        projects = list(list_projects() or [])
        syncable = [
            project
            for project in projects
            if getattr(project, "id", None)
            and not (
                str(getattr(project, "id", "")).startswith("local-")
                and not getattr(project, "created_by", "")
            )
        ]
        summaries: list[dict[str, Any]] = []
        migrations: dict[str, str] = {}

        for index, project in enumerate(syncable, start=1):
            if self._is_cancelled():
                return {
                    "state": "cancelled",
                    "cancelled": True,
                    "projects": summaries,
                }
            project_id = str(project.id)
            project_name = str(getattr(project, "name", "") or project_id)
            self.progress.emit(
                f"Automatically synchronizing {index}/{len(syncable)}: "
                f"{project_name}"
            )
            try:
                summary = self._sync_project(backend, project_id)
            # Projects are independent synchronization units. A corrupt local
            # row or project-specific server failure must not starve every
            # project later in this automatic pass.
            # pylint: disable-next=broad-exception-caught
            except Exception:  # noqa: BLE001 - isolate this project and continue
                logger.exception(
                    "Automatic synchronization failed for project %s (%s)",
                    project_id,
                    project_name,
                )
                summary = {
                    "state": "retry_wait",
                    "sync_error": {
                        "reason": "project_sync_failed",
                        "failure_kind": "transient",
                        "retryable": True,
                        "request_failed": False,
                    },
                }
            summary.setdefault("project_id", project_id)
            summaries.append(summary)
            migrated_to = summary.get("project_id_migrated_to")
            if migrated_to:
                migrations[project_id] = str(migrated_to)
            sync_error = summary.get("sync_error")
            if (
                str(summary.get("state") or "")
                in {"authentication_required", "retry_wait"}
                and isinstance(sync_error, dict)
                and sync_error.get("request_failed")
            ):
                # Transport and authentication failures normally affect every
                # project. Stop this pass rather than hammering the same broken
                # connection once per project; the scheduler will retry later.
                break

        if migrations and not self._is_cancelled():
            self.progress.emit("Refreshing project list")
            projects = list(list_projects() or [])

        states = {str(item.get("state") or "complete") for item in summaries}
        if "authentication_required" in states:
            state = "authentication_required"
        elif "retry_wait" in states:
            state = "retry_wait"
        elif states - {"complete"}:
            state = "attention_required"
        else:
            state = "complete"

        retry_values = sorted(
            str(value)
            for value in (item.get("next_retry_at") for item in summaries)
            if value
        )
        result: dict[str, Any] = {
            "state": state,
            "projects": summaries,
            "project_id_migrations": migrations,
            "next_retry_at": retry_values[0] if retry_values else None,
            "_visible_projects": projects,
        }
        if self._payload.get("export_remote") and state != "authentication_required":
            export_remote = getattr(backend, "export_authenticated_remote", None)
            if callable(export_remote):
                authenticated_remote = export_remote()
                if authenticated_remote is not None:
                    result["_authenticated_remote"] = authenticated_remote
        return result

    def _run_history(self, backend: Any) -> dict[str, Any]:
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

    def _run_snapshot(self, backend: Any) -> dict[str, Any]:
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
            except Exception as exc:  # noqa: BLE001 - snapshot already committed
                logger.warning(
                    "Snapshot succeeded but history refresh failed",
                    exc_info=True,
                )
                result["history_error"] = str(exc)
        return result

    def _execute(self, backend: Any) -> object:
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
        backend: Any | None = None
        try:
            if self._is_cancelled():
                self.cancelled.emit(self._kind)
                return
            backend = self._backend_factory()
            result = self._execute(backend)
            if isinstance(result, dict) and result.get("state") == "cancelled":
                self.cancelled.emit(self._kind)
            else:
                self.succeeded.emit(self._kind, result)
        # Nothing may escape the worker-thread boundary into Qt's event loop.
        # pylint: disable-next=broad-exception-caught
        except Exception as exc:  # noqa: BLE001 - thread boundary
            if self._kind == "automatic_sync":
                logger.info("Automatic synchronization attempt failed: %s", exc)
            else:
                logger.exception("Background %s job failed", self._kind)
            self.failed.emit(self._kind, str(exc))
        finally:
            if backend is not None and self._owns_backend:
                store = getattr(backend, "store", None)
                close = getattr(store, "close", None)
                if callable(close):
                    try:
                        close()  # pylint: disable=not-callable
                    # Store cleanup is best-effort after the job result is known.
                    # pylint: disable-next=broad-exception-caught
                    except Exception:  # noqa: BLE001 - best-effort cleanup
                        logger.warning(
                            "Could not close background local store",
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
