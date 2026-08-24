"""Shared field definitions for risks and opportunities."""

from __future__ import annotations

from typing import Final

# Entity statuses
DEFAULT_STATUS: Final[str] = "concept"

ALL_STATUSES: Final[tuple[str, ...]] = (
    "concept",
    "active",
    "closed",
    "deleted",
    "happened",
)

# Action statuses
ACTION_DEFAULT_STATUS: Final[str] = "open"
ACTION_STATUSES: Final[tuple[str, ...]] = ("open", "doing", "done")


# Shared metadata fields.
SCORED_ENTITY_META_KEYS: Final[tuple[str, ...]] = (
    "code",
    "description",
    "category",
    "threat",
    "triggers",
    "mitigation_plan",
    "document_url",
    "owner_user_id",
    "status",
    "identified_at",
    "status_changed_at",
    "response_at",
    "occurred_at",
    "impact_cost",
    "impact_time",
    "impact_scope",
    "impact_quality",
)

# Base keys shared by Risk + Opportunity across API/SQLite/UI payloads.
SCORED_ENTITY_BASE_KEYS: Final[tuple[str, ...]] = (
    "id",
    "project_id",
    "title",
    "probability",
    "impact",
)

# Sync metadata keys commonly present in API/SQLite.
SCORED_ENTITY_SYNC_KEYS: Final[tuple[str, ...]] = (
    "version",
    "is_deleted",
    "updated_at",
)

# Canonical column list for reading scored entities from SQLite.
# (SQLite does not persist `score`; it is computed client-side when absent.)
SCORED_ENTITY_DB_COLUMNS: Final[tuple[str, ...]] = (
    *SCORED_ENTITY_BASE_KEYS,
    *SCORED_ENTITY_META_KEYS,
    *SCORED_ENTITY_SYNC_KEYS,
)

# SQLite column definitions for schema upgrades (order matters for stable diffs).
SCORED_ENTITY_META_SQLITE_COLUMNS: Final[tuple[tuple[str, str], ...]] = (
    ("code", "TEXT"),
    ("description", "TEXT"),
    ("category", "TEXT"),
    ("threat", "TEXT"),
    ("triggers", "TEXT"),
    ("owner_user_id", "TEXT"),
    ("status", "TEXT"),
    ("identified_at", "TEXT"),
    ("status_changed_at", "TEXT"),
    ("response_at", "TEXT"),
    ("occurred_at", "TEXT"),
    ("mitigation_plan", "TEXT"),
    ("document_url", "TEXT"),
    ("impact_cost", "INTEGER"),
    ("impact_time", "INTEGER"),
    ("impact_scope", "INTEGER"),
    ("impact_quality", "INTEGER"),
)


# Allowed fields to persist into outbox entries (used for both risk + opportunity).
SCORED_ENTITY_OUTBOX_ALLOWED_KEYS: Final[frozenset[str]] = frozenset(
    (
        "id",
        "title",
        "probability",
        "impact",
        *SCORED_ENTITY_META_KEYS,
        "is_deleted",
        "created_at",
        "created_by",
    )
)


# Canonical CSV column ordering for export (used for both risk + opportunity).
SCORED_ENTITY_CSV_COLUMNS: Final[tuple[str, ...]] = (
    "code",
    "title",
    "category",
    "status",
    "owner_user_id",
    "probability",
    "impact",
    "score",
    "identified_at",
    "response_at",
    "occurred_at",
    "description",
    "threat",
    "triggers",
)
