from __future__ import annotations

from collections.abc import Iterable, MutableMapping
from typing import Any


def norm_optional_text_fields(
    payload: MutableMapping[str, Any], keys: Iterable[str]
) -> None:
    """Strip optional text fields and convert empty strings to None."""
    if not payload:
        return
    for key in keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if value is None:
            continue
        normalized = str(value).strip()
        payload[key] = normalized if normalized else None
