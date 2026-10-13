"""Projects and application metadata kept in the local store."""

from __future__ import annotations

import uuid

from riskapp_client.adapters.local_storage.sqlite_base import SqliteStoreBase
from riskapp_client.domain.domain_models import Project

# Rows that make a cached project worth keeping after the server drops it.
_PROJECT_DATA_TABLES = (
    "risks",
    "opportunities",
    "actions",
    "assessments",
    "helpdesk_tickets",
    "outbox",
)

_BOOTSTRAP_META_KEYS = (
    "bootstrap_project_id",
    "bootstrap_user_project_id",
    "bootstrap_anon_project_id",
)


class ProjectStoreMixin(SqliteStoreBase):
    """Projects, including local-only ones, and key/value metadata."""

    def list_projects(self) -> list[Project]:
        rows = self.conn.execute(
            "SELECT id, name, description, created_by FROM projects ORDER BY name;"
        ).fetchall()
        return [
            Project(
                id=r["id"],
                name=r["name"],
                description=r["description"],
                created_by=str(r["created_by"] or ""),
            )
            for r in rows
        ]

    def get_project(self, project_id: str) -> Project | None:
        row = self.conn.execute(
            "SELECT id, name, description, created_by FROM projects WHERE id=?;",
            (project_id,),
        ).fetchone()
        if not row:
            return None
        return Project(
            id=str(row["id"]),
            name=str(row["name"]),
            description=str(row["description"] or ""),
            created_by=str(row["created_by"] or ""),
        )

    def create_local_project(
        self,
        *,
        name: str,
        description: str = "",
        project_id: str | None = None,
        created_by: str | None = None,
    ) -> Project:
        pid = str(project_id or f"local-{uuid.uuid4()}")
        owner = (
            created_by
            if created_by is not None
            else (self.get_meta("last_email") or "")
        )
        self._upsert_row(
            "projects",
            {
                "id": pid,
                "name": str(name or "Local Project"),
                "description": description or "",
                "created_by": owner,
            },
        )
        self._commit_if_needed()
        return Project(
            id=pid,
            name=str(name or "Local Project"),
            description=description or "",
            created_by=owner,
        )

    def upsert_projects(self, projects: list[Project]) -> None:
        cur = self.conn.cursor()
        for p in projects:
            self._upsert_row(
                "projects",
                {
                    "id": p.id,
                    "name": p.name,
                    "description": p.description or "",
                    "created_by": p.created_by or "",
                },
                cur,
            )
        self._commit_if_needed()

    def sync_projects(self, server_projects: list[Project]) -> None:
        """Merge server project list with local cache.

        Rules:
        - local-* projects are NEVER touched (managed by offline/sync flow).
        - Projects that exist on server are upserted.
        - Projects NOT on server are only removed if they have ZERO local data
          (no risks, opportunities, actions, assessments, outbox entries).
          This prevents data loss after promotion or during transient issues.
        """
        server_ids = {p.id for p in server_projects}
        local_rows = self.conn.execute("SELECT id FROM projects;").fetchall()
        for row in local_rows:
            pid = str(row["id"])
            if pid.startswith("local-") or pid in server_ids:
                continue
            if self._has_local_data(pid):
                continue
            # Clean up an empty project the user can no longer access.
            self.conn.execute("DELETE FROM sync_state WHERE project_id = ?;", (pid,))
            self.conn.execute("DELETE FROM projects WHERE id = ?;", (pid,))
        self.upsert_projects(server_projects)
        self._commit_if_needed()

    def _has_local_data(self, project_id: str) -> bool:
        return any(
            self.conn.execute(
                f"SELECT 1 FROM {table} WHERE project_id = ? LIMIT 1;",  # noqa: S608
                (project_id,),
            ).fetchone()
            for table in _PROJECT_DATA_TABLES
        )

    def migrate_project_id(self, *, old_project_id: str, new_project_id: str) -> None:
        """Replace a local project id with the server project id."""
        old_id = str(old_project_id)
        new_id = str(new_project_id)
        if not old_id or not new_id or old_id == new_id:
            return
        p = self.get_project(old_id)
        if not p:
            return
        # The parent id and every child reference move atomically. Deferring FK
        # checks until commit avoids the previous PRAGMA foreign_keys=OFF flow,
        # which accidentally left enforcement disabled for the connection.
        with self.write_transaction():
            cur = self.conn.cursor()
            cur.execute("PRAGMA defer_foreign_keys=ON;")
            self._upsert_row(
                "projects",
                {
                    "id": new_id,
                    "name": p.name,
                    "description": p.description or "",
                    "created_by": p.created_by or "",
                },
                cur,
            )
            for table in (*_PROJECT_DATA_TABLES, "sync_state"):
                cur.execute(
                    f"UPDATE {table} SET project_id=? WHERE project_id=?;",  # noqa: S608
                    (new_id, old_id),
                )
            cur.execute("DELETE FROM projects WHERE id=?;", (old_id,))
            for key in _BOOTSTRAP_META_KEYS:
                if (self.get_meta(key) or "") == old_id:
                    self.set_meta(key, new_id)

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key=?;", (key,)
        ).fetchone()
        return str(row["value"]) if row else None

    def set_meta(self, key: str, value: str) -> None:
        self._upsert_row("meta", {"key": key, "value": value}, pk="key")
        self._commit_if_needed()
