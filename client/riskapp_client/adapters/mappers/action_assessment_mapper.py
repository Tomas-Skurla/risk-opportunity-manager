"""Mapping helpers for actions and assessments."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from riskapp_client.domain.domain_models import Action, Assessment
from riskapp_client.domain.scored_entity_fields import ACTION_DEFAULT_STATUS


def _req_str(data: Mapping[str, Any], key: str) -> str:
    v = data.get(key)
    s = str(v).strip() if v is not None else ""
    if not s:
        raise KeyError(f"Missing required field: {key}")
    return s


def _opt_str(
    data: Mapping[str, Any], key: str, default: str | None = None
) -> str | None:
    v = data.get(key)
    if v is None:
        return default
    s = str(v).strip()
    return s if s else default


def _opt_int(
    data: Mapping[str, Any], key: str, default: int | None = None
) -> int | None:
    v = data.get(key)
    if v is None:
        return default
    if isinstance(v, bool):
        return default
    s = str(v).strip()
    if not s:
        return default
    try:
        return int(s)
    except (TypeError, ValueError):
        return default


def action_from_mapping(data: Mapping[str, Any]) -> Action:
    data = dict(data)
    return Action(
        id=_req_str(data, "id"),
        project_id=_req_str(data, "project_id"),
        risk_id=_opt_str(data, "risk_id"),
        opportunity_id=_opt_str(data, "opportunity_id"),
        kind=_opt_str(data, "kind", "") or "",
        title=_opt_str(data, "title", "") or "",
        description=str(data.get("description") or ""),
        status=_opt_str(data, "status", ACTION_DEFAULT_STATUS) or ACTION_DEFAULT_STATUS,
        owner_user_id=_opt_str(data, "owner_user_id"),
        version=int(_opt_int(data, "version", 0) or 0),
        is_deleted=bool(data.get("is_deleted", False)),
        updated_at=str(data.get("updated_at") or ""),
    )


def assessment_from_mapping(data: Mapping[str, Any]) -> Assessment:
    data = dict(data)
    # Older endpoints use risk_id/opportunity_id; sync uses item_id.
    item_id = (
        _opt_str(data, "item_id")
        or _opt_str(data, "risk_id")
        or _opt_str(data, "opportunity_id")
        or ""
    )
    if not item_id:
        raise KeyError("Missing required field: item_id")
    return Assessment(
        id=_req_str(data, "id"),
        item_id=item_id,
        assessor_user_id=_opt_str(data, "assessor_user_id", "") or "",
        probability=int(_opt_int(data, "probability", 1) or 1),
        impact=int(_opt_int(data, "impact", 1) or 1),
        notes=str(data.get("notes") or ""),
        version=int(_opt_int(data, "version", 0) or 0),
        is_deleted=bool(data.get("is_deleted", False)),
        updated_at=str(data.get("updated_at") or ""),
    )
