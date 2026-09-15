from __future__ import annotations

from typing import Protocol

class _ScoredItem(Protocol):
    """Writable score fields shared by items and assessments."""

    probability: int
    impact: int
    score: int


def recalculate_item_scores(item: _ScoredItem) -> None:
    if not (hasattr(item, "probability") and hasattr(item, "impact")):
        return

    dims = (
        getattr(item, "impact_cost", None),
        getattr(item, "impact_time", None),
        getattr(item, "impact_scope", None),
        getattr(item, "impact_quality", None),
    )
    valid = [int(v) for v in dims if v is not None]
    if valid:
        item.impact = max(valid)

    item.score = int(item.probability or 1) * int(item.impact or 1)
