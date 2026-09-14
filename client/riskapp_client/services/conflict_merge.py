"""Explicit per-field choices for two-way synchronization conflicts.

No common ancestor is stored in the outbox, so this module never guesses
which side changed a field. The user must select any local values to keep.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from riskapp_client.domain.conflict_fields import MERGE_FIELDS
from riskapp_client.domain.scored_entity_fields import ALL_STATUSES

_PARENTS = ("item_id", "risk_id", "opportunity_id")
_DIMENSIONS = ("impact_cost", "impact_time", "impact_scope", "impact_quality")


def mergeable_fields(conflict: dict[str, Any]) -> tuple[str, ...]:
    """Return differing, user-editable fields present in both saved copies."""
    entity = str(conflict.get("entity") or "")
    local, server = conflict.get("record"), conflict.get("server_record")
    if (
        conflict.get("op") != "upsert"
        or entity not in MERGE_FIELDS
        or not isinstance(local, dict)
        or not isinstance(server, dict)
        or not server
        or bool(local.get("is_deleted"))
        or bool(server.get("is_deleted"))
        or str(local.get("status") or "").lower() == "deleted"
        or str(server.get("status") or "").lower() == "deleted"
        or not server.get("id")
        or str(server.get("id")) != str(conflict.get("entity_id"))
        or not isinstance(conflict.get("server_version"), int)
        or isinstance(conflict.get("server_version"), bool)
        or conflict["server_version"] < 1
    ):
        return ()
    dimensions_active = entity in {"risk", "opportunity"} and any(
        server.get(key) is not None or local.get(key) is not None
        for key in _DIMENSIONS
    )
    return tuple(
        key for key in MERGE_FIELDS[entity]
        if key in local and key in server and local[key] != server[key]
        and not (key == "impact" and dimensions_active)
    )


def _validate_selected(entity: str, key: str, value: Any) -> None:
    if key not in {"title", "probability", "impact", *_DIMENSIONS} and (
        value is not None and not isinstance(value, str)
    ):
        raise ValueError(f"{key} must be text")
    if key in {"probability", "impact", *_DIMENSIONS}:
        if value is None and key in _DIMENSIONS:
            return
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
            raise ValueError(f"{key} must be an integer from 1 to 5")
    elif key == "title":
        if not isinstance(value, str) or not value.strip() or len(value) > 300:
            raise ValueError("title must contain 1 to 300 characters")
    elif key == "owner_user_id" and value is not None:
        try:
            UUID(str(value))
        except (ValueError, TypeError) as exc:
            raise ValueError("owner_user_id must be a UUID") from exc
    elif key in {"identified_at", "response_at", "occurred_at"} and value is not None:
        try:
            datetime.fromisoformat(value)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{key} must be a date and time") from exc
    elif key == "status":
        allowed = (
            set(ALL_STATUSES) - {"deleted"} if entity in {"risk", "opportunity"}
            else {"open", "doing", "done"} if entity == "action"
            else {"open", "in_progress", "resolved", "closed"}
        )
        if value not in allowed:
            raise ValueError("Invalid status for this entity")
    elif key == "kind" and value not in {"mitigation", "contingency", "exploit"}:
        raise ValueError("Invalid action kind")
    elif key == "priority" and value not in {"low", "medium", "high", "critical"}:
        raise ValueError("Invalid help-desk priority")
    elif key == "category" and entity == "helpdesk_ticket" and value not in {
        "bug", "question", "feature_request", "access", "other"
    }:
        raise ValueError("Invalid help-desk category")
    elif key == "code" and value is not None and (
        not isinstance(value, str) or not 1 <= len(value) <= 64
    ):
        raise ValueError("code must contain 1 to 64 characters")
    elif (
        key == "category" and entity != "helpdesk_ticket"
        and value is not None and len(value) > 200
    ):
        raise ValueError("category is too long")
    elif key == "document_url" and value is not None and len(value) > 2000:
        raise ValueError("document_url is too long")
    elif key == "reporter_email" and value is not None and len(value) > 320:
        raise ValueError("reporter_email is too long")
    elif key == "notes" and value is not None and len(value) > 5000:
        raise ValueError("notes is too long")
    elif isinstance(value, str) and len(value) > 10000:
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
