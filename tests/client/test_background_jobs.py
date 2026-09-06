"""Thread-boundary tests for blocking desktop backend jobs."""

from __future__ import annotations

import threading

from PySide6.QtCore import QTimer
from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore
from riskapp_client.domain.domain_models import Project
from riskapp_client.services.offline_first_facade import OfflineFirstBackend
from riskapp_client.ui_v2.workers import BackgroundJobRunner
from riskapp_client.ui_v2.workers import background_jobs as jobs


def test_worker_dispatches_sync_progress_and_project_migration(qtbot) -> None:
    progress_messages: list[str] = []
    outcomes: list[tuple[str, object]] = []

    class Backend:
        def sync_project(self, project_id, *, should_cancel, progress):
            assert project_id == "local-1"
            assert not should_cancel()
            progress("Pushing changes")
            return {
                "state": "complete",
                "project_id_migrated_to": "project-1",
            }

        @staticmethod
        def list_projects():
            return [Project("project-1", "Published")]

    worker = jobs._BackgroundJobWorker(
        Backend,
        owns_backend=False,
        kind="sync",
        payload={"project_id": "local-1"},
        cancel_event=threading.Event(),
    )
    worker.progress.connect(progress_messages.append)
    worker.succeeded.connect(lambda kind, result: outcomes.append((kind, result)))

    worker.run()

    assert progress_messages == ["Pushing changes", "Refreshing project list"]
    assert outcomes[0][0] == "sync"
    result = outcomes[0][1]
    assert isinstance(result, dict)
    assert result["_visible_projects"] == [Project("project-1", "Published")]


def test_worker_dispatches_history_and_preserves_snapshot_after_history_error(
    qtbot,
) -> None:
    outcomes: list[tuple[str, object]] = []

    class Backend:
        @staticmethod
        def create_snapshot(project_id, *, kind=None):
            return {"id": "snapshot-1", "project_id": project_id, "kind": kind}

        @staticmethod
        def top_history(_project_id, **_filters):
            raise RuntimeError("history unavailable")

    worker = jobs._BackgroundJobWorker(
        Backend,
        owns_backend=False,
        kind="snapshot",
        payload={
            "project_id": "project-1",
            "kind": "risks",
            "history": {"kind": "risks", "limit": 5},
            "display": {"period": "All"},
        },
        cancel_event=threading.Event(),
    )
    worker.succeeded.connect(lambda kind, result: outcomes.append((kind, result)))

    worker.run()

    assert outcomes[0][0] == "snapshot"
    result = outcomes[0][1]
    assert isinstance(result, dict)
    assert result["snapshot"]["id"] == "snapshot-1"
    assert result["history_error"] == "history unavailable"


def test_worker_reports_prestart_cancellation_invalid_results_and_unknown_jobs(
    qtbot,
) -> None:
    factory_called = False
    cancelled: list[str] = []

    def factory():
        nonlocal factory_called
        factory_called = True
        return object()

    cancel_event = threading.Event()
    cancel_event.set()
    worker = jobs._BackgroundJobWorker(
        factory,
        owns_backend=False,
        kind="sync",
        payload={"project_id": "project-1"},
        cancel_event=cancel_event,
    )
    worker.cancelled.connect(cancelled.append)
    worker.run()

    assert cancelled == ["sync"]
    assert not factory_called

    class InvalidBackend:
        @staticmethod
        def sync_project(_project_id):
            return "invalid"

    failures: list[tuple[str, str]] = []
    invalid = jobs._BackgroundJobWorker(
        InvalidBackend,
        owns_backend=False,
        kind="sync",
        payload={"project_id": "project-1"},
        cancel_event=threading.Event(),
    )
    invalid.failed.connect(lambda kind, message: failures.append((kind, message)))
    invalid.run()

    unknown = jobs._BackgroundJobWorker(
        object,
        owns_backend=False,
        kind="unknown",
        payload={},
        cancel_event=threading.Event(),
    )
    unknown.failed.connect(lambda kind, message: failures.append((kind, message)))
    unknown.run()

    assert failures == [
        ("sync", "Synchronization returned an invalid result"),
        ("unknown", "Unknown background job: 'unknown'"),
    ]


def test_runner_constructs_uses_and_closes_backend_in_worker_thread(qtbot) -> None:
    main_thread_id = threading.get_ident()
    release = threading.Event()
    started = threading.Event()
    calls: dict[str, int] = {}
    results: list[tuple[int, object]] = []
    progress: list[str] = []
    event_loop_ticks: list[int] = []

    class Store:
        def close(self) -> None:
            calls["close"] = threading.get_ident()

    class Backend:
        store = Store()

        def sync_project(self, project_id, *, should_cancel, progress):
            assert project_id == "project-1"
            calls["sync"] = threading.get_ident()
            progress("Waiting in test backend")
            started.set()
            assert release.wait(timeout=2)
            assert not should_cancel()
            return {"state": "complete", "pushed": 0}

    def backend_factory():
        calls["factory"] = threading.get_ident()
        return Backend()

    runner = BackgroundJobRunner(backend_factory, owns_backend=True)
    runner.progress_changed.connect(progress.append)
    assert runner.start(
        "sync",
        {"project_id": "project-1"},
        on_success=lambda result: results.append((threading.get_ident(), result)),
    )

    qtbot.waitUntil(started.is_set)
    QTimer.singleShot(0, lambda: event_loop_ticks.append(threading.get_ident()))
    qtbot.waitUntil(lambda: bool(event_loop_ticks))
    assert runner.is_busy
    assert event_loop_ticks == [main_thread_id]

    release.set()
    qtbot.waitUntil(lambda: bool(results) and not runner.is_busy)

    assert results == [
        (main_thread_id, {"state": "complete", "pushed": 0})
    ]
    assert progress == ["Waiting in test backend"]
    assert calls["factory"] == calls["sync"] == calls["close"]
    assert calls["factory"] != main_thread_id
    assert runner.shutdown()


def test_runner_is_single_flight_and_cancels_cooperatively(qtbot) -> None:
    main_thread_id = threading.get_ident()
    started = threading.Event()
    cancelled: list[int] = []

    class Backend:
        def sync_project(self, _project_id, *, should_cancel, progress):
            started.set()
            while not should_cancel():
                threading.Event().wait(0.005)
            progress("Cancellation observed")
            return {"state": "cancelled", "cancelled": True}

    runner = BackgroundJobRunner(Backend, owns_backend=False)
    assert runner.start(
        "sync",
        {"project_id": "project-1"},
        on_cancelled=lambda: cancelled.append(threading.get_ident()),
    )
    assert not runner.start("history", {"project_id": "project-1"})

    qtbot.waitUntil(started.is_set)
    runner.cancel()
    qtbot.waitUntil(lambda: bool(cancelled) and not runner.is_busy)

    assert cancelled == [main_thread_id]
    assert runner.shutdown()


def test_failed_shutdown_wait_restores_runner_until_job_finishes(qtbot) -> None:
    started = threading.Event()
    release = threading.Event()
    results: list[object] = []

    class Backend:
        def sync_project(self, _project_id):
            started.set()
            assert release.wait(timeout=2)
            return {"state": "complete"}

    runner = BackgroundJobRunner(Backend, owns_backend=False)
    assert runner.start(
        "sync",
        {"project_id": "project-1"},
        on_success=results.append,
    )
    qtbot.waitUntil(started.is_set)

    assert not runner.shutdown(timeout_ms=1)
    release.set()
    qtbot.waitUntil(lambda: bool(results) and not runner.is_busy)

    assert results == [{"state": "complete"}]
    assert runner.shutdown()


def test_snapshot_and_history_requests_run_in_worker_thread(qtbot) -> None:
    main_thread_id = threading.get_ident()
    calls: list[tuple[str, int, object]] = []
    results: list[dict] = []

    class Backend:
        def create_snapshot(self, project_id, *, kind=None):
            calls.append(("snapshot", threading.get_ident(), kind))
            return {"id": "snapshot-1", "project_id": project_id}

        def top_history(self, project_id, **filters):
            calls.append(("history", threading.get_ident(), filters))
            return [{"captured_at": "2026-09-06T12:00:00", "top": []}]

    runner = BackgroundJobRunner(Backend, owns_backend=False)
    assert runner.start(
        "snapshot",
        {
            "project_id": "project-1",
            "kind": "risks",
            "history": {"kind": "risks", "limit": 10},
            "display": {"kind": "risks", "limit": 10, "period": "All"},
        },
        on_success=results.append,
    )
    qtbot.waitUntil(lambda: bool(results) and not runner.is_busy)

    assert [call[0] for call in calls] == ["snapshot", "history"]
    assert all(call[1] != main_thread_id for call in calls)
    assert results[0]["snapshot"]["id"] == "snapshot-1"
    assert len(results[0]["history"]) == 1
    assert runner.shutdown()


def test_offline_facade_worker_uses_a_separate_sqlite_connection(
    tmp_path, qtbot
) -> None:
    main_thread_id = threading.get_ident()
    calls: dict[str, int] = {}
    results: list[dict] = []

    class Remote:
        def fork_authenticated(self):
            calls["fork"] = threading.get_ident()
            return self

        def sync_pull(self, project_id, _since):
            assert project_id == "project-1"
            calls["pull"] = threading.get_ident()
            return {
                "server_time": "2026-09-06T12:00:00",
                "risks": [],
                "opportunities": [],
                "actions": [],
                "assessments": [],
                "helpdesk_tickets": [],
            }

    store = LocalStore(str(tmp_path / "local.db"))
    store.upsert_projects([Project("project-1", "Project")])
    backend = OfflineFirstBackend(store, Remote())
    runner = BackgroundJobRunner(
        backend.create_background_backend,
        owns_backend=True,
    )
    try:
        assert runner.start(
            "sync",
            {"project_id": "project-1"},
            on_success=results.append,
        )
        qtbot.waitUntil(lambda: bool(results) and not runner.is_busy)

        assert results[0]["state"] == "complete"
        assert calls["fork"] == calls["pull"]
        assert calls["fork"] != main_thread_id
        # The original connection remains owned and usable by the GUI thread.
        assert store.get_project("project-1") is not None
    finally:
        runner.shutdown()
        store.close()
