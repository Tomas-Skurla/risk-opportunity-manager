"""Mapping helpers for risks and opportunities."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any, TypeVar

from riskapp_client.domain.scored_entity_fields import (
    SCORED_ENTITY_META_KEYS,
    SCORED_ENTITY_META_SQLITE_COLUMNS,
)
from riskapp_client.utils.normalize import norm_optional_text_fields

ModelT = TypeVar("ModelT")

# Text-like metadata keys.
SCORED_ENTITY_TEXT_META_KEYS: tuple[str, ...] = tuple(
    k
    for k, col_type in SCORED_ENTITY_META_SQLITE_COLUMNS
    if str(col_type).upper().startswith("TEXT")
)

IMPACT_DIMENSIONS = ("impact_cost", "impact_time", "impact_scope", "impact_quality")
DATE_FIELDS = ("identified_at", "status_changed_at", "response_at", "occurred_at")


def _opt_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def _req_int(value: Any, default: int) -> int:
    v = _opt_int(value)
    return int(default) if v is None else int(v)


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def normalize_scored_payload_inplace(
    payload: MutableMapping[str, Any],
    *,
    strict_required_ints: bool = True,
) -> None:
    """Normalize a scored-entity payload in place."""
    if not payload:
        return
    norm_optional_text_fields(payload, SCORED_ENTITY_TEXT_META_KEYS)

    def _coerce_required_int(value: Any, *, default: int, field: str) -> int:
        """Coerce a required integer field."""
        if value is None:
            return default
        if isinstance(value, bool):
            return default
        s = str(value).strip()
        if not s:
            return default
        try:
            return int(s)
        except ValueError:
            if strict_required_ints:
                raise ValueError(f"{field} must be an integer") from None
            return default

    if "probability" in payload:
        payload["probability"] = _coerce_required_int(
            payload.get("probability"),
            default=1,
            field="probability",
        )
    if "impact" in payload:
        payload["impact"] = _coerce_required_int(
            payload.get("impact"),
            default=1,
            field="impact",
        )
    for k in IMPACT_DIMENSIONS:
        if k in payload:
            payload[k] = _opt_int(payload.get(k))


def scored_entity_from_mapping(
    data: Mapping[str, Any], *, model_cls: type[ModelT]
) -> ModelT:
    """Create a Risk/Opportunity model from a mapping (API JSON, sqlite3.Row, dict)."""
    if not data:
        raise ValueError("empty scored entity mapping")
    # sqlite3.Row does not support .get().
    data = dict(data)
    eid = str(data.get("id") or "").strip()
    pid = str(data.get("project_id") or "").strip()
    if not eid or not pid:
        raise KeyError("scored entity mapping must contain 'id' and 'project_id'")
    out: dict[str, Any] = {
        "id": eid,
        "project_id": pid,
        "title": str(data.get("title") or ""),
        "probability": _req_int(data.get("probability"), default=1),
        "impact": _req_int(data.get("impact"), default=1),
        "version": _req_int(data.get("version"), default=0),
        "is_deleted": bool(data.get("is_deleted", False)),
        "updated_at": str(data.get("updated_at") or ""),
    }
    for k in SCORED_ENTITY_META_KEYS:
        out[k] = data.get(k)
    for k in IMPACT_DIMENSIONS:
        out[k] = _opt_int(out.get(k))
    out["owner_user_id"] = _opt_str(out.get("owner_user_id"))
    for k in DATE_FIELDS:
        out[k] = _opt_str(out.get(k))
    norm_optional_text_fields(out, SCORED_ENTITY_TEXT_META_KEYS)
    return model_cls(**out)


def scored_entity_to_mapping(
    entity: Any,
    *,
    include_project_id: bool = True,
    include_sync: bool = True,
    include_score: bool = True,
    include_nones: bool = True,
) -> dict[str, Any]:
    """Convert a Risk/Opportunity model into a plain dict."""
    out: dict[str, Any] = {
        "id": str(entity.id),
        "title": str(getattr(entity, "title", "") or ""),
        "probability": int(getattr(entity, "probability", 1) or 1),
        "impact": int(getattr(entity, "impact", 1) or 1),
    }
    if include_project_id:
        out["project_id"] = str(entity.project_id)
    for k in SCORED_ENTITY_META_KEYS:
        out[k] = getattr(entity, k, None)
    if include_sync:
        out["version"] = int(getattr(entity, "version", 0) or 0)
        out["is_deleted"] = bool(getattr(entity, "is_deleted", False))
        out["updated_at"] = str(getattr(entity, "updated_at", "") or "")
    if include_score:
        out["score"] = _opt_int(getattr(entity, "score", None))
    norm_optional_text_fields(out, SCORED_ENTITY_TEXT_META_KEYS)
    if not include_nones:
        out = {k: v for k, v in out.items() if v is not None}
    return out
