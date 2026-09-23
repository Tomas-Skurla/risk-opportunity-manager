"""Upgrade coverage for the transactional change-sequence migration."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import uuid
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run_alembic(database_path: Path, revision: str) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "ENV": "test",
            "SECRET_KEY": "riskapp-sequence-migration-test-secret",
            "TOKEN_HASH_KEY": "riskapp-sequence-migration-token-key",
            "ALLOW_INSECURE_DEFAULT_SECRET": "0",
            "AUTO_CREATE_SCHEMA": "0",
            "DATABASE_URL": f"sqlite+pysqlite:///{database_path.as_posix()}",
        }
    )
    subprocess.run(  # noqa: S603 -- fixed interpreter, module, and test revision
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def _insert_revision_one_records(database_path: Path) -> tuple[str, str]:
    user_id = uuid.uuid4().hex
    project_id = uuid.uuid4().hex
    empty_project_id = uuid.uuid4().hex
    item_id = uuid.uuid4().hex
    action_id = uuid.uuid4().hex
    assessment_id = uuid.uuid4().hex
    ticket_id = uuid.uuid4().hex

    with (
        closing(sqlite3.connect(database_path)) as connection,
        connection,
    ):
        connection.execute(
            """
            INSERT INTO users
                (email, password_hash, is_active, is_superuser, id)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("migration@test.com", "test-hash", 1, 0, user_id),
        )
        connection.executemany(
            """
            INSERT INTO projects
                (name, description, created_at, created_by, id)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("Existing", "", "2026-01-01 00:00:00", user_id, project_id),
                (
                    "Empty",
                    "",
                    "2026-01-01 00:00:00",
                    user_id,
                    empty_project_id,
                ),
            ],
        )
        connection.execute(
            """
            INSERT INTO items
                (type, id, project_id, title, probability, impact, status,
                 identified_at, status_changed_at, score, created_by,
                 created_at, updated_at, version, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "risk",
                item_id,
                project_id,
                "Risk",
                2,
                3,
                "active",
                "2026-01-01 00:00:00",
                "2026-01-01 00:00:00",
                6,
                user_id,
                "2026-01-01 00:00:00",
                "2026-01-01 00:00:00",
                1,
                0,
            ),
        )
        connection.execute(
            """
            INSERT INTO assessments
                (item_id, id, assessor_user_id, probability, impact, score,
                 notes, created_at, updated_at, version, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                assessment_id,
                user_id,
                3,
                4,
                12,
                "",
                "2026-01-01 12:00:00",
                "2026-01-01 12:00:00",
                1,
                0,
            ),
        )
        connection.execute(
            """
            INSERT INTO actions
                (project_id, item_id, kind, title, description, status,
                 owner_user_id, created_by, id, created_at, updated_at,
                 version, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                item_id,
                "mitigation",
                "Action",
                "",
                "open",
                None,
                user_id,
                action_id,
                "2026-01-02 00:00:00",
                "2026-01-02 00:00:00",
                1,
                0,
            ),
        )
        connection.execute(
            """
            INSERT INTO helpdesk_tickets
                (project_id, title, description, category, priority, status,
                 reporter_email, created_by, id, created_at, updated_at,
                 version, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                "Ticket",
                "",
                "other",
                "medium",
                "open",
                None,
                user_id,
                ticket_id,
                "2026-01-03 00:00:00",
                "2026-01-03 00:00:00",
                1,
                0,
            ),
        )

    return project_id, empty_project_id


def test_upgrade_backfills_all_syncable_rows_and_project_counters(tmp_path) -> None:
    database_path = tmp_path / "revision-one.sqlite3"
    _run_alembic(database_path, "0001")
    project_id, empty_project_id = _insert_revision_one_records(database_path)

    _run_alembic(database_path, "head")

    with(
        closing(sqlite3.connect(database_path)) as connection,
        connection,
    ):
        sequences = [
            connection.execute(
                f"SELECT change_sequence FROM {table_name}"  # noqa: S608
            ).fetchone()[0]
            for table_name in (
                "items",
                "assessments",
                "actions",
                "helpdesk_tickets",
            )
        ]
        states = dict(
            connection.execute(
                "SELECT project_id, last_sequence FROM sync_project_state"
            ).fetchall()
        )
        column = next(
            row
            for row in connection.execute(
                "PRAGMA table_info(helpdesk_tickets)"
            ).fetchall()
            if row[1] == "change_sequence"
        )

    assert sequences == [1, 2, 3, 4]
    assert states[project_id] == 4
    assert states[empty_project_id] == 0
    assert column[3] == 1
    assert column[4] is None
