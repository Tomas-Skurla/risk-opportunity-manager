"""Filtering helpers for risks and opportunities (client-side)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from riskapp_client.domain.domain_models import Opportunity, Risk, ScoredEntity


def parse_date(value: str) -> datetime | None:
    """Parse YYYY-MM-DD or ISO datetime; return None if invalid."""
    text = (value or "").strip()
    if not text:
        return None
    try:
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            return datetime.fromisoformat(text + "T00:00:00")
        return datetime.fromisoformat(text)
    except ValueError:
        return None


ANY_STATUS = "(any)"
MAX_SCORE = 999_999


@dataclass(frozen=True)
class ScoredFilterCriteria:
    """Shared filter criteria for any scored entity."""

    search: str = ""
    min_score: int = 0
    max_score: int = MAX_SCORE
    status: str = ANY_STATUS
    category_contains: str = ""
    # Owner filtering: an exact owner, or only unassigned items.
    owner_user_id: str | None = None
    owner_unassigned: bool = False
    identified_from: datetime | None = None
    identified_to: datetime | None = None


def criteria_from_report_filters(filters: Mapping[str, Any]) -> ScoredFilterCriteria:
    """Read the server's report query parameters; ``to_date`` includes that day."""
    identified_to = parse_date(str(filters.get("to_date") or ""))
    if identified_to:
        identified_to = identified_to.replace(hour=23, minute=59, second=59)
    owner_user_id = filters.get("owner_user_id")
    return ScoredFilterCriteria(
        search=str(filters.get("search") or ""),
        min_score=int(filters.get("min_score") or 0),
        max_score=int(filters.get("max_score") or MAX_SCORE),
        status=str(filters.get("status") or ANY_STATUS),
        category_contains=str(filters.get("category") or ""),
        owner_user_id=str(owner_user_id) if owner_user_id else None,
        owner_unassigned=bool(filters.get("owner_unassigned")),
        identified_from=parse_date(str(filters.get("from_date") or "")),
        identified_to=identified_to,
    )


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


def _search_text(item: ScoredEntity) -> str:
    fields = (item.title, item.code, item.category, item.description)
    return " ".join(value or "" for value in fields).lower()


def _owner_matches(
    item: ScoredEntity, owner_id: str | None, *, unassigned: bool
) -> bool:
    owner = (item.owner_user_id or "").strip()
    if unassigned:
        return not owner
    return not owner_id or owner.lower() == owner_id


def _identified_between(
    item: ScoredEntity, start: datetime | None, end: datetime | None
) -> bool:
    """Without date bounds every item matches; with them, a valid date must fit."""
    if start is None and end is None:
        return True
    identified = parse_date(item.identified_at or "")
    if identified is None:
        return False
    return (start is None or identified >= start) and (end is None or identified <= end)


def filter_scored[TScored: ScoredEntity](
    items: Sequence[TScored], criteria: ScoredFilterCriteria
) -> list[TScored]:
    """Filter any scored entity according to UI criteria."""
    search = _norm(criteria.search)
    low, high = sorted((int(criteria.min_score), int(criteria.max_score)))
    status = _norm(criteria.status or ANY_STATUS)
    category = _norm(criteria.category_contains)
    owner_id = _norm(criteria.owner_user_id) or None
    unassigned = bool(criteria.owner_unassigned)
    start, end = criteria.identified_from, criteria.identified_to
    return [
        item
        for item in items
        if (not search or search in _search_text(item))
        and low <= item.score <= high
        and (status == ANY_STATUS or _norm(item.status) == status)
        and (not category or category in (item.category or "").lower())
        and _owner_matches(item, owner_id, unassigned=unassigned)
        and _identified_between(item, start, end)
    ]


def filter_risks(risks: list[Risk], criteria: ScoredFilterCriteria) -> list[Risk]:
    return filter_scored(risks, criteria)


def filter_opportunities(
    opps: list[Opportunity], criteria: ScoredFilterCriteria
) -> list[Opportunity]:
    return filter_scored(opps, criteria)
