"""Unit boundaries for reusable server-side query filters."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import select


def test_item_filter_params_rejects_conflicting_owner_modes() -> None:
    from riskapp_server.core.filters import ItemFilterParams

    owner_id = uuid.uuid4()
    with pytest.raises(HTTPException, match="only one") as exc_info:
        ItemFilterParams(owner_user_id=owner_id, owner_unassigned=True)
    assert exc_info.value.status_code == 422

    params = ItemFilterParams(owner_user_id=owner_id, owner_unassigned=False)
    assert params.owner_user_id == owner_id
    assert params.owner_unassigned is False


def test_small_filter_helpers_cover_empty_swapped_and_date_ranges() -> None:
    from riskapp_server.core.filters import (
        apply_date_range,
        csv_list,
        normalize_score_range,
    )
    from riskapp_server.db.session import Item

    assert csv_list(None) == []
    assert csv_list(" active, ,closed ") == ["active", "closed"]
    assert normalize_score_range(20, 5) == (5, 20)
    assert normalize_score_range(None, 5) == (None, 5)

    base = select(Item)
    assert apply_date_range(
        base, Item.identified_at, from_date=None, to_date=None
    ) is base
    bounded = apply_date_range(
        base,
        Item.identified_at,
        from_date=date(2025, 1, 1),
        to_date=date(2025, 1, 31),
    )
    assert len(bounded._where_criteria) == 2


def test_apply_item_filters_builds_deleted_text_owner_and_score_predicates() -> None:
    from riskapp_server.core.filters import apply_item_filters
    from riskapp_server.db.session import Item

    stmt = apply_item_filters(
        select(Item),
        Item,
        search=r"100%_literal\value",
        item_type=" RISK ",
        min_score=20,
        max_score=5,
        status="deleted, active",
        category="Ops, Fin%ance",
        owner_user_id=None,
        owner_unassigned=True,
        from_date=date(2025, 1, 1),
        to_date=date(2025, 1, 31),
    )
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True})).lower()
    assert "is_deleted is true" in compiled
    assert "items.status in ('active')" in compiled
    assert "items.owner_user_id is null" in compiled
    assert "items.type = 'risk'" in compiled
    assert "items.score >= 5" in compiled
    assert "items.score <= 20" in compiled
    assert r"100\%\_literal\\value" in compiled


def test_apply_item_filters_supports_non_deleted_owner_and_empty_filters() -> None:
    from riskapp_server.core.filters import apply_item_filters
    from riskapp_server.db.session import Item

    owner_id = uuid.uuid4()
    filtered = apply_item_filters(
        select(Item),
        Item,
        search="   ",
        item_type=None,
        min_score=None,
        max_score=None,
        status="active",
        category="   ",
        owner_user_id=owner_id,
        owner_unassigned=False,
        from_date=None,
        to_date=None,
    )
    compiled = str(filtered.compile(compile_kwargs={"literal_binds": True})).lower()
    assert "is_deleted is false" in compiled
    assert "items.status in ('active')" in compiled
    assert owner_id.hex in compiled

    unfiltered = apply_item_filters(
        select(Item),
        Item,
        search=None,
        item_type=None,
        min_score=None,
        max_score=None,
        status=None,
        category=None,
        owner_user_id=None,
        owner_unassigned=False,
        from_date=None,
        to_date=None,
    )
    assert len(unfiltered._where_criteria) == 1

    deleted_only = apply_item_filters(
        select(Item),
        Item,
        search=None,
        item_type=None,
        min_score=None,
        max_score=None,
        status="deleted",
        category=",",
        owner_user_id=None,
        owner_unassigned=False,
        from_date=None,
        to_date=None,
    )
    assert "is_deleted is true" in str(deleted_only).lower()
