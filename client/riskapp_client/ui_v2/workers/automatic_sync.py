"""Qt scheduling policy for reliable automatic synchronization."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta

from PySide6.QtCore import QObject, QTimer, Slot

_TRANSIENT_STATES = frozenset(
    {
        "authentication_required",
        "failed",
        "offline",
        "retry_wait",
    }
)
_MAX_QT_TIMER_MS = 2_147_483_647


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _retry_delay_seconds(value: object, *, now: datetime) -> float | None:
    """Return the delay until an ISO-8601 retry timestamp."""
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        retry_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    else:
        retry_at = retry_at.astimezone(UTC)
    return max(0.0, (retry_at - now.astimezone(UTC)).total_seconds())


class AutomaticSyncScheduler(QObject):
    """Trigger one automatic job at a time without performing any I/O itself."""

    def __init__(
        self,
        start_job: Callable[[], bool],
        *,
        interval_seconds: int,
        initial_delay_seconds: int = 5,
        max_backoff_seconds: int = 300,
        busy_retry_seconds: int = 2,
        clock: Callable[[], datetime] = _utc_now,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._start_job = start_job
        self._interval_seconds = max(0, int(interval_seconds))
        self._initial_delay_seconds = max(0, int(initial_delay_seconds))
        self._max_backoff_seconds = max(5, int(max_backoff_seconds))
        self._busy_retry_seconds = max(1, int(busy_retry_seconds))
        self._clock = clock
        self._running = False
        self._job_in_flight = False
        self._failure_count = 0
        self._not_before: datetime | None = None
        self._last_delay_ms: int | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        # PySide exposes bound signals dynamically to Pylint.
        # pylint: disable-next=no-member
        self._timer.timeout.connect(self._on_timeout)

    @property
    def enabled(self) -> bool:
        return self._interval_seconds > 0

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def job_in_flight(self) -> bool:
        return self._job_in_flight

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def last_delay_ms(self) -> int | None:
        """Expose the most recently scheduled delay for diagnostics and tests."""
        return self._last_delay_ms

    def start(self) -> None:
        if not self.enabled or self._running:
            return
        self._running = True
        self._schedule(self._initial_delay_seconds)

    def stop(self) -> None:
        self._running = False
        self._job_in_flight = False
        self._timer.stop()

    def request_soon(self, *, delay_seconds: int = 1) -> None:
        """Debounce a local-change trigger while preserving active backoff."""
        if not self._running or self._job_in_flight:
            return
        delay = max(0.0, float(delay_seconds))
        if self._not_before is not None:
            delay = max(delay, (self._not_before - self._clock()).total_seconds())
        self._schedule(delay, only_if_sooner=True)

    def observe_result(self, result: object) -> None:
        """Reschedule from a manual sync result without claiming a worker job."""
        self._finish(result)

    def job_succeeded(self, result: object) -> None:
        self._job_in_flight = False
        self._finish(result)

    def job_failed(self) -> None:
        self._job_in_flight = False
        if not self._running:
            return
        self._failure_count += 1
        delay = self._backoff_seconds()
        self._not_before = self._clock() + timedelta(seconds=delay)
        self._schedule(delay)

    def _finish(self, result: object) -> None:
        if not self._running:
            return
        state = "failed"
        next_retry_at: object = None
        if isinstance(result, Mapping):
            state = str(result.get("state") or "complete")
            next_retry_at = result.get("next_retry_at")
        if state == "complete" and next_retry_at:
            state = "retry_wait"

        if state in _TRANSIENT_STATES:
            self._failure_count += 1
            delay = self._backoff_seconds()
            retry_delay = _retry_delay_seconds(
                next_retry_at,
                now=self._clock(),
            )
            if retry_delay is not None:
                delay = max(delay, retry_delay)
            self._not_before = self._clock() + timedelta(seconds=delay)
            self._schedule(delay)
            return

        self._failure_count = 0
        self._not_before = None
        self._schedule(self._interval_seconds)

    def _backoff_seconds(self) -> float:
        exponent = min(16, max(0, self._failure_count - 1))
        return float(min(5 * (2**exponent), self._max_backoff_seconds))

    def _schedule(self, seconds: float, *, only_if_sooner: bool = False) -> None:
        if not self._running:
            return
        delay_ms = min(
            _MAX_QT_TIMER_MS,
            max(1, int(max(0.0, seconds) * 1000)),
        )
        if only_if_sooner and self._timer.isActive():
            remaining = self._timer.remainingTime()
            if remaining >= 0 and remaining <= delay_ms:
                return
        self._last_delay_ms = delay_ms
        self._timer.start(delay_ms)

    @Slot()
    def _on_timeout(self) -> None:
        if not self._running or self._job_in_flight:
            return
        if self._start_job():
            self._job_in_flight = True
            return
        # A manual snapshot, an unsaved editor, or a still-unwinding worker can
        # temporarily hold the single-flight runner. This is not a network
        # failure and therefore must not increase the exponential backoff.
        self._schedule(self._busy_retry_seconds)
