"""Schema migration: legacy FK removal, new column additions."""

from __future__ import annotations

import sqlite3

import pytest


def _create_legacy_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.executescript("""
        CREATE TABLE projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE risks (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            title TEXT NOT NULL,
            probability INTEGER NOT NULL,
            impact INTEGER NOT NULL,
            version INTEGER NOT NULL DEFAULT 0,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT '',
            dirty INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(project_id) REFERENCES projects(id)
        );

        -- legacy broken table: FK to risks and NOT NULL risk_id
        CREATE TABLE assessments (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            risk_id TEXT NOT NULL,
            assessor_user_id TEXT NOT NULL,
            probability INTEGER NOT NULL,
            impact INTEGER NOT NULL,
            score INTEGER NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT '',
            version INTEGER NOT NULL DEFAULT 0,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT '',
            dirty INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(project_id) REFERENCES projects(id),
            FOREIGN KEY(risk_id) REFERENCES risks(id)
        );
        """)
    conn.execute("INSERT INTO projects (id, name, description) VALUES ('p1', 'P', '');")
    conn.execute(
        "INSERT INTO risks (id, project_id, title, probability, impact) VALUES ('r1','p1','R',2,2);"
    )
    conn.execute(
        "INSERT INTO assessments (id, project_id, risk_id, assessor_user_id, probability, impact, score) "
        "VALUES ('a1','p1','r1','u1',3,4,12);"
    )
    conn.commit()
    conn.close()


def test_assessment_fk_migration_removes_risks_fk_and_adds_opportunity_id(
    tmp_path,
) -> None:
    """SQLite migration drops legacy risks-FK on assessments and adds opportunity_id/item_* columns"""
    db_file = tmp_path / "legacy.db"
    _create_legacy_db(str(db_file))
    # Opening LocalStore triggers ensure_schema() and runs the migration.
    from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore

    store = LocalStore(str(db_file))
    try:
        cols = store.conn.execute("PRAGMA table_info(assessments);").fetchall()
        col_names = {str(c[1]) for c in cols}
        assert "opportunity_id" in col_names
        assert "risk_id" in col_names
        assert "item_id" in col_names
        assert "item_type" in col_names
        fks = store.conn.execute("PRAGMA foreign_key_list(assessments);").fetchall()
        assert all(str(r[2]) != "risks" for r in fks)
        row = store.conn.execute(
            "SELECT id, risk_id, opportunity_id, item_id, item_type FROM assessments WHERE id='a1';"
        ).fetchone()
        assert row is not None
        assert row["item_type"] == "risk"
        assert row["item_id"] == "r1"
        assert row["risk_id"] == "r1"
        assert row["opportunity_id"] is None
        assert store.conn.execute("PRAGMA foreign_keys;").fetchone()[0] == 1
    finally:
        store.close()


def test_project_id_migration_is_atomic_and_keeps_foreign_keys_enabled(tmp_path):
    """Promoting a local project migrates children without disabling FK checks."""
    from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore

    store = LocalStore(str(tmp_path / "promotion.db"))
    try:
        project = store.create_local_project(name="Local", project_id="local-p1")
        store.upsert_local_risk(
            risk_id="r1",
            project_id=project.id,
            title="Risk",
            probability=2,
            impact=3,
        )

        store.migrate_project_id(old_project_id=project.id, new_project_id="server-p1")

        risk = store.get_risk_row("r1")
        assert risk is not None
        assert risk["project_id"] == "server-p1"
        assert store.get_project(project.id) is None
        assert store.get_project("server-p1") is not None
        assert store.conn.execute("PRAGMA foreign_keys;").fetchone()[0] == 1

        with pytest.raises(sqlite3.IntegrityError):
            store.conn.execute(
                "UPDATE risks SET project_id='missing-project' WHERE id='r1';"
            )
    finally:
        store.conn.rollback()
        store.close()


def test_existing_outbox_gains_failure_kind_column(tmp_path) -> None:
    db_file = tmp_path / "legacy-outbox.db"
    conn = sqlite3.connect(db_file)
    conn.execute("""
        CREATE TABLE outbox (
            change_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            entity TEXT NOT NULL,
            op TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            base_version INTEGER,
            record_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            last_error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()

    from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore

    with LocalStore(str(db_file)) as store:
        columns = {
            str(row[1])
            for row in store.conn.execute("PRAGMA table_info(outbox);").fetchall()
        }
        assert "failure_kind" in columns
