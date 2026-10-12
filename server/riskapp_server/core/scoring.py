"""Derived score fields for risks, opportunities and assessments."""

from __future__ import annotations

from typing import Any

_IMPACT_DIMENSIONS = ("impact_cost", "impact_time", "impact_scope", "impact_quality")


def recalculate_item_scores(item: Any) -> None:
    """Set impact to the highest impact dimension and score to probability x impact.

    The sync engine calls this for every row it writes, so rows without
    probability and impact, such as actions and tickets, are left unchanged.
    """

    if not (hasattr(item, "probability") and hasattr(item, "impact")):
        return
    dimensions = [getattr(item, key, None) for key in _IMPACT_DIMENSIONS]
    valid = [int(value) for value in dimensions if value is not None]
    if valid:
        item.impact = max(valid)

    item.score = int(item.probability or 1) * int(item.impact or 1)
