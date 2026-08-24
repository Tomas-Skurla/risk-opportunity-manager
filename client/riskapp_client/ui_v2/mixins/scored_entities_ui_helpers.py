"""UI helpers for scored-entity tabs (Risks / Opportunities).

The tab UI is shared (ScoredEntitiesTab); these helpers keep the remaining mixin
code small and consistent.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLineEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
)  # pylint: disable=no-name-in-module
from riskapp_client.services import entity_filters as filters


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
                item.setTextAlignment(Qt.AlignCenter)
            else:
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
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
