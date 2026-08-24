"""Unit tests for the small offline-first service adapters."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from riskapp_client.adapters.mappers.action_assessment_mapper import (
    action_from_mapping,
    assessment_from_mapping,
)
from riskapp_client.domain.domain_models import HelpDeskTicket, Member
from riskapp_client.services.action_management_service import ActionService
from riskapp_client.services.assessment_management_service import AssessmentService
from riskapp_client.services.helpdesk_service import HelpDeskService
from riskapp_client.services.member_management_service import MembersService


def test_action_service_lists_creates_and_updates_both_target_types(
    monkeypatch,
) -> None:
    store = Mock()
    store.list_actions.return_value = ["action"]
    store.get_action_project_and_version.return_value = ("project-1", 4)
    outbox = Mock()
    service = ActionService(store, outbox)
    monkeypatch.setattr(
        "riskapp_client.services.action_management_service.uuid.uuid4",
        lambda: "action-new",
    )

    assert service.list("project-1") == ["action"]
    created = service.create(
        "project-1",
        target_type="risk",
        target_id="risk-1",
        kind="mitigation",
        title="Mitigate",
        description="",
        status="",
        owner_user_id=None,
    )
    assert created.id == "action-new"
    assert created.risk_id == "risk-1"
    assert created.opportunity_id is None
    assert created.status == "open"

    updated = service.update(
        "action-1",
        target_type="opportunity",
        target_id="opp-1",
        kind="exploit",
        title="Exploit",
        description="details",
        status="doing",
        owner_user_id="user-1",
    )
    assert updated.version == 4
    assert updated.risk_id is None
    assert updated.opportunity_id == "opp-1"
    assert store.upsert_local_action.call_count == 2
    assert outbox.queue_action_upsert.call_count == 2


def test_assessment_service_handles_new_existing_risk_and_opportunity() -> None:
    store = Mock()
    store.list_assessments.return_value = ["assessment"]
    store.get_assessment_project_and_version.side_effect = [
        KeyError("new"),
        ("project-1", 3),
    ]
    outbox = Mock()
    service = AssessmentService(store, outbox)

    assert service.list("project-1", "risk", "risk-1") == ["assessment"]
    risk_assessment = service.upsert_my(
        "project-1", "risk", "risk-1", "user-1", 2, 4, None
    )
    assert risk_assessment.version == 0
    assert risk_assessment.notes == ""
    assert outbox.queue_assessment_upsert.call_args.kwargs["risk_id"] == "risk-1"

    opportunity_assessment = service.upsert_my(
        "project-1", "opportunity", "opp-1", "user-1", 5, 3, "notes"
    )
    assert opportunity_assessment.version == 3
    assert opportunity_assessment.score == 15
    assert outbox.queue_assessment_upsert.call_args.kwargs["opportunity_id"] == (
        "opp-1"
    )


def test_helpdesk_service_create_update_and_both_delete_paths() -> None:
    store = Mock()
    created = HelpDeskTicket(
        "ticket-new",
        "project-1",
        "Problem",
        "Details",
        "bug",
        "high",
        "open",
        "reporter@example.test",
    )
    updated = HelpDeskTicket(
        "ticket-new",
        "project-1",
        "Solved",
        status="closed",
    )
    store.list_helpdesk_tickets.return_value = [created]
    store.create_helpdesk_ticket.return_value = created
    store.update_helpdesk_ticket.return_value = updated
    store.get_helpdesk_ticket_project_and_version.side_effect = [
        ("project-1", 0),
        ("project-1", 2),
    ]
    outbox = Mock()
    service = HelpDeskService(store, outbox)

    assert service.list("project-1") == [created]
    assert service.create("project-1", title="Problem") is created
    assert service.update("ticket-new", title="Solved", status="closed") is updated
    assert outbox.queue_helpdesk_upsert.call_count == 2

    service.delete("ticket-new")
    store.delete_helpdesk_ticket.assert_called_once_with("ticket-new")
    outbox.discard_entity_changes.assert_called_once_with(
        "project-1",
        entity="helpdesk_ticket",
        entity_id="ticket-new",
    )
    service.delete("ticket-new")
    store.soft_delete_helpdesk_ticket.assert_called_once_with("ticket-new")
    outbox.queue_helpdesk_delete.assert_called_once_with("ticket-new", "project-1")


def test_members_service_requires_remote_and_delegates() -> None:
    offline = MembersService(None)
    assert offline.list("project-1") == []
    with pytest.raises(RuntimeError, match="online mode"):
        offline.add("project-1", user_email="user@example.test", role="member")
    with pytest.raises(RuntimeError, match="online mode"):
        offline.remove("project-1", member_user_id="user-1")

    remote = Mock()
    member = Member("user-1", "user@example.test", "member")
    remote.list_members.return_value = [member]
    online = MembersService(remote)
    assert online.list("project-1") == [member]
    online.add("project-1", user_email=member.email, role="manager")
    online.remove("project-1", member_user_id=member.user_id)
    remote.add_member.assert_called_once_with(
        "project-1", user_email=member.email, role="manager"
    )
    remote.remove_member.assert_called_once_with(
        "project-1", member_user_id=member.user_id
    )


def test_action_and_assessment_mappers_validate_legacy_payloads() -> None:
    with pytest.raises(KeyError, match="id"):
        action_from_mapping({"project_id": "project-1"})
    action = action_from_mapping(
        {
            "id": " action-1 ",
            "project_id": "project-1",
            "risk_id": " ",
            "opportunity_id": "opp-1",
            "version": True,
            "status": None,
        }
    )
    assert action.id == "action-1"
    assert action.risk_id is None
    assert action.opportunity_id == "opp-1"
    assert action.version == 0
    assert action.status == "open"

    with pytest.raises(KeyError, match="item_id"):
        assessment_from_mapping({"id": "assessment-1"})
    assessment = assessment_from_mapping(
        {
            "id": "assessment-1",
            "opportunity_id": "opp-1",
            "probability": "bad",
            "impact": " 4 ",
            "version": "",
        }
    )
    assert assessment.item_id == "opp-1"
    assert assessment.probability == 1
    assert assessment.impact == 4
