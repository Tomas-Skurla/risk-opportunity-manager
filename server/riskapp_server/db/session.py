"""SQLAlchemy engine/session + ORM models."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    insert,
    select,
    update,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.types import Uuid as SAUuid

from riskapp_server.core.config import (
    AUTO_CREATE_SCHEMA,
    DATABASE_URL,
    DB_MAX_OVERFLOW,
    DB_POOL_RECYCLE,
    DB_POOL_SIZE,
    DB_STATEMENT_TIMEOUT_MS,
)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    id: Mapped[uuid.UUID] = mapped_column(
        SAUuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


_engine_kwargs: dict = {"pool_pre_ping": True}

if DATABASE_URL.startswith("sqlite"):
    # SQLite needs this with the FastAPI/Uvicorn threading model.
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    _engine_kwargs.update(
        {
            "pool_recycle": DB_POOL_RECYCLE,
            "pool_size": DB_POOL_SIZE,
            "max_overflow": DB_MAX_OVERFLOW,
        }
    )
    if DB_STATEMENT_TIMEOUT_MS and "postgresql" in DATABASE_URL:
        _engine_kwargs.setdefault("connect_args", {})
        _engine_kwargs["connect_args"].update(
            {"options": f"-c statement_timeout={DB_STATEMENT_TIMEOUT_MS}"}
        )

engine = create_engine(DATABASE_URL, **_engine_kwargs)

if DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_conn: Any, _: Any) -> None:
        """Enable SQLite foreign-key enforcement for each connection."""
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


if "postgresql" in DATABASE_URL and DB_STATEMENT_TIMEOUT_MS:

    @event.listens_for(engine, "connect")
    def _set_statement_timeout(dbapi_conn: Any, _: Any) -> None:
        # Apply the timeout per connection.
        cur = dbapi_conn.cursor()
        cur.execute("SET statement_timeout = %s", (int(DB_STATEMENT_TIMEOUT_MS),))
        cur.close()


# Keep ORM objects usable after commit in request handlers.
SessionLocal = sessionmaker( # pylint: disable=invalid-name
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    # Handy for local runs; deployments should use migrations instead.
    if AUTO_CREATE_SCHEMA:
        Base.metadata.create_all(bind=engine)


class Role(StrEnum):
    # Public domain names intentionally match their lowercase stored values.
    # pylint: disable=invalid-name
    admin = "admin"
    manager = "manager"
    member = "member"
    viewer = "viewer"


@runtime_checkable
class _StatusChangeable(Protocol):
    """Object that can record a status transition."""

    def change_status(self, new_status: str, now: datetime) -> None:
        """Record a status transition at ``now``."""


class SyncMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    # Assigned from SyncProjectState in the same transaction as every write.
    # Pull synchronization uses this value instead of wall-clock timestamps.
    change_sequence: Mapped[int] = mapped_column(
        BigInteger, default=0, nullable=False
    )

    def soft_delete(self, now: datetime) -> None:
        self.is_deleted = True
        self.updated_at = now
        self.version = int(self.version) + 1
        if isinstance(self, _StatusChangeable):
            self.change_status("deleted", now)


class RiskStatus(StrEnum):
    # Public domain names intentionally match their lowercase stored values.
    # pylint: disable=invalid-name
    concept = "concept"
    active = "active"
    closed = "closed"
    deleted = "deleted"
    happened = "happened"


class SyncReceipt(Base):
    """Stores processed sync changes; change IDs are globally unique."""

    __tablename__ = "sync_receipts"

    id = None  # type: ignore[assignment]  # suppress type checker warning
    __table_args__ = (
        # The primary key reserves a change ID across all users and projects.
        UniqueConstraint("change_id", "user_id", "project_id", name="uq_sync_receipt"),
        Index("ix_sync_receipts_project_processed", "project_id", "processed_at"),
    )

    change_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid(as_uuid=True), ForeignKey("users.id"), index=True, nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    entity: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUuid(as_uuid=True), index=True
    )
    op: Mapped[str] = mapped_column(String(20), nullable=False)

    status: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    response: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Pre-migration receipts have no original request to hash. Never replay one
    # without verifying its payload against this digest.
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    processed_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_project_ts", "project_id", "ts"),)

    ts: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, index=True, nullable=False
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid(as_uuid=True), ForeignKey("users.id"), index=True, nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    change_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid(as_uuid=True), index=True, nullable=False
    )
    entity: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid(as_uuid=True), index=True, nullable=False
    )
    op: Mapped[str] = mapped_column(String(20), nullable=False)

    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)


class User(Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(320), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Global admin flag for system-level operations (account lifecycle).
    # Project-level permissions are still handled via ProjectMember.role.
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime)


class RefreshToken(Base):
    """Rotating refresh tokens for session continuation."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("ix_refresh_tokens_user_active", "user_id", "revoked_at"),
        Index("ix_refresh_tokens_expires", "expires_at"),
        UniqueConstraint("token_hash", name="uq_refresh_token_hash"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid(as_uuid=True), ForeignKey("users.id"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)

    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(SAUuid(as_uuid=True))


class PasswordResetToken(Base):
    """One-time password reset tokens."""

    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        Index("ix_password_reset_user_active", "user_id", "used_at"),
        Index("ix_password_reset_expires", "expires_at"),
        UniqueConstraint("token_hash", name="uq_password_reset_token_hash"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid(as_uuid=True), ForeignKey("users.id"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    request_ip: Mapped[str | None] = mapped_column(String(64))


class Project(Base):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        SAUuid(as_uuid=True), ForeignKey("users.id"), nullable=False
    )


class SyncProjectState(Base):
    """Per-project high-water mark for the transactional change feed."""

    __tablename__ = "sync_project_state"
    __table_args__ = (
        CheckConstraint(
            "last_sequence >= 0", name="ck_sync_project_state_nonnegative"
        ),
    )

    id = None  # type: ignore[assignment]  # project_id is the sole primary key
    project_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    last_sequence: Mapped[int] = mapped_column(
        BigInteger, default=0, nullable=False
    )


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_user"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )


class ItemBaseMixin(SyncMixin):
    project_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    probability: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    impact: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    impact_cost: Mapped[int | None] = mapped_column(Integer)
    impact_time: Mapped[int | None] = mapped_column(Integer)
    impact_scope: Mapped[int | None] = mapped_column(Integer)
    impact_quality: Mapped[int | None] = mapped_column(Integer)
    code: Mapped[str | None] = mapped_column(String(60), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(120), index=True)
    threat: Mapped[str | None] = mapped_column(Text)
    triggers: Mapped[str | None] = mapped_column(Text)
    mitigation_plan: Mapped[str | None] = mapped_column(Text)
    document_url: Mapped[str | None] = mapped_column(Text)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUuid(as_uuid=True), ForeignKey("users.id"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(30), default=RiskStatus.concept.value, nullable=False, index=True
    )
    identified_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False, index=True
    )
    status_changed_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    response_at: Mapped[datetime | None] = mapped_column(DateTime)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime)
    score: Mapped[int] = mapped_column(Integer, default=1, index=True, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        SAUuid(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    def change_status(self, new_status: str, now: datetime) -> None:
        if self.status != new_status:
            self.status = new_status
            self.status_changed_at = now
            if new_status == "happened":
                self.occurred_at = now


class Item(Base, ItemBaseMixin):
    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_items_project_code"),
        # Domain rules: probability/impact are qualitative (1..5).
        CheckConstraint("probability BETWEEN 1 AND 5", name="ck_items_probability_1_5"),
        CheckConstraint("impact BETWEEN 1 AND 5", name="ck_items_impact_1_5"),
        Index(
            "ix_items_project_type_deleted_score",
            "project_id",
            "type",
            "is_deleted",
            "score",
        ),
        Index("ix_items_project_type_updated", "project_id", "type", "updated_at"),
        Index(
            "ix_items_project_type_change_sequence",
            "project_id",
            "type",
            "change_sequence",
        ),
    )
    type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)


def _validate_scale_1_5(field: str, value: int | None) -> None:
    if value is None:
        raise ValueError(f"{field} must not be null")
    if not 1 <= int(value) <= 5:
        raise ValueError(f"{field} must be in range 1..5 (got {value!r})")


def _score(probability: int, impact: int) -> int:
    return int(probability) * int(impact)


class AssessmentMixin(SyncMixin):
    assessor_user_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    probability: Mapped[int] = mapped_column(Integer, nullable=False)
    impact: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text)


class Assessment(Base, AssessmentMixin):
    __tablename__ = "assessments"
    __table_args__ = (
        UniqueConstraint("item_id", "assessor_user_id", name="uq_item_assessor"),
        Index("ix_assessments_item_updated", "item_id", "updated_at"),
        Index("ix_assessments_assessor_updated", "assessor_user_id", "updated_at"),
        Index(
            "ix_assessments_item_change_sequence", "item_id", "change_sequence"
        ),
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid(as_uuid=True),
        ForeignKey("items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    @property
    def risk_id(self) -> uuid.UUID:  # client/API compatibility
        return self.item_id

    @property
    def opportunity_id(self) -> uuid.UUID:  # client/API compatibility
        return self.item_id


@event.listens_for(Item, "before_insert")
@event.listens_for(Item, "before_update")
@event.listens_for(Assessment, "before_insert")
@event.listens_for(Assessment, "before_update")
def _compute_score(_mapper: Any, _connection: Any, target: Any) -> None:
    # Keep score in sync with probability × impact.
    _validate_scale_1_5("probability", getattr(target, "probability", None))
    _validate_scale_1_5("impact", getattr(target, "impact", None))
    target.score = _score(target.probability, target.impact)


class ActionKind(StrEnum):
    # Public domain names intentionally match their lowercase stored values.
    # pylint: disable=invalid-name
    mitigation = "mitigation"
    contingency = "contingency"
    exploit = "exploit"


class ActionStatus(StrEnum):
    # Public domain names intentionally match their lowercase stored values.
    # pylint: disable=invalid-name
    open = "open"
    doing = "doing"
    done = "done"


class HelpDeskStatus(StrEnum):
    # Public domain names intentionally match their lowercase stored values.
    # pylint: disable=invalid-name
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"
    closed = "closed"


class HelpDeskPriority(StrEnum):
    # Public domain names intentionally match their lowercase stored values.
    # pylint: disable=invalid-name
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class HelpDeskCategory(StrEnum):
    # Public domain names intentionally match their lowercase stored values.
    # pylint: disable=invalid-name
    bug = "bug"
    question = "question"
    feature_request = "feature_request"
    access = "access"
    other = "other"


class HelpDeskTicket(Base, SyncMixin):
    __tablename__ = "helpdesk_tickets"
    __table_args__ = (
        Index(
            "ix_helpdesk_project_deleted_updated",
            "project_id",
            "is_deleted",
            "updated_at",
        ),
        Index(
            "ix_helpdesk_project_change_sequence",
            "project_id",
            "change_sequence",
        ),
        Index(
            "ix_helpdesk_project_status_created", "project_id", "status", "created_at"
        ),
        Index("ix_helpdesk_project_priority", "project_id", "priority"),
        CheckConstraint(
            "status IN ('open','in_progress','resolved','closed')",
            name="ck_helpdesk_status",
        ),
        CheckConstraint(
            "priority IN ('low','medium','high','critical')",
            name="ck_helpdesk_priority",
        ),
        CheckConstraint(
            "category IN ('bug','question','feature_request','access','other')",
            name="ck_helpdesk_category",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(
        String(40), nullable=False, default=HelpDeskCategory.other.value, index=True
    )
    priority: Mapped[str] = mapped_column(
        String(20), nullable=False, default=HelpDeskPriority.medium.value, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=HelpDeskStatus.open.value, index=True
    )
    reporter_email: Mapped[str | None] = mapped_column(String(320))
    created_by: Mapped[uuid.UUID] = mapped_column(
        SAUuid(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )


class Action(Base, SyncMixin):
    __tablename__ = "actions"
    __table_args__ = (
        Index(
            "ix_actions_project_deleted_updated",
            "project_id",
            "is_deleted",
            "updated_at",
        ),
        Index("ix_actions_project_item", "project_id", "item_id"),
        Index(
            "ix_actions_project_change_sequence", "project_id", "change_sequence"
        ),
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid(as_uuid=True),
        ForeignKey("items.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ActionStatus.open.value, index=True
    )

    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUuid(as_uuid=True), ForeignKey("users.id"), index=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        SAUuid(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )


class ScoreSnapshot(Base):
    __tablename__ = "score_snapshots"
    __table_args__ = (
        Index(
            "ix_score_snapshots_project_kind_captured",
            "project_id",
            "kind",
            "captured_at",
        ),
        Index("ix_score_snapshots_batch_score", "batch_id", "score"),
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid(as_uuid=True), index=True, nullable=False
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)

    project_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(20), index=True, nullable=False)

    item_id: Mapped[uuid.UUID] = mapped_column(
        SAUuid(as_uuid=True), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)

    probability: Mapped[int] = mapped_column(Integer, nullable=False)
    impact: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[int] = mapped_column(Integer, index=True, nullable=False)

    created_by: Mapped[uuid.UUID] = mapped_column(
        SAUuid(as_uuid=True), ForeignKey("users.id"), index=True, nullable=False
    )


def _next_change_sequence(connection: Any, project_id: uuid.UUID) -> int:
    """Reserve the next sequence while holding the project counter's write lock."""
    result = connection.execute(
        update(SyncProjectState)
        .where(SyncProjectState.project_id == project_id)
        .values(last_sequence=SyncProjectState.last_sequence + 1)
    )
    if result.rowcount != 1:
        raise RuntimeError(f"Missing synchronization state for project {project_id}")
    return int(
        connection.execute(
            select(SyncProjectState.last_sequence).where(
                SyncProjectState.project_id == project_id
            )
        ).scalar_one()
    )


def _sync_entity_project_id(connection: Any, target: Any) -> uuid.UUID:
    if isinstance(target, Assessment):
        project_id = connection.execute(
            select(Item.project_id).where(Item.id == target.item_id)
        ).scalar_one_or_none()
        if project_id is None:
            raise RuntimeError(
                f"Cannot sequence assessment {target.id}: parent item is missing"
            )
        return project_id
    return target.project_id


@event.listens_for(Project, "after_insert")
def _create_project_sync_state(_mapper: Any, connection: Any, target: Project) -> None:
    """Create the counter atomically with a new project."""
    connection.execute(
        insert(SyncProjectState).values(project_id=target.id, last_sequence=0)
    )


@event.listens_for(Item, "before_insert")
@event.listens_for(Item, "before_update")
@event.listens_for(Assessment, "before_insert")
@event.listens_for(Assessment, "before_update")
@event.listens_for(Action, "before_insert")
@event.listens_for(Action, "before_update")
@event.listens_for(HelpDeskTicket, "before_insert")
@event.listens_for(HelpDeskTicket, "before_update")
def _assign_change_sequence(_mapper: Any, connection: Any, target: Any) -> None:
    """Stamp every syncable write from the transaction-owned project counter."""
    project_id = _sync_entity_project_id(connection, target)
    target.change_sequence = _next_change_sequence(connection, project_id)
