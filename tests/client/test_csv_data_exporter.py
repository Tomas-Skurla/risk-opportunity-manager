"""Client CSV export behavior."""

from __future__ import annotations

import csv

from riskapp_client.adapters.local_storage.csv_data_exporter import (
    export_opportunities,
    export_risks,
)
from riskapp_client.domain.domain_models import Opportunity, Risk
from riskapp_client.domain.scored_entity_fields import SCORED_ENTITY_CSV_COLUMNS


def _read_rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.reader(handle))


def test_export_risks_writes_stable_columns_and_neutralizes_formulas(tmp_path) -> None:
    path = tmp_path / "risks.csv"
    risk = Risk(
        id="risk-1",
        project_id="project-1",
        code='=HYPERLINK("https://bad.example")',
        title="  +SUM(1,2)",
        description="@malicious",
        probability=4,
        impact=3,
    )

    result = export_risks(path, (item for item in [risk]))
    rows = _read_rows(path)

    assert result.path == path
    assert result.rows_written == 1
    assert rows[0] == list(SCORED_ENTITY_CSV_COLUMNS)
    exported = dict(zip(rows[0], rows[1], strict=True))
    assert exported["code"].startswith("'=")
    assert exported["title"].startswith("'  +")
    assert exported["description"].startswith("'@")
    assert exported["probability"] == "4"
    assert exported["impact"] == "3"
    assert exported["score"] == "12"


def test_export_opportunities_handles_empty_and_none_cells(tmp_path) -> None:
    empty_path = tmp_path / "empty.csv"
    empty_result = export_opportunities(empty_path, [])
    assert empty_result.rows_written == 0
    assert _read_rows(empty_path) == [list(SCORED_ENTITY_CSV_COLUMNS)]

    path = tmp_path / "opportunities.csv"
    opportunity = Opportunity(
        id="opp-1",
        project_id="project-1",
        title="Useful opportunity",
        category=None,
        probability=2,
        impact=5,
    )
    export_opportunities(path, [opportunity])
    exported = dict(zip(*_read_rows(path), strict=True))
    assert exported["category"] == ""
    assert exported["score"] == "10"
