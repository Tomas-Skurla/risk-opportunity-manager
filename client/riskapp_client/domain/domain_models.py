"""Client-side domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from riskapp_client.domain.scored_entity_fields import (
    ACTION_DEFAULT_STATUS,
    DEFAULT_STATUS,
)


def _int_or_none(value: Any) -> int | None:
    """Convert optional integer-like values."""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class Member:

    user_id: str
    email: str
    role: str
    is_superuser: bool = False
    created_at: str | None = None


@dataclass
class Project:

    id: str
    name: str
    description: str = ""
    created_by: str = ""


@dataclass
class Action:

    id: str
    project_id: str

    # Older payloads still use separate risk_id/opportunity_id fields.
    risk_id: str | None
    opportunity_id: str | None

    # mitigation|contingency|exploit
    kind: str
    title: str
    description: str = ""
    status: str = ACTION_DEFAULT_STATUS  # open|doing|done
    owner_user_id: str | None = None

    version: int = 0
    is_deleted: bool = False
    updated_at: str = ""


@dataclass
class ScoredEntity:
    """Base model for risks and opportunities."""

    id: str
    project_id: str

    code: str | None = None  # human-facing unique identifier (search/filter)
    title: str = ""
    description: str | None = None
    category: str | None = None
    threat: str | None = None
    triggers: str | None = None
    mitigation_plan: str | None = None
    document_url: str | None = None
    owner_user_id: str | None = None
    status: str | None = DEFAULT_STATUS
    identified_at: str | None = None
    status_changed_at: str | None = None
    response_at: str | None = None
    occurred_at: str | None = None
    # 1..5 scale
    probability: int = 3
    impact: int = 3
    # Optional per-dimension impacts.
    impact_cost: int | None = None
    impact_time: int | None = None
    impact_scope: int | None = None
    impact_quality: int | None = None
    version: int = 0
    is_deleted: bool = False
    updated_at: str = ""

    score: int = field(init=False)

    def __post_init__(self) -> None:
        """Recompute derived fields after initialization."""
        if self.status is None:
            self.status = DEFAULT_STATUS

        dims = (
            _int_or_none(self.impact_cost),
            _int_or_none(self.impact_time),
            _int_or_none(self.impact_scope),
            _int_or_none(self.impact_quality),
        )
        dims_int = [x for x in dims if x is not None]
        if dims_int:
            self.impact = max(dims_int)

        # Keep probability/impact strict: invalid values should be caught early.
        self.score = int(self.probability) * int(self.impact)


@dataclass
class Risk(ScoredEntity):

    pass


@dataclass
class Opportunity(ScoredEntity):

    pass


@dataclass
class Assessment:

    id: str
    item_id: str
    assessor_user_id: str
    probability: int
    impact: int
    notes: str = ""

    version: int = 0
    is_deleted: bool = False
    updated_at: str = ""

    # allow passing score, but always recompute it
    score: int = 0

    def __post_init__(self) -> None:
        """Recompute derived fields after initialization."""
        self.score = int(self.probability) * int(self.impact)

    # Backward-compatible aliases (risk-only older code paths).
    @property
    def risk_id(self) -> str:
        return self.item_id

    @property
    def opportunity_id(self) -> str:
        return self.item_id


TICKET_STATUSES = ("open", "in_progress", "resolved", "closed")
TICKET_PRIORITIES = ("low", "medium", "high", "critical")
TICKET_CATEGORIES = ("bug", "question", "feature_request", "access", "other")


@dataclass
class HelpDeskTicket:
    """A help-desk / support ticket.

    Tickets are persisted locally in SQLite and, for remote-backed projects,
    participate in the standard offline-first sync pipeline.
    """

    id: str
    project_id: str
    title: str
    description: str = ""
    category: str = "other"
    priority: str = "medium"
    status: str = "open"
    reporter_email: str = ""
    created_at: str = ""
    updated_at: str = ""
    version: int = 0
    is_deleted: bool = False


class Backend(Protocol):
    """Protocol describing the backend contract used by the client."""

    def list_projects(self) -> list[Project]: ...

    # --- Risks ---
    def list_risks(self, project_id: str) -> list[Risk]: ...

    def risks_report(self, project_id: str, **filters) -> dict: ...

    def create_risk(
        self,
        project_id: str,
        *,
        title: str,
        probability: int,
        impact: int,
        impact_cost: int | None = None,
        impact_time: int | None = None,
        impact_scope: int | None = None,
        impact_quality: int | None = None,
        code: str | None = None,
        description: str | None = None,
        category: str | None = None,
        threat: str | None = None,
        triggers: str | None = None,
        mitigation_plan: str | None = None,
        document_url: str | None = None,
        owner_user_id: str | None = None,
        status: str | None = None,
        identified_at: str | None = None,
        status_changed_at: str | None = None,
        response_at: str | None = None,
        occurred_at: str | None = None,
    ) -> Risk: ...

    def update_risk(
        self,
        project_id: str,
        risk_id: str,
        *,
        title: str,
        probability: int,
        impact: int,
        impact_cost: int | None = None,
        impact_time: int | None = None,
        impact_scope: int | None = None,
        impact_quality: int | None = None,
        code: str | None = None,
        description: str | None = None,
        category: str | None = None,
        threat: str | None = None,
        triggers: str | None = None,
        mitigation_plan: str | None = None,
        document_url: str | None = None,
        owner_user_id: str | None = None,
        status: str | None = None,
        identified_at: str | None = None,
        status_changed_at: str | None = None,
        response_at: str | None = None,
        occurred_at: str | None = None,
        base_version: int | None = None,
    ) -> Risk:
        """Update risk."""
        ...

    def delete_risk(self, project_id: str, risk_id: str) -> None: ...

    # --- Opportunities ---
    def list_opportunities(self, project_id: str) -> list[Opportunity]: ...

    def opportunities_report(self, project_id: str, **filters) -> dict: ...

    def create_opportunity(
        self,
        project_id: str,
        *,
        title: str,
        probability: int,
        impact: int,
        impact_cost: int | None = None,
        impact_time: int | None = None,
        impact_scope: int | None = None,
        impact_quality: int | None = None,
        code: str | None = None,
        description: str | None = None,
        category: str | None = None,
        threat: str | None = None,
        triggers: str | None = None,
        mitigation_plan: str | None = None,
        document_url: str | None = None,
        owner_user_id: str | None = None,
        status: str | None = None,
        identified_at: str | None = None,
        status_changed_at: str | None = None,
        response_at: str | None = None,
        occurred_at: str | None = None,
    ) -> Opportunity: ...

    def update_opportunity(
        self,
        project_id: str,
        opportunity_id: str,
        *,
        title: str,
        probability: int,
        impact: int,
        impact_cost: int | None = None,
        impact_time: int | None = None,
        impact_scope: int | None = None,
        impact_quality: int | None = None,
        code: str | None = None,
        description: str | None = None,
        category: str | None = None,
        threat: str | None = None,
        triggers: str | None = None,
        mitigation_plan: str | None = None,
        document_url: str | None = None,
        owner_user_id: str | None = None,
        status: str | None = None,
        identified_at: str | None = None,
        status_changed_at: str | None = None,
        response_at: str | None = None,
        occurred_at: str | None = None,
        base_version: int | None = None,
    ) -> Opportunity:
        """Update opportunity."""
        ...

    def delete_opportunity(self, project_id: str, opportunity_id: str) -> None: ...

    # --- Members / roles ---
    def list_members(self, project_id: str) -> list[Member]: ...

    def add_member(self, project_id: str, *, user_email: str, role: str) -> None: ...

    def remove_member(self, project_id: str, *, member_user_id: str) -> None: ...

    # --- Actions ---
    def list_actions(self, project_id: str) -> list[Action]: ...

    def create_action(
        self,
        project_id: str,
        *,
        target_type: str,  # "risk" | "opportunity"
        target_id: str,
        kind: str,  # mitigation|contingency|exploit
        title: str,
        description: str,
        status: str,  # open|doing|done
        owner_user_id: str | None,
    ) -> Action: ...

    def update_action(
        self,
        project_id: str,
        action_id: str,
        *,
        target_type: str,
        target_id: str,
        kind: str,
        title: str,
        description: str,
        status: str,
        owner_user_id: str | None,
        base_version: int | None = None,
    ) -> Action:
        """Update action."""
        ...

    # --- Assessments ---
    def list_assessments(
        self, project_id: str, item_type: str, item_id: str
    ) -> list[Assessment]: ...

    def upsert_my_assessment(
        self,
        project_id: str,
        item_type: str,
        item_id: str,
        probability: int,
        impact: int,
        notes: str | None = None,
    ) -> Assessment: ...

    # Optional, but useful for row highlighting or prefill.
    def current_user_id(self) -> str | None: ...

    def create_snapshot(self, project_id: str) -> dict[str, Any]: ...

    def top_history(
        self,
        project_id: str,
        *,
        kind: str = "risks",
        limit: int = 10,
        from_ts: str | None = None,
        to_ts: str | None = None,
    ) -> list[dict[str, Any]]: ...

    # --- Help Desk ---
    def list_helpdesk_tickets(self, project_id: str) -> list[HelpDeskTicket]: ...

    def create_helpdesk_ticket(
        self,
        project_id: str,
        *,
        title: str,
        description: str = "",
        category: str = "other",
        priority: str = "medium",
        reporter_email: str = "",
    ) -> HelpDeskTicket: ...

    def update_helpdesk_ticket(
        self,
        ticket_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        category: str | None = None,
        priority: str | None = None,
        status: str | None = None,
    ) -> HelpDeskTicket: ...

    def delete_helpdesk_ticket(self, ticket_id: str) -> None: ...
