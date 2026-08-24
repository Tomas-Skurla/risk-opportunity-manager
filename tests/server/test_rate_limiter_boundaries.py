"""Deterministic sliding-window and cardinality-limit tests."""

from __future__ import annotations

from collections import deque

import pytest


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0, "window_s": 1, "max_keys": 1},
        {"limit": 1, "window_s": 0, "max_keys": 1},
        {"limit": 1, "window_s": 1, "max_keys": 0},
    ],
)
def test_limiter_rejects_non_positive_configuration(kwargs) -> None:
    from riskapp_server.core.rate_limit import InMemorySlidingWindowLimiter

    with pytest.raises(ValueError, match="must all be positive"):
        InMemorySlidingWindowLimiter(**kwargs)


def test_limiter_expires_hits_and_returns_retry_after(monkeypatch) -> None:
    import riskapp_server.core.rate_limit as rate_limit

    now = [100.0]
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: now[0])
    limiter = rate_limit.InMemorySlidingWindowLimiter(
        limit=2, window_s=10, max_keys=10
    )

    assert limiter.check("account") == (True, 0)
    now[0] = 101.0
    assert limiter.check("account") == (True, 0)
    now[0] = 102.0
    allowed, retry_after = limiter.check("account")
    assert allowed is False
    assert retry_after == 8

    now[0] = 111.5
    assert limiter.check("account") == (True, 0)
    limiter.reset()
    assert limiter._hits == {}


def test_limiter_prunes_stale_keys_and_bounds_untrusted_cardinality(
    monkeypatch,
) -> None:
    import riskapp_server.core.rate_limit as rate_limit

    now = [100.0]
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: now[0])
    limiter = rate_limit.InMemorySlidingWindowLimiter(
        limit=1, window_s=10, max_keys=3
    )
    limiter._hits = {"empty": deque(), "stale": deque([1.0])}
    limiter._checks = 255

    assert limiter.check("fresh") == (True, 0)
    assert set(limiter._hits) == {"fresh"}
    assert limiter.check("second") == (True, 0)
    assert limiter.check("third") == (True, 0)
    allowed, retry_after = limiter.check("fourth")
    assert allowed is False
    assert retry_after == 10
    assert "third" not in limiter._hits
    assert rate_limit.InMemorySlidingWindowLimiter._OVERFLOW_KEY in limiter._hits
