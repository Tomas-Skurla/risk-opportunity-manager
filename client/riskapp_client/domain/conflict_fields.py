"""Editable synchronization fields shared by local storage and merge rules."""

from __future__ import annotations

_SCORED = (
    "title", "code", "description", "category", "threat", "triggers",
    "mitigation_plan", "document_url", "owner_user_id", "status",
    "identified_at", "response_at", "occurred_at", "probability", "impact",
    "impact_cost", "impact_time", "impact_scope", "impact_quality",
)

MERGE_FIELDS: dict[str, tuple[str, ...]] = {
    "risk": _SCORED,
    "opportunity": _SCORED,
    "action": ("kind", "title", "description", "status", "owner_user_id"),
    "assessment": ("probability", "impact", "notes"),
    "helpdesk_ticket": (
        "title", "description", "category", "priority", "status",
        "reporter_email",
    ),
}
