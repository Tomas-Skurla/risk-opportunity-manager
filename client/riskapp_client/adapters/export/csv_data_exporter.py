"""CSV export helpers."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from riskapp_client.domain.domain_models import Opportunity, Risk
from riskapp_client.domain.scored_entity_fields import SCORED_ENTITY_CSV_COLUMNS

_DANGEROUS_PREFIXES = ("=", "+", "-", "@")
_NUMERIC_COLS = {"probability", "impact", "score"}


def _sanitize_csv_cell(value: str) -> str:
    """Prefix formula-like cells with a quote."""
    stripped = value.lstrip()
    if stripped.startswith(_DANGEROUS_PREFIXES):
        return f"'{value}"
    return value


def _cell(value: object) -> str:
    if value is None:
        return ""
    return _sanitize_csv_cell(str(value))


@dataclass(frozen=True)
class CsvExportResult:

    path: Path
    rows_written: int


def _export_scored_entities(
    path: str | Path, rows: Iterable[object]
) -> CsvExportResult:
    """Export Risk/Opportunity rows to CSV using the shared column list."""
    out_path = Path(path)
    items = list(rows)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(list(SCORED_ENTITY_CSV_COLUMNS))
        for ent in items:
            out_row = []
            for col in SCORED_ENTITY_CSV_COLUMNS:
                v = getattr(ent, col, None)
                if col in _NUMERIC_COLS and v is not None:
                    out_row.append(int(v))
                else:
                    out_row.append(_cell(v))
            writer.writerow(out_row)
    return CsvExportResult(path=out_path, rows_written=len(items))


def export_risks(path: str | Path, risks: Iterable[Risk]) -> CsvExportResult:
    """Export risks to CSV in a stable column order."""
    return _export_scored_entities(path, risks)


def export_opportunities(
    path: str | Path, opps: Iterable[Opportunity]
) -> CsvExportResult:
    """Export opportunities to CSV in a stable column order."""
    return _export_scored_entities(path, opps)
