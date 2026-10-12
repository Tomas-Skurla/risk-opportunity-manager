"""UI helpers for scored-entity tabs (Risks / Opportunities).

The tab UI is shared (ScoredEntitiesTab); these helpers keep the remaining mixin
code small and consistent.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLineEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
)  # pylint: disable=no-name-in-module

from riskapp_client.domain.scored_entity_fields import ALL_STATUSES, DEFAULT_STATUS
from riskapp_client.services import entity_filters as filters


def _top_categories(counts: Mapping[str, Any]) -> list[str]:
    ranked = sorted(counts.items(), key=lambda kv: int(kv[1] or 0), reverse=True)[:3]
    names = [f"{c} {n}" for c, n in ranked if c and c != "(none)" and int(n or 0) > 0]
    return [f"Top categories: {', '.join(names)}"] if names else []


def server_report_lines(
    report: Mapping[str, Any], shown: int, full_count: int
) -> list[str]:
    """Format server statistics alongside the visible and loaded local counts."""
    matching_total = report.get("total")
    project_total = report.get("project_total")

    matching_count_text = "?"
    if matching_total is not None:
        matching_count_text = str(int(matching_total))

    project_count_text = "?"
    if project_total is not None:
        project_count_text = str(int(project_total))

    summary = (
        f"Local {shown}/{full_count} · "
        f"Server {matching_count_text}/{project_count_text}"
    )
    average_score = report.get("avg_score")
    if average_score is not None:
        minimum_score = report.get("min_score")
        maximum_score = report.get("max_score")
        summary += (
            f" · score min {minimum_score} · max {maximum_score}"
            f" · avg {float(average_score):.1f}"
        )
    lines = [summary]
    status_counts = report.get("status_counts") or {}
    status_labels = []
    for status in ALL_STATUSES:
        status_count = status_counts.get(status, 0)
        if int(status_count or 0) > 0:
            status_labels.append(f"{status} {status_count}")

    if status_labels:
        lines.append(f"Status: {', '.join(status_labels)}")

    category_counts = report.get("category_counts") or {}
    lines.extend(_top_categories(category_counts))
    return lines


def local_report_lines(items: Sequence[Any], full_count: int) -> list[str]:
    """Calculate statistics for the visible rows; the caller handles empty tables."""
    scores: list[int] = []
    status_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()

    for item in items:
        score = int(getattr(item, "score", 0) or 0)
        status = getattr(item, "status", None) or DEFAULT_STATUS
        category = getattr(item, "category", None) or "(none)"

        scores.append(score)
        status_counts[status] += 1
        category_counts[category] += 1

    minimum_score = min(scores)
    maximum_score = max(scores)
    average_score = sum(scores) / len(scores)
    lines = [
        f"Showing {len(items)}/{full_count} · score min {minimum_score}"
        f" · max {maximum_score} · avg {average_score:.1f}"
    ]

    status_labels = []
    for status in ALL_STATUSES:
        status_count = status_counts[status]
        if status_count > 0:
            status_labels.append(f"{status} {status_count}")

    # Keep the standard status order, then list custom statuses by frequency.
    for status, status_count in status_counts.most_common():
        if status not in ALL_STATUSES:
            status_labels.append(f"{status} {status_count}")

    lines.append(f"Status: {', '.join(status_labels)}")
    lines.extend(_top_categories(category_counts))
    return lines


class _ScoredEntity(Protocol):

    id: str
    code: str | None
    title: str
    category: str | None
    status: str | None
    owner_user_id: str | None
    probability: int
    impact: int
    score: int

    description: str | None
    threat: str | None
    triggers: str | None

    mitigation_plan: str | None
    document_url: str | None

    identified_at: str | None
    status_changed_at: str | None
    response_at: str | None
    occurred_at: str | None

    impact_cost: int | None
    impact_time: int | None
    impact_scope: int | None
    impact_quality: int | None


MkItem = Callable[[str], QTableWidgetItem]


def score_bounds(min_spin: QSpinBox, max_spin: QSpinBox) -> tuple[int, int]:
    mn = int(min_spin.value())
    mx = int(max_spin.value())
    return (mx, mn) if mn > mx else (mn, mx)


def date_bounds(
    from_edit: QLineEdit, to_edit: QLineEdit
) -> tuple[datetime | None, datetime | None]:
    dt_from = filters.parse_date(from_edit.text())
    dt_to = filters.parse_date(to_edit.text())
    if dt_to:
        dt_to = dt_to.replace(hour=23, minute=59, second=59)
    return dt_from, dt_to


def populate_scored_table(
    table: QTableWidget,
    items: list[_ScoredEntity],
    *,
    mk_item: Callable[..., QTableWidgetItem],
) -> dict[str, _ScoredEntity]:
    """Populate the shared scored-entity table (Code/Title/Category/Status/Owner/P/I/Score).

    Returns a {id: entity} cache.
    """
    table.setRowCount(len(items))
    for row, it in enumerate(items):
        cols = [
            (it.code or "", True, False),
            (it.title, True, False),
            (it.category or "", False, False),
            (it.status or "", False, False),
            (it.owner_user_id or "", False, False),
            (str(it.probability), False, True),
            (str(it.impact), False, True),
            (str(it.score), False, True),
        ]
        for col, (val, use_id, center) in enumerate(cols):
            # Pass align_center to mk_item (which your backend mixin handles)
            item = mk_item(
                val, entity_id=it.id if use_id else None, align_center=center
            )
            # Strictly force alignment on the Qt item itself
            if center:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            else:
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
            table.setItem(row, col, item)
    return {x.id: x for x in items}


def form_values_for_entity(entity: _ScoredEntity) -> dict[str, Any]:
    """Convert a scored entity into kwargs expected by RiskForm.set_values()."""
    return {
        "title": entity.title,
        "probability": entity.probability,
        "impact": entity.impact,
        "code": entity.code,
        "description": entity.description,
        "category": entity.category,
        "threat": entity.threat,
        "triggers": entity.triggers,
        "mitigation_plan": getattr(entity, "mitigation_plan", None),
        "document_url": getattr(entity, "document_url", None),
        "owner_user_id": entity.owner_user_id,
        "status": entity.status,
        "identified_at": entity.identified_at,
        "status_changed_at": entity.status_changed_at,
        "response_at": entity.response_at,
        "occurred_at": entity.occurred_at,
        "impact_cost": getattr(entity, "impact_cost", None),
        "impact_time": getattr(entity, "impact_time", None),
        "impact_scope": getattr(entity, "impact_scope", None),
        "impact_quality": getattr(entity, "impact_quality", None),
    }
