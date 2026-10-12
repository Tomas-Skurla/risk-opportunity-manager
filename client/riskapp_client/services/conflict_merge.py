"""Explicit per-field choices for two-way synchronization conflicts.

No common ancestor is stored in the outbox, so this module never guesses
which side changed a field. The user must select any local values to keep.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from riskapp_client.domain.conflict_fields import MERGE_FIELDS
from riskapp_client.domain.domain_models import (
    TICKET_CATEGORIES,
    TICKET_PRIORITIES,
    TICKET_STATUSES,
)
from riskapp_client.domain.scored_entity_fields import ACTION_STATUSES, ALL_STATUSES

_PARENTS = ("item_id", "risk_id", "opportunity_id")
_DIMENSIONS = ("impact_cost", "impact_time", "impact_scope", "impact_quality")
_SCORES = frozenset({"probability", "impact", *_DIMENSIONS})
_DATES = frozenset({"identified_at", "response_at", "occurred_at"})
_SCORED_STATUSES = frozenset(ALL_STATUSES) - {"deleted"}
_BAD_STATUS = "Invalid status for this entity"
# Fields limited to a closed set of values, and the error for anything else.
_CHOICES: dict[tuple[str, str], tuple[frozenset[str], str]] = {
    ("risk", "status"): (_SCORED_STATUSES, _BAD_STATUS),
    ("opportunity", "status"): (_SCORED_STATUSES, _BAD_STATUS),
    ("action", "status"): (frozenset(ACTION_STATUSES), _BAD_STATUS),
    ("action", "kind"): (
        frozenset({"mitigation", "contingency", "exploit"}),
        "Invalid action kind",
    ),
    ("helpdesk_ticket", "status"): (frozenset(TICKET_STATUSES), _BAD_STATUS),
    ("helpdesk_ticket", "priority"): (
        frozenset(TICKET_PRIORITIES),
        "Invalid help-desk priority",
    ),
    ("helpdesk_ticket", "category"): (
        frozenset(TICKET_CATEGORIES),
        "Invalid help-desk category",
    ),
}
# Same limits as the server schemas; other text fields allow 10,000 characters.
_MAX_LENGTH = {
    "category": 200,
    "document_url": 2000,
    "reporter_email": 320,
    "notes": 5000,
}


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _is_deleted(record: dict[str, Any]) -> bool:
    return (
        bool(record.get("is_deleted"))
        or str(record.get("status") or "").lower() == "deleted"
    )


def _can_merge(conflict: dict[str, Any]) -> bool:
    """A live upsert whose saved server copy is this item at a real version."""
    local, server = conflict.get("record"), conflict.get("server_record")
    return (
        conflict.get("op") == "upsert"
        and str(conflict.get("entity") or "") in MERGE_FIELDS
        and isinstance(local, dict)
        and isinstance(server, dict)
        and bool(server)
        and not _is_deleted(local)
        and not _is_deleted(server)
        and bool(server.get("id"))
        and str(server.get("id")) == str(conflict.get("entity_id"))
        and _is_positive_int(conflict.get("server_version"))
    )


def mergeable_fields(conflict: dict[str, Any]) -> tuple[str, ...]:
    """Return differing, user-editable fields present in both saved copies."""
    if not _can_merge(conflict):
        return ()
    entity = str(conflict.get("entity") or "")
    local, server = conflict["record"], conflict["server_record"]
    dimensions_active = entity in {"risk", "opportunity"} and any(
        server.get(key) is not None or local.get(key) is not None for key in _DIMENSIONS
    )
    return tuple(
        key
        for key in MERGE_FIELDS[entity]
        if key in local
        and key in server
        and local[key] != server[key]
        and not (key == "impact" and dimensions_active)
    )


def _validate_selected(entity: str, key: str, value: Any) -> None:
    """Reject a chosen local value that the server would refuse."""
    if key in _SCORES:
        _validate_score(key, value)
    elif key == "title":
        if not isinstance(value, str) or not value.strip() or len(value) > 300:
            raise ValueError("title must contain 1 to 300 characters")
    elif value is not None and not isinstance(value, str):
        raise ValueError(f"{key} must be text")
    elif (entity, key) in _CHOICES:
        allowed, error = _CHOICES[entity, key]
        if value not in allowed:
            raise ValueError(error)
    elif value is not None:
        _validate_text(key, value)


def _validate_score(key: str, value: Any) -> None:
    if value is None and key in _DIMENSIONS:
        return
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
        raise ValueError(f"{key} must be an integer from 1 to 5")


def _validate_text(key: str, value: str) -> None:
    if key == "owner_user_id":
        try:
            UUID(value)
        except (ValueError, TypeError) as exc:
            raise ValueError("owner_user_id must be a UUID") from exc
    elif key in _DATES:
        try:
            datetime.fromisoformat(value)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{key} must be a date and time") from exc
    elif key == "code" and not 1 <= len(value) <= 64:
        raise ValueError("code must contain 1 to 64 characters")
    elif len(value) > _MAX_LENGTH.get(key, 10_000):
        raise ValueError(f"{key} is too long")


def merged_record(
    conflict: dict[str, Any], choices: dict[str, str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build an upsert from the server copy and explicitly selected local fields."""
    fields = mergeable_fields(conflict)
    if not fields:
        raise ValueError("This conflict cannot be merged field by field")
    if not isinstance(choices, dict) or set(choices) != set(fields):
        raise ValueError("Choose local or server for every differing field")
    if any(choice not in {"mine", "server"} for choice in choices.values()):
        raise ValueError("Invalid field choice")
    if "mine" not in choices.values():
        raise ValueError("Choose Use server when keeping every server field")

    entity = str(conflict["entity"])
    local, server = conflict["record"], conflict["server_record"]
    allowed = ("id", *MERGE_FIELDS[entity], *_PARENTS)
    record = {key: server[key] for key in allowed if key in server}
    record["id"] = str(server["id"])
    selected = {key: local[key] for key, side in choices.items() if side == "mine"}
    for key, value in selected.items():
        _validate_selected(entity, key, value)
    record.update(selected)
    if entity in {"risk", "opportunity"}:
        dimensions = [record.get(key) for key in _DIMENSIONS]
        if any(value is not None for value in dimensions):
            record["impact"] = max(value for value in dimensions if value is not None)
    return record, selected
