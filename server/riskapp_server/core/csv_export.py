"""CSV output safety helpers."""

from __future__ import annotations

from typing import Any

_FORMULA_PREFIXES = ("=", "+", "-", "@")


def safe_csv_cell(value: Any) -> Any:
    """Prevent spreadsheet programs from interpreting user text as a formula."""
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return value
    text = str(value)
    if text.lstrip().startswith(_FORMULA_PREFIXES):
        return f"'{text}"
    return text
