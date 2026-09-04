from __future__ import annotations

import json
import logging
from typing import Any

from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore, utc_iso
from riskapp_client.adapters.local_storage.sync_outbox_queue import OutboxStore


class SyncService:
    def __init__(
        self, store: LocalStore, outbox: OutboxStore, remote: Any | None
    ) -> None:
        self._store = store
        self._outbox = outbox
        self._remote = remote

    def can_sync(self) -> bool:
        return self._remote is not None

    def pending_count(self, project_id: str | None = None) -> int:
        return self._outbox.pending_count(project_id)

    def blocked_count(self, project_id: str | None = None) -> int:
        return self._outbox.blocked_count(project_id)

    def conflict_count(self, project_id: str | None = None) -> int:
        return self._outbox.conflict_count(project_id)

    def error_count(self, project_id: str | None = None) -> int:
        return self._outbox.error_count(project_id)

    def last_sync_time(self, project_id: str | None) -> str | None:
        if not project_id:
            return None
        value = self._store.get_last_server_time(project_id)
        if not value or str(value).startswith("1970-01-01"):
            return None
        return str(value)

    def blocked_details(self, project_id: str | None = None) -> list[dict[str, Any]]:
        return self._outbox.get_blocked_changes(project_id)

    def _json_snippet(self, obj: object, *, limit: int = 500) -> str:
        try:
            return json.dumps(obj)[:limit]
        except Exception:  # noqa: BLE001
            return str(obj)[:limit]

    def _extract_change_ids(self, items: object) -> list[str]:
        return [
            str(it.get("change_id"))
            for it in (items or [])
            if isinstance(it, dict) and it.get("change_id")
        ]

    def _push_once(
        self, project_id: str, changes: list[dict[str, Any]]
    ) -> dict[str, Any]:
        if not self._remote:
            raise RuntimeError(
                "No server configured (start the app online at least once)."
            )
        return self._remote.sync_push(project_id, changes)

    def _process_push(
        self, project_id: str, changes: list[dict[str, Any]]
    ) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]]]:
        resp = self._push_once(project_id, changes)
        sent_ids = [
            str(c.get("change_id") or "") for c in changes if c.get("change_id")
        ]

        conflicts = list(resp.get("conflicts") or [])
        errors = list(resp.get("errors") or [])
        dup_ids = [str(x) for x in (resp.get("duplicate_change_ids") or []) if x]

        conflict_ids = set(self._extract_change_ids(conflicts))
        error_ids = set(self._extract_change_ids(errors))

        processed = (set(sent_ids) - conflict_ids - error_ids) | set(dup_ids)
        if processed:
            self._outbox.delete_outbox_ids(list(processed))

        for c in conflicts:
            cid = str(c.get("change_id") or "")
            if cid:
                self._outbox.block_outbox_id(
                    cid, self._json_snippet(c), failure_kind="conflict"
                )
        for e in errors:
            cid = str(e.get("change_id") or "")
            if cid:
                self._outbox.block_outbox_id(
                    cid, self._json_snippet(e), failure_kind="error"
                )

        return (len(processed), conflicts, errors)

    def sync_project(self, project_id: str) -> dict[str, Any]:
        if not self._remote:
            raise RuntimeError(
                "No server configured (start the app online at least once)."
            )

        effective_project_id = project_id

        summary: dict[str, Any] = {
            "pushed": 0,
            "conflicts": 0,
            "errors": 0,
            "blocked": 0,
            "blocked_details": [],
            "pulled_risks": 0,
            "pulled_opportunities": 0,
            "pulled_actions": 0,
            "pulled_assessments": 0,
            "pulled_helpdesk_tickets": 0,
        }

        if str(project_id).startswith("local-"):
            promoted = self._promote_local_project(project_id)
            if promoted and promoted != project_id:
                summary["project_id_migrated_from"] = project_id
                summary["project_id_migrated_to"] = promoted
                effective_project_id = promoted

        changes = self._outbox.get_pending_changes(effective_project_id, limit=100)
        if changes:
            pushed, conflicts, errors = self._process_push(
                effective_project_id, changes
            )
            summary["pushed"] += pushed
            summary["conflicts"] += len(self._extract_change_ids(conflicts))
            summary["errors"] += len(self._extract_change_ids(errors))

        since = self._store.get_last_server_time(effective_project_id)

        try:
            pull = self._remote.sync_pull(effective_project_id, since)
        except Exception as exc:  # noqa: BLE001
            status = getattr(exc, "status", None)
            if int(status or 0) != 413:
                raise
            pull = self._pull_paginated(effective_project_id, since)

        server_time = str(pull.get("server_time") or utc_iso())
        # Apply parent items before child records. This lets assessment pulls
        # that only contain item_id be classified as risk vs opportunity.
        for key in ("risks", "opportunities", "actions", "assessments"):
            items = pull.get(key) or []
            getattr(self._store, f"apply_pull_{key}")(effective_project_id, items)
            summary[f"pulled_{key}"] = len(items)

        helpdesk_items = pull.get("helpdesk_tickets") or []
        if helpdesk_items:
            self._store.apply_pull_helpdesk_tickets(
                effective_project_id, helpdesk_items
            )
        summary["pulled_helpdesk_tickets"] = len(helpdesk_items)

        self._store.set_last_server_time(effective_project_id, server_time)
        summary["blocked_details"] = self.blocked_details(effective_project_id)
        summary["blocked"] = len(summary["blocked_details"])
        return summary

    def _promote_local_project(self, local_project_id: str) -> str | None:
        if not self._remote:
            return None

        p = self._store.get_project(local_project_id)
        if not p:
            return None

        if not p.created_by:
            raise RuntimeError(
                "This local-only project cannot be synced. "
                "Create a new project after logging in to sync your work."
            )

        if not hasattr(self._remote, "create_project"):
            return None

        name = p.name or "Local Project"
        try:
            existing = self._remote.list_projects() or []
            existing_names = {ep.name for ep in existing}
            if name in existing_names:
                n = 2
                while f"{name} ({n})" in existing_names:
                    n += 1
                name = f"{name} ({n})"
        except (AttributeError, RuntimeError):
            logging.getLogger(__name__).debug(
                "Server-side name collision check failed", exc_info=True
            )

        created = self._remote.create_project(
            name=name, description=p.description or ""
        )

        new_id = getattr(created, "id", None) if created else None
        if not new_id:
            return None

        self._store.conn.execute(
            "UPDATE projects SET name = ? WHERE id = ?;",
            (name, local_project_id),
        )
        self._store.conn.commit()

        self._store.migrate_project_id(
            old_project_id=local_project_id, new_project_id=str(new_id)
        )
        self._store.upsert_projects([created])
        return str(new_id)

    def _pull_paginated(self, project_id: str, since: str) -> dict[str, Any]:

        limit = 2000
        cursors: dict[str, str] = {}
        snapshot_time: str | None = None

        merged: dict[str, Any] = {
            "server_time": None,
            "risks": [],
            "opportunities": [],
            "actions": [],
            "assessments": [],
            "helpdesk_tickets": [],
        }

        while True:
            resp = self._remote.sync_pull(
                project_id,
                since,
                limit_per_entity=limit,
                cursors=cursors or None,
                snapshot_time=snapshot_time,
            )
            page_snapshot = str(resp.get("server_time") or "")
            if not page_snapshot:
                raise RuntimeError("Sync pagination response omitted server_time")
            if snapshot_time is None:
                snapshot_time = page_snapshot
                merged["server_time"] = page_snapshot
            elif page_snapshot != snapshot_time:
                raise RuntimeError("Sync pagination snapshot changed between pages")
            for key in (
                "risks",
                "opportunities",
                "actions",
                "assessments",
                "helpdesk_tickets",
            ):
                merged[key].extend(list(resp.get(key) or []))

            has_more = resp.get("has_more") or {}
            next_cursors = resp.get("cursors") or {}
            if not isinstance(has_more, dict) or not isinstance(next_cursors, dict):
                raise RuntimeError("Invalid sync pagination metadata")

            more_keys = [key for key, more in has_more.items() if bool(more)]
            if not more_keys:
                break

            stalled = [
                str(key)
                for key in more_keys
                if not next_cursors.get(key)
                or next_cursors.get(key) == cursors.get(key)
            ]
            if stalled:
                raise RuntimeError(
                    "Sync pagination did not advance for: " + ", ".join(stalled)
                )
            cursors = {
                str(key): str(value) for key, value in next_cursors.items() if value
            }

        return merged
