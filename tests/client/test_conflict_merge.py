"""Field selection avoids identity, deletion and derived score mutations."""

from __future__ import annotations

import pytest
from riskapp_client.services.conflict_merge import mergeable_fields, merged_record


@pytest.mark.parametrize(
    ("entity", "field", "mine", "server"),
    [
        ("risk", "title", "Local", "Server"),
        ("opportunity", "probability", 5, 2),
        ("action", "description", "Local", "Server"),
        ("assessment", "notes", "Local", "Server"),
        ("helpdesk_ticket", "priority", "high", "low"),
    ],
)
def test_each_entity_can_select_a_differing_field(
    entity, field, mine, server
) -> None:
    conflict = {
        "entity": entity, "entity_id": "item", "op": "upsert",
        "server_version": 3,
        "record": {"id": "item", field: mine, "score": 99},
        "server_record": {
            "id": "item", "version": 3, field: server,
            "score": 2, "is_deleted": False,
        },
    }
    assert mergeable_fields(conflict) == (field,)
    record, selected = merged_record(conflict, {field: "mine"})
    assert record[field] == mine and selected == {field: mine}
    assert "score" not in record and "version" not in record


def test_dimension_values_derive_impact_and_block_impact_choice() -> None:
    conflict = {
        "entity": "risk", "entity_id": "risk-1", "op": "upsert",
        "server_version": 4,
        "record": {
            "id": "risk-1", "impact": 4, "impact_cost": 4,
            "impact_time": 1,
        },
        "server_record": {
            "id": "risk-1", "version": 4, "impact": 2,
            "impact_cost": 2, "impact_time": 2,
        },
    }
    assert mergeable_fields(conflict) == ("impact_cost", "impact_time")
    record, _ = merged_record(
        conflict, {"impact_cost": "mine", "impact_time": "server"}
    )
    assert record["impact"] == 4


@pytest.mark.parametrize("op,deleted", [("delete", False), ("upsert", True)])
def test_deleted_conflict_has_no_field_merge(op, deleted) -> None:
    conflict = {
        "entity": "risk", "entity_id": "risk-1", "op": op,
        "server_version": 3,
        "record": {"id": "risk-1", "title": "Mine"},
        "server_record": {
            "id": "risk-1", "version": 3, "title": "Server",
            "is_deleted": deleted,
        },
    }
    assert not mergeable_fields(conflict)
    with pytest.raises(ValueError, match="cannot be merged"):
        merged_record(conflict, {"title": "mine"})


def test_invalid_selected_value_keeps_conflict_for_user_decision() -> None:
    conflict = {
        "entity": "risk", "entity_id": "risk-1", "op": "upsert",
        "server_version": 3,
        "record": {"id": "risk-1", "probability": 9},
        "server_record": {"id": "risk-1", "version": 3, "probability": 2},
    }
    with pytest.raises(ValueError, match="probability"):
        merged_record(conflict, {"probability": "mine"})
