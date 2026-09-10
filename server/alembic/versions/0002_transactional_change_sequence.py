"""transactional monotonic change sequence

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-09

"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _sync_tables() -> dict[str, sa.TableClause]:
    identifier = sa.Uuid()
    timestamp = sa.DateTime()
    return {
        "items": sa.table(
            "items",
            sa.column("id", identifier),
            sa.column("project_id", identifier),
            sa.column("updated_at", timestamp),
            sa.column("change_sequence", sa.BigInteger()),
        ),
        "actions": sa.table(
            "actions",
            sa.column("id", identifier),
            sa.column("project_id", identifier),
            sa.column("updated_at", timestamp),
            sa.column("change_sequence", sa.BigInteger()),
        ),
        "assessments": sa.table(
            "assessments",
            sa.column("id", identifier),
            sa.column("item_id", identifier),
            sa.column("updated_at", timestamp),
            sa.column("change_sequence", sa.BigInteger()),
        ),
        "helpdesk_tickets": sa.table(
            "helpdesk_tickets",
            sa.column("id", identifier),
            sa.column("project_id", identifier),
            sa.column("updated_at", timestamp),
            sa.column("change_sequence", sa.BigInteger()),
        ),
    }


def _timestamp_key(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _backfill_change_sequences() -> None:
    bind = op.get_bind()
    tables = _sync_tables()
    projects = sa.table("projects", sa.column("id", sa.Uuid()))
    state = sa.table(
        "sync_project_state",
        sa.column("project_id", sa.Uuid()),
        sa.column("last_sequence", sa.BigInteger()),
    )

    project_ids = list(bind.execute(sa.select(projects.c.id)).scalars())
    changes: dict[Any, list[tuple[str, Any, Any, sa.TableClause]]] = defaultdict(
        list
    )

    for table_name in ("items", "actions", "helpdesk_tickets"):
        table = tables[table_name]
        rows = bind.execute(
            sa.select(table.c.id, table.c.project_id, table.c.updated_at)
        )
        for entity_id, project_id, updated_at in rows:
            changes[project_id].append(
                (table_name, entity_id, updated_at, table)
            )

    assessments = tables["assessments"]
    items = tables["items"]
    assessment_rows = bind.execute(
        sa.select(
            assessments.c.id,
            items.c.project_id,
            assessments.c.updated_at,
        ).select_from(
            assessments.join(items, assessments.c.item_id == items.c.id)
        )
    )
    for entity_id, project_id, updated_at in assessment_rows:
        changes[project_id].append(
            ("assessments", entity_id, updated_at, assessments)
        )

    state_rows: list[dict[str, Any]] = []
    for project_id in project_ids:
        project_changes = changes.get(project_id, [])
        project_changes.sort(
            key=lambda row: (_timestamp_key(row[2]), row[0], str(row[1]))
        )
        for sequence, (_name, entity_id, _updated_at, table) in enumerate(
            project_changes, start=1
        ):
            bind.execute(
                sa.update(table)
                .where(table.c.id == entity_id)
                .values(change_sequence=sequence)
            )
        state_rows.append(
            {
                "project_id": project_id,
                "last_sequence": len(project_changes),
            }
        )

    if state_rows:
        bind.execute(sa.insert(state), state_rows)


def _add_sequence_column(table_name: str) -> None:
    with op.batch_alter_table(table_name, schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "change_sequence",
                sa.BigInteger(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )


def _drop_sequence_default(table_name: str) -> None:
    with op.batch_alter_table(table_name, schema=None) as batch_op:
        batch_op.alter_column(
            "change_sequence",
            existing_type=sa.BigInteger(),
            nullable=False,
            server_default=None,
        )


def upgrade() -> None:
    """Add and backfill transaction-owned sequence watermarks."""
    op.create_table(
        "sync_project_state",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "last_sequence >= 0", name="ck_sync_project_state_nonnegative"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("project_id"),
    )

    for table_name in ("items", "actions", "assessments", "helpdesk_tickets"):
        _add_sequence_column(table_name)

    _backfill_change_sequences()

    for table_name in ("items", "actions", "assessments", "helpdesk_tickets"):
        _drop_sequence_default(table_name)

    with op.batch_alter_table("items", schema=None) as batch_op:
        batch_op.create_index(
            "ix_items_project_type_change_sequence",
            ["project_id", "type", "change_sequence"],
            unique=False,
        )
    with op.batch_alter_table("actions", schema=None) as batch_op:
        batch_op.create_index(
            "ix_actions_project_change_sequence",
            ["project_id", "change_sequence"],
            unique=False,
        )
    with op.batch_alter_table("assessments", schema=None) as batch_op:
        batch_op.create_index(
            "ix_assessments_item_change_sequence",
            ["item_id", "change_sequence"],
            unique=False,
        )
    with op.batch_alter_table("helpdesk_tickets", schema=None) as batch_op:
        batch_op.create_index(
            "ix_helpdesk_project_change_sequence",
            ["project_id", "change_sequence"],
            unique=False,
        )


def downgrade() -> None:
    """Remove sequence watermarks and return to timestamp-only pulls."""
    index_names = {
        "items": "ix_items_project_type_change_sequence",
        "actions": "ix_actions_project_change_sequence",
        "assessments": "ix_assessments_item_change_sequence",
        "helpdesk_tickets": "ix_helpdesk_project_change_sequence",
    }
    for table_name, index_name in index_names.items():
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.drop_index(index_name)
            batch_op.drop_column("change_sequence")
    op.drop_table("sync_project_state")
