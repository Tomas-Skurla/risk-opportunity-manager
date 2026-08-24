"""Client-side scored entity filtering."""

from __future__ import annotations


def _build_risks():
    from riskapp_client.domain.domain_models import Risk

    return [
        Risk(
            id="r1",
            project_id="p1",
            title="Server outage",
            description="Major outage on prod",
            category="Tech",
            probability=4,
            impact=3,
            owner_user_id="u-alice",
        ),
        Risk(
            id="r2",
            project_id="p1",
            title="Supplier delay",
            description="",
            category="Vendors",
            probability=3,
            impact=4,
            owner_user_id=None,
        ),
        Risk(
            id="r3",
            project_id="p1",
            title="Documentation gap",
            description="missing onboarding doc",
            category="Process",
            probability=1,
            impact=1,
            owner_user_id="",  # treated as unassigned
        ),
    ]


def test_filter_scored_search_score_range_and_owner_unassigned() -> None:
    """filter_scored matches search across fields, normalises swapped score range, filters unassigned"""
    from riskapp_client.services.entity_filters import (
        ScoredFilterCriteria,
        filter_scored,
    )

    risks = _build_risks()

    # Search is case-insensitive and matches title/code/category/description.
    matched = filter_scored(risks, ScoredFilterCriteria(search="OUTAGE"))
    assert [r.id for r in matched] == ["r1"]

    # Search hits the description field too.
    matched = filter_scored(risks, ScoredFilterCriteria(search="onboarding"))
    assert [r.id for r in matched] == ["r3"]

    # Score range with min > max is normalised, so the score 12 risks pass.
    matched = filter_scored(risks, ScoredFilterCriteria(min_score=20, max_score=5))
    assert {r.id for r in matched} == {"r1", "r2"}  # both have score 12

    # owner_unassigned keeps only items with no/empty owner_user_id.
    matched = filter_scored(risks, ScoredFilterCriteria(owner_unassigned=True))
    assert {r.id for r in matched} == {"r2", "r3"}
