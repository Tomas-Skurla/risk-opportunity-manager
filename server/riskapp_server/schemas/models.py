from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    model_validator,
)

from riskapp_server.db.session import (
    ActionKind,
    ActionStatus,
    HelpDeskCategory,
    HelpDeskPriority,
    HelpDeskStatus,
    RiskStatus,
    Role,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


Probability = Annotated[int, Field(ge=1, le=5)]
Impact = Annotated[int, Field(ge=1, le=5)]
ImpactDim = Annotated[int, Field(ge=1, le=5)]
NonEmptyStr = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)
]
BoundedText = Annotated[str, Field(max_length=10_000)]
BoundedUrl = Annotated[str, Field(max_length=2000)]
BoundedNotes = Annotated[str, Field(max_length=5000)]


class RegisterIn(BaseModel):

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):

    user_id: uuid.UUID | None = None
    access_token: str
    token_type: str = "bearer"
    expires_in: int | None = None
    refresh_token: str | None = None


class RefreshIn(BaseModel):

    refresh_token: str = Field(min_length=1, max_length=512)


class ChangePasswordIn(BaseModel):

    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class PasswordResetRequestIn(BaseModel):

    email: EmailStr


class PasswordResetConfirmIn(BaseModel):

    token: str = Field(min_length=32, max_length=512)
    new_password: str = Field(min_length=1, max_length=128)


class AdminSetPasswordIn(BaseModel):

    new_password: str = Field(min_length=1, max_length=128)


class UserOut(ORMModel):

    id: uuid.UUID
    email: EmailStr
    is_active: bool
    is_superuser: bool


class ProjectCreate(BaseModel):

    name: NonEmptyStr
    description: BoundedText | None = None


class AddMemberIn(BaseModel):

    user_email: EmailStr
    role: Role


class MemberOut(ORMModel):

    user_id: uuid.UUID
    email: EmailStr
    role: Role
    is_superuser: bool = False
    created_at: datetime | None = None


class ProjectOut(ORMModel):

    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    created_by: uuid.UUID


class ItemShared(BaseModel):
    impact_cost: ImpactDim | None = None
    impact_time: ImpactDim | None = None
    impact_scope: ImpactDim | None = None
    impact_quality: ImpactDim | None = None

    code: str | None = Field(default=None, min_length=1, max_length=64)

    description: BoundedText | None = None
    category: str | None = Field(default=None, max_length=200)
    threat: BoundedText | None = None
    triggers: BoundedText | None = None
    mitigation_plan: BoundedText | None = None
    document_url: BoundedUrl | None = None
    owner_user_id: uuid.UUID | None = None
    status: RiskStatus | None = None

    identified_at: datetime | None = None
    response_at: datetime | None = None
    occurred_at: datetime | None = None


class ItemCreate(ItemShared):

    type: Literal["risk", "opportunity"]
    title: NonEmptyStr
    probability: Probability
    impact: Impact


class RiskCreate(ItemCreate):

    type: Literal["risk"] = "risk"


class OpportunityCreate(ItemCreate):

    type: Literal["opportunity"] = "opportunity"


class ItemUpdate(ItemShared):

    base_version: int | None = None
    title: str | None = Field(default=None, max_length=300)
    probability: Probability | None = None
    impact: Impact | None = None


class RiskUpdate(ItemUpdate):

    pass


class OpportunityUpdate(ItemUpdate):

    pass


class ItemOut(ItemShared, ORMModel):

    id: uuid.UUID
    type: Literal["risk", "opportunity"]
    project_id: uuid.UUID
    title: str
    probability: int
    impact: int
    score: int
    status_changed_at: datetime | None = None
    created_at: datetime
    created_by: uuid.UUID
    updated_at: datetime
    version: int
    is_deleted: bool


class RiskOut(ItemOut):

    type: Literal["risk"]


class OpportunityOut(ItemOut):

    type: Literal["opportunity"]


class ScoreReportOut(BaseModel):

    total: int
    project_total: int | None = None
    min_score: int | None = None
    max_score: int | None = None
    avg_score: float | None = None
    status_counts: dict[str, int] = Field(default_factory=dict)
    category_counts: dict[str, int] = Field(default_factory=dict)
    owner_counts: dict[str, int] = Field(default_factory=dict)
    score_buckets: dict[str, int] = Field(default_factory=dict)


class AssessmentIn(BaseModel):

    base_version: int | None = None
    probability: Probability
    impact: Impact
    notes: str | None = None


class AssessmentOut(ORMModel):

    id: uuid.UUID
    item_id: uuid.UUID
    risk_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    assessor_user_id: uuid.UUID
    probability: int
    impact: int
    score: int
    notes: str | None
    created_at: datetime
    updated_at: datetime
    version: int
    is_deleted: bool


class RiskAssessmentOut(ORMModel):

    id: uuid.UUID
    risk_id: uuid.UUID
    assessor_user_id: uuid.UUID
    probability: int
    impact: int
    score: int
    notes: str | None
    created_at: datetime
    updated_at: datetime
    version: int
    is_deleted: bool


class OpportunityAssessmentOut(ORMModel):

    id: uuid.UUID
    opportunity_id: uuid.UUID
    assessor_user_id: uuid.UUID
    probability: int
    impact: int
    score: int
    notes: str | None
    created_at: datetime
    updated_at: datetime
    version: int
    is_deleted: bool


class MatrixResponse(BaseModel):

    kind: str
    probability_axis: list[int]
    impact_axis: list[int]
    risks: list[list[int]] | None = None
    opportunities: list[list[int]] | None = None


class ActionCreate(BaseModel):

    risk_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    kind: ActionKind
    title: NonEmptyStr
    description: BoundedText | None = None
    status: ActionStatus | None = None
    owner_user_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _validate_target(self):
        # Avoid ambiguous linking; if you support global/project-level actions, allowing neither is OK.
        if self.risk_id and self.opportunity_id:
            raise ValueError("Provide only one of risk_id or opportunity_id.")
        return self


class ActionUpdate(BaseModel):

    risk_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    kind: ActionKind | None = None
    title: str | None = Field(default=None, max_length=300)
    description: BoundedText | None = None
    status: ActionStatus | None = None
    owner_user_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _validate_target(self):
        if self.risk_id and self.opportunity_id:
            raise ValueError("Provide only one of risk_id or opportunity_id.")
        return self


class ActionOut(ORMModel):

    id: uuid.UUID
    project_id: uuid.UUID
    risk_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    kind: ActionKind
    title: str
    description: str | None
    status: ActionStatus
    owner_user_id: uuid.UUID | None
    updated_at: datetime
    version: int
    is_deleted: bool


class HelpDeskTicketCreate(BaseModel):

    title: NonEmptyStr
    description: BoundedText | None = None
    category: HelpDeskCategory | None = None
    priority: HelpDeskPriority | None = None
    reporter_email: str | None = Field(default=None, max_length=320)


class HelpDeskTicketUpdate(BaseModel):

    base_version: int | None = None
    title: str | None = Field(default=None, max_length=300)
    description: BoundedText | None = None
    category: HelpDeskCategory | None = None
    priority: HelpDeskPriority | None = None
    status: HelpDeskStatus | None = None
    reporter_email: str | None = Field(default=None, max_length=320)


class HelpDeskTicketOut(ORMModel):

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    description: str | None
    category: HelpDeskCategory
    priority: HelpDeskPriority
    status: HelpDeskStatus
    reporter_email: str | None
    created_at: datetime
    updated_at: datetime
    version: int
    is_deleted: bool


class SnapshotCreateOut(BaseModel):

    batch_id: uuid.UUID
    captured_at: datetime
    risks: int = 0
    opportunities: int = 0


class SnapshotLatestOut(BaseModel):

    batch_id: uuid.UUID
    captured_at: datetime
    kind: str
    count: int


class TopItem(BaseModel):

    item_id: uuid.UUID
    title: str
    probability: int
    impact: int
    score: int


class TopBatch(BaseModel):

    batch_id: uuid.UUID
    captured_at: datetime
    top: list[TopItem]


class SyncPullRequest(BaseModel):

    project_id: uuid.UUID
    since: datetime
    # Optional per-entity pagination.
    limit_per_entity: int | None = Field(default=None, ge=1, le=50000)
    cursors: dict[str, str] | None = None
    snapshot_time: datetime | None = None

    @model_validator(mode="after")
    def _validate_pagination_snapshot(self):
        if self.cursors and self.limit_per_entity is None:
            raise ValueError("cursors require limit_per_entity")
        if self.cursors and self.snapshot_time is None:
            raise ValueError("cursors require snapshot_time")
        return self


class SyncPullResponse(BaseModel):

    server_time: datetime
    risks: list[RiskOut]
    opportunities: list[OpportunityOut]
    actions: list[ActionOut]
    # Assessments are linked to items by item_id.
    assessments: list[AssessmentOut]
    helpdesk_tickets: list[HelpDeskTicketOut] = Field(default_factory=list)
    has_more: dict[str, bool] | None = None
    cursors: dict[str, str] | None = None


class SyncChange(BaseModel):

    change_id: uuid.UUID
    entity: Literal["risk", "opportunity", "action", "assessment", "helpdesk_ticket"]
    op: Literal["upsert", "delete"]
    base_version: int | None = None
    record: dict[str, object]


class SyncPushRequest(BaseModel):

    project_id: uuid.UUID
    changes: list[SyncChange] = Field(max_length=1000)


class SyncPushResponse(BaseModel):

    accepted: int
    duplicates: int = 0
    duplicate_change_ids: list[str] = Field(default_factory=list)
    conflicts: list[dict] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)
    server_time: datetime


# Sync payload validators


class SyncItemRecord(ItemShared):

    id: uuid.UUID
    title: str | None = Field(default=None, max_length=300)
    probability: Probability | None = None
    impact: Impact | None = None
    is_deleted: bool | None = None


class SyncActionRecord(BaseModel):

    id: uuid.UUID
    item_id: uuid.UUID | None = None
    risk_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    kind: ActionKind | None = None
    title: str | None = Field(default=None, max_length=300)
    description: BoundedText | None = None
    status: ActionStatus | None = None
    owner_user_id: uuid.UUID | None = None
    is_deleted: bool | None = None


class SyncAssessmentRecord(BaseModel):

    id: uuid.UUID
    item_id: uuid.UUID | None = None
    risk_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    probability: Probability | None = None
    impact: Impact | None = None
    notes: BoundedNotes | None = None
    is_deleted: bool | None = None


class SyncHelpDeskTicketRecord(BaseModel):

    id: uuid.UUID
    title: str | None = Field(default=None, max_length=300)
    description: BoundedText | None = None
    category: HelpDeskCategory | None = None
    priority: HelpDeskPriority | None = None
    status: HelpDeskStatus | None = None
    reporter_email: str | None = Field(default=None, max_length=320)
    is_deleted: bool | None = None
