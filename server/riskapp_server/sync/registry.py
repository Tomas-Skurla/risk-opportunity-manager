"""Which entities the sync protocol accepts, and their per-entity rules."""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from pydantic import BaseModel

from riskapp_server.db.models import (
    Action,
    ActionStatus,
    Assessment,
    HelpDeskCategory,
    HelpDeskPriority,
    HelpDeskStatus,
    HelpDeskTicket,
    Item,
)
from riskapp_server.schemas.models import (
    SyncActionRecord,
    SyncAssessmentRecord,
    SyncHelpDeskTicketRecord,
    SyncItemRecord,
)


class EntityConfig(TypedDict):
    model: type[Any]
    schema: type[BaseModel]
    manager_delete: bool
    defaults: dict[str, Any]
    parent_field: NotRequired[str]


ENTITY_REGISTRY: dict[str, EntityConfig] = {
    "risk": {
        "model": Item,
        "schema": SyncItemRecord,
        "manager_delete": True,
        "defaults": {
            "title": "Untitled",
            "probability": 1,
            "impact": 1,
            "type": "risk",
        },
    },
    "opportunity": {
        "model": Item,
        "schema": SyncItemRecord,
        "manager_delete": True,
        "defaults": {
            "title": "Untitled",
            "probability": 1,
            "impact": 1,
            "type": "opportunity",
        },
    },
    "action": {
        "model": Action,
        "schema": SyncActionRecord,
        "manager_delete": True,
        "defaults": {
            "title": "Untitled action",
            "kind": "mitigation",
            "status": ActionStatus.open.value,
        },
    },
    "assessment": {
        "model": Assessment,
        "schema": SyncAssessmentRecord,
        "manager_delete": False,
        "defaults": {"probability": 1, "impact": 1},
        "parent_field": "item_id",
    },
    "helpdesk_ticket": {
        "model": HelpDeskTicket,
        "schema": SyncHelpDeskTicketRecord,
        "manager_delete": False,
        "defaults": {
            "title": "Untitled ticket",
            "category": HelpDeskCategory.other.value,
            "priority": HelpDeskPriority.medium.value,
            "status": HelpDeskStatus.open.value,
        },
    },
}

ENTITY_MODELS = {key: config["model"] for key, config in ENTITY_REGISTRY.items()}
OPS = {"upsert", "delete"}
