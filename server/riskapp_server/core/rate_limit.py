"""In-memory sliding-window limiter for /login."""

from __future__ import annotations

import threading
import time
from collections import deque
from math import ceil


class InMemorySlidingWindowLimiter:
    _OVERFLOW_KEY = "__rate_limit_overflow__"

    def __init__(self, *, limit: int, window_s: int, max_keys: int = 10_000) -> None:
        self.limit = int(limit)
        self.window_s = int(window_s)
        self.max_keys = int(max_keys)
        if self.limit < 1 or self.window_s < 1 or self.max_keys < 1:
            raise ValueError("limit, window_s, and max_keys must all be positive")
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}
        self._checks = 0

    def reset(self) -> None:
        """Clear all tracked keys (useful for tests)."""
        with self._lock:
            self._hits.clear()
            self._checks = 0

    def _prune_stale_keys(self, cutoff: float) -> None:
        stale = [
            key for key, hits in self._hits.items() if not hits or hits[-1] < cutoff
        ]
        for key in stale:
            self._hits.pop(key, None)

    def check(self, key: str) -> tuple[bool, int]:
        """Check if the key is allowed.

        Returns:
            (allowed, retry_after_seconds)
        """
        now = time.monotonic()
        with self._lock:
            cutoff = now - self.window_s
            self._checks += 1
            if self._checks % 256 == 0:
                self._prune_stale_keys(cutoff)

            # Bound attacker-controlled cardinality. Once the cap is reached,
            # previously unseen keys share a conservative overflow bucket.
            if (
                key not in self._hits
                and key != self._OVERFLOW_KEY
                and len(self._hits) >= self.max_keys - 1
            ):
                key = self._OVERFLOW_KEY

            q = self._hits.get(key)
            if q is None:
                q = deque()
                self._hits[key] = q

            while q and q[0] < cutoff:
                q.popleft()

            if len(q) >= self.limit:
                retry_after = max(1, ceil(q[0] + self.window_s - now))
                return False, retry_after

            q.append(now)
            return True, 0
