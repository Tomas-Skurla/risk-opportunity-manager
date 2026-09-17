"""Automatic synchronization scheduling and backoff policy."""

from __future__ import annotations

from datetime import UTC, datetime

from riskapp_client.ui_v2.workers.automatic_sync import (
    AutomaticSyncScheduler,
    _retry_delay_seconds,
)

# Scheduling policy is deliberately tested through its small private seams.
# pylint: disable=protected-access


def test_retry_timestamp_parsing_handles_empty_invalid_and_naive_values() -> None:
    now = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)

    assert _retry_delay_seconds(None, now=now) is None
    assert _retry_delay_seconds("invalid", now=now) is None
    assert _retry_delay_seconds("2026-09-16T12:00:09", now=now) == 9
    assert _retry_delay_seconds("2026-09-16T11:59:00Z", now=now) == 0


def test_scheduler_starts_once_and_returns_to_regular_interval(qtbot) -> None:
    starts: list[str] = []

    def start_job() -> bool:
        starts.append("started")
        return True

    scheduler = AutomaticSyncScheduler(
        start_job,
        interval_seconds=60,
        initial_delay_seconds=0,
    )

    scheduler.start()
    qtbot.waitUntil(lambda: starts == ["started"])
    assert scheduler.job_in_flight

    scheduler.job_succeeded({"state": "complete"})

    assert not scheduler.job_in_flight
    assert scheduler.failure_count == 0
    assert scheduler.last_delay_ms == 60_000

    scheduler.request_soon()
    assert scheduler.last_delay_ms == 1_000

    # Repeated starts and requests during an active job remain single-flight.
    scheduler.start()
    scheduler._on_timeout()
    assert scheduler.job_in_flight
    scheduler.request_soon()
    assert scheduler.last_delay_ms == 1_000
    scheduler.stop()


def test_scheduler_uses_persistent_retry_time_and_preserves_backoff(qtbot) -> None:
    now = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    starts: list[str] = []

    def start_job() -> bool:
        starts.append("started")
        return True

    scheduler = AutomaticSyncScheduler(
        start_job,
        interval_seconds=60,
        initial_delay_seconds=0,
        max_backoff_seconds=300,
        clock=lambda: now,
    )
    scheduler.start()
    qtbot.waitUntil(lambda: bool(starts))

    scheduler.job_succeeded(
        {
            "state": "retry_wait",
            "next_retry_at": "2026-09-16T12:00:30+00:00",
        }
    )
    assert scheduler.failure_count == 1
    assert scheduler.last_delay_ms == 30_000

    scheduler.request_soon()
    assert scheduler.last_delay_ms == 30_000

    scheduler.job_failed()
    assert scheduler.failure_count == 2
    assert scheduler.last_delay_ms == 10_000
    scheduler.stop()


def test_manual_results_and_malformed_results_share_scheduler_policy(qtbot) -> None:
    scheduler = AutomaticSyncScheduler(
        lambda: True,
        interval_seconds=45,
        initial_delay_seconds=0,
    )
    scheduler.request_soon()
    scheduler.start()
    qtbot.waitUntil(lambda: scheduler.job_in_flight)

    scheduler.observe_result({"state": "attention_required"})
    assert scheduler.failure_count == 0
    assert scheduler.last_delay_ms == 45_000

    scheduler.job_succeeded(object())
    assert scheduler.failure_count == 1
    assert scheduler.last_delay_ms == 5_000

    scheduler.stop()
    scheduler.job_failed()
    assert scheduler.failure_count == 1


def test_busy_runner_retries_without_counting_network_failure(qtbot) -> None:
    attempts: list[str] = []

    def busy() -> bool:
        attempts.append("busy")
        return False

    scheduler = AutomaticSyncScheduler(
        busy,
        interval_seconds=60,
        initial_delay_seconds=0,
        busy_retry_seconds=2,
    )
    scheduler.start()
    qtbot.waitUntil(lambda: bool(attempts))

    assert scheduler.failure_count == 0
    assert scheduler.last_delay_ms == 2_000
    scheduler.stop()


def test_disabled_scheduler_never_starts(qtbot) -> None:
    starts: list[str] = []

    def start_job() -> bool:
        starts.append("started")
        return True

    scheduler = AutomaticSyncScheduler(
        start_job,
        interval_seconds=0,
    )

    scheduler.start()
    qtbot.wait(5)

    assert not scheduler.is_running
    assert not starts
