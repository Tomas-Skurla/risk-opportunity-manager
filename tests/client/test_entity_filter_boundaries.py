"""Boundary behavior for the shared scored-entity filters."""

from __future__ import annotations

from datetime import datetime

import pytest


def _entities():
    from riskapp_client.domain.domain_models import Opportunity, Risk

    return [
        Risk(
            id="risk-1",
            project_id="project-1",
            code="R-101",
            title="Vendor outage",
            description="Primary supplier unavailable",
            category="Operations",
            owner_user_id="User-A",
            status="active",
            identified_at="2025-01-15",
            probability=3,
            impact=4,
        ),
        Risk(
            id="risk-2",
            project_id="project-1",
            code=None,
            title="Untriaged",
            description=None,
            category=None,
            owner_user_id=None,
            status="concept",
            identified_at="not-a-date",
            probability=1,
            impact=2,
        ),
        Opportunity(
            id="opportunity-1",
            project_id="project-1",
            code="O-201",
            title="New market",
            description="Regional expansion",
            category="Growth",
            owner_user_id="User-B",
            status="active",
            identified_at="2025-03-10T12:30:00",
            probability=5,
            impact=5,
        ),
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", None),
        ("   ", None),
        ("2025-02-03", datetime(2025, 2, 3)),
        ("2025-02-03T04:05:06", datetime(2025, 2, 3, 4, 5, 6)),
        ("2025/02/03", None),
    ],
)
def test_parse_date_accepts_supported_formats_and_rejects_invalid_values(
    raw: str, expected: datetime | None
) -> None:
    from riskapp_client.services.entity_filters import parse_date

    assert parse_date(raw) == expected


@pytest.mark.parametrize(
    ("criteria", "expected_ids"),
    [
        ({"search": "supplier"}, ["risk-1"]),
        ({"search": "missing"}, []),
        ({"min_score": 13}, ["opportunity-1"]),
        ({"max_score": 3}, ["risk-2"]),
        ({"status": " ACTIVE "}, ["risk-1", "opportunity-1"]),
        ({"category_contains": "ERAT"}, ["risk-1"]),
        ({"owner_user_id": " user-a "}, ["risk-1"]),
        ({"owner_contains": "user-b"}, ["opportunity-1"]),
        ({"owner_unassigned": True}, ["risk-2"]),
        (
            {
                "identified_from": datetime(2025, 1, 1),
                "identified_to": datetime(2025, 1, 31, 23, 59),
            },
            ["risk-1"],
        ),
        ({"identified_from": datetime(2025, 2, 1)}, ["opportunity-1"]),
        ({"identified_to": datetime(2024, 12, 31)}, []),
    ],
)
def test_filter_scored_exercises_each_boundary(criteria, expected_ids) -> None:
    from riskapp_client.services.entity_filters import (
        ScoredFilterCriteria,
        filter_scored,
    )

    result = filter_scored(_entities(), ScoredFilterCriteria(**criteria))
    assert [item.id for item in result] == expected_ids


def test_typed_wrappers_delegate_to_the_shared_filter() -> None:
    from riskapp_client.services.entity_filters import (
        OpportunityFilterCriteria,
        RiskFilterCriteria,
        filter_opportunities,
        filter_risks,
    )

    risk, other_risk, opportunity = _entities()
    assert filter_risks([risk, other_risk], RiskFilterCriteria(search="R-101")) == [
        risk
    ]
    assert filter_opportunities(
        [opportunity], OpportunityFilterCriteria(status="active")
    ) == [opportunity]
