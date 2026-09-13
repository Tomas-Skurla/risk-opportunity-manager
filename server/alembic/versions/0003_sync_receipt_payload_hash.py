# pylint: disable=invalid-name,no-member
# Alembic requires revision identifiers and dynamically proxies op directives.
"""Store canonical request hashes for verified synchronization replays.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing receipts cannot be backfilled: the original request was not
    # stored. The server rejects unverifiable replays of these rows.
    op.add_column("sync_receipts", sa.Column("payload_hash", sa.String(64)))


def downgrade() -> None:
    with op.batch_alter_table("sync_receipts") as batch_op:
        batch_op.drop_column("payload_hash")
