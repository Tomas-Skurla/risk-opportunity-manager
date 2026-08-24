from __future__ import annotations


def recalculate_item_scores(item) -> None:
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
