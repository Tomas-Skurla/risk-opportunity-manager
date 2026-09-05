from __future__ import annotations

import logging
from typing import Any

from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore, utc_iso
from riskapp_client.adapters.local_storage.sync_outbox_queue import OutboxStore

_SYNC_EPOCH = "1970-01-01T00:00:00"
_CONFLICT_RESOLUTIONS = {"keep_mine", "use_server", "later"}


class SyncService:
    def __init__(
        self, store: LocalStore, outbox: OutboxStore, remote: Any | None
    ) -> None:
        self._store = store
        self._outbox = outbox
        self._remote = remote
        if remote is not None:
            # A newly constructed online backend represents a fresh authenticated
            # session, so changes blocked by the previous session may try again.
            self._outbox.release_authentication_blocks()

    def can_sync(self) -> bool:
        return self._remote is not None

    def pending_count(self, project_id: str | None = None) -> int:
        return self._outbox.pending_count(project_id)

    def blocked_count(self, project_id: str | None = None) -> int:
        return self._outbox.blocked_count(project_id)

    def deferred_count(self, project_id: str | None = None) -> int:
        return self._outbox.deferred_count(project_id)

    def next_retry_at(self, project_id: str | None = None) -> str | None:
        return self._outbox.next_retry_at(project_id)

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

    def conflict_details(self, project_id: str | None = None) -> list[dict[str, Any]]:
        """Return only conflicts that are waiting for an explicit decision."""
        return [
            item
            for item in self._outbox.get_blocked_changes(project_id)
            if item.get("failure_kind") == "conflict"
        ]

    def _require_conflict(self, change_id: str) -> dict[str, Any]:
        conflict = self._outbox.get_blocked_change(str(change_id))
        if conflict is None:
            raise KeyError("Synchronization conflict no longer exists")
        if conflict.get("failure_kind") != "conflict":
            raise ValueError("The selected outbox item is not a version conflict")
        return conflict

    def _current_local_version(self, conflict: dict[str, Any]) -> int:
        entity = str(conflict["entity"])
        entity_id = str(conflict["entity_id"])
        getters = {
            "risk": self._store.get_risk_project_and_version,
            "opportunity": self._store.get_opportunity_project_and_version,
            "action": self._store.get_action_project_and_version,
            "assessment": self._store.get_assessment_project_and_version,
            "helpdesk_ticket": self._store.get_helpdesk_ticket_project_and_version,
        }
        getter = getters.get(entity)
        if getter is None:
            raise ValueError(f"Unsupported conflict entity: {entity!r}")
        local_project_id, version = getter(entity_id)
        if str(local_project_id) != str(conflict["project_id"]):
            raise RuntimeError("The conflicted item belongs to another project")
        return int(version)

    def _normalize_server_record(
        self, conflict: dict[str, Any]
    ) -> dict[str, Any]:
        raw = conflict.get("server_record")
        if not isinstance(raw, dict) or not raw:
            raise RuntimeError(
                "The server copy is unavailable for this conflict; choose "
                "Keep mine or leave it for later."
            )
        record = dict(raw)
        entity = str(conflict["entity"])
        entity_id = str(conflict["entity_id"])
        project_id = str(conflict["project_id"])
        if str(record.get("id") or "") != entity_id:
            raise RuntimeError("The saved server copy does not match this item")
        record_project_id = record.get("project_id")
        if record_project_id and str(record_project_id) != project_id:
            raise RuntimeError("The saved server copy belongs to another project")
        record["project_id"] = project_id

        if entity in {"risk", "opportunity"}:
            server_type = str(record.get("type") or entity)
            if server_type != entity:
                raise RuntimeError(
                    "This conflict changes the entity type and cannot be "
                    "resolved automatically."
                )

        # Older stored conflict payloads assigned item_id to both aliases.
        # Resolve an ambiguous parent from the authoritative local parent rows.
        if entity in {"action", "assessment"}:
            item_id = str(record.get("item_id") or "")
            risk_id = str(record.get("risk_id") or "")
            opportunity_id = str(record.get("opportunity_id") or "")
            if not item_id:
                item_id = risk_id or opportunity_id
                record["item_id"] = item_id
            if item_id and bool(risk_id) == bool(opportunity_id):
                is_opportunity = self._store.conn.execute(
                    "SELECT 1 FROM opportunities WHERE project_id=? AND id=?;",
                    (project_id, item_id),
                ).fetchone()
                is_risk = self._store.conn.execute(
                    "SELECT 1 FROM risks WHERE project_id=? AND id=?;",
                    (project_id, item_id),
                ).fetchone()
                if bool(is_opportunity) == bool(is_risk):
                    raise RuntimeError(
                        "The server copy has an ambiguous parent and cannot be "
                        "applied safely."
                    )
                record["risk_id"] = item_id if is_risk else None
                record["opportunity_id"] = item_id if is_opportunity else None
        return record

    def _apply_server_record(
        self, conflict: dict[str, Any], record: dict[str, Any]
    ) -> None:
        project_id = str(conflict["project_id"])
        entity = str(conflict["entity"])
        appliers = {
            "risk": self._store.apply_pull_risks,
            "opportunity": self._store.apply_pull_opportunities,
            "action": self._store.apply_pull_actions,
            "assessment": self._store.apply_pull_assessments,
            "helpdesk_ticket": self._store.apply_pull_helpdesk_tickets,
        }
        apply_record = appliers.get(entity)
        if apply_record is None:
            raise ValueError(f"Unsupported conflict entity: {entity!r}")
        apply_record(project_id, [record])

    def resolve_conflict(
        self, change_id: str, resolution: str
    ) -> dict[str, Any]:
        """Resolve one persisted conflict without silently discarding either side."""
        choice = str(resolution or "").strip().lower()
        if choice not in _CONFLICT_RESOLUTIONS:
            raise ValueError(
                "resolution must be one of: keep_mine, use_server, later"
            )

        if choice == "later":
            conflict = self._require_conflict(change_id)
            return {
                "change_id": str(change_id),
                "resolution": choice,
                "resolved": False,
                "project_id": str(conflict["project_id"]),
            }

        with self._store.write_transaction():
            conflict = self._require_conflict(change_id)
            project_id = str(conflict["project_id"])

            if choice == "keep_mine":
                try:
                    server_version = int(conflict.get("server_version"))
                except (TypeError, ValueError) as exc:
                    raise RuntimeError(
                        "The current server version is unavailable; leave this "
                        "conflict blocked for later."
                    ) from exc
                if server_version < 1:
                    raise RuntimeError("The current server version is invalid")
                target_version = max(
                    server_version, self._current_local_version(conflict)
                )
                replacement_id = self._outbox.requeue_conflict_with_new_id(
                    str(change_id), target_version
                )
                if not replacement_id:
                    raise RuntimeError("The conflict disappeared before it was resolved")
                return {
                    "change_id": str(change_id),
                    "replacement_change_id": replacement_id,
                    "resolution": choice,
                    "resolved": True,
                    "project_id": project_id,
                    "base_version": target_version,
                }

            server_record = self._normalize_server_record(conflict)
            self._outbox.delete_outbox_ids([str(change_id)])
            self._apply_server_record(conflict, server_record)
            # The saved conflict record is a point-in-time copy. Rewind the
            # watermark so the next sync cannot miss a newer server update.
            self._store.set_last_server_time(project_id, _SYNC_EPOCH)
            return {
                "change_id": str(change_id),
                "resolution": choice,
                "resolved": True,
                "project_id": project_id,
            }

    def _extract_change_ids(self, items: object) -> list[str]:
        return [
            str(it.get("change_id"))
            for it in (items or [])
            if isinstance(it, dict) and it.get("change_id")
        ]

    @staticmethod
    def _classify_status(status: int) -> tuple[str, bool]:
        status = int(status or 0)
        if status == 401:
            return "authentication", False
        if status == 403:
            return "permission", False
        if status == 0 or status in {408, 425, 429} or status >= 500:
            return "transient", True
        return "validation", False

    def _request_failure(self, exc: Exception, *, phase: str) -> dict[str, Any]:
        status_value = getattr(exc, "status", None)
        if status_value is None:
            raise exc
        status = int(status_value or 0)
        failure_kind, retryable = self._classify_status(status)
        return {
            "status": "error",
            "reason": f"{phase}_request_failed",
            "detail": str(getattr(exc, "detail", None) or exc),
            "http_status": status,
            "failure_kind": failure_kind,
            "retryable": retryable,
            "request_failed": True,
        }

    @staticmethod
    def _normalize_error(item: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(item)
        reason = str(normalized.get("reason") or "")
        failure_kind = str(normalized.get("failure_kind") or "")
        if not failure_kind:
            if reason == "insufficient_permissions":
                failure_kind = "permission"
            elif reason == "internal_error":
                failure_kind = "transient"
            else:
                failure_kind = "validation"
        normalized["failure_kind"] = failure_kind
        normalized["retryable"] = bool(
            normalized.get("retryable") or failure_kind == "transient"
        )
        return normalized

    @staticmethod
    def _state_for_failure_kind(failure_kind: str) -> str:
        return {
            "transient": "retry_wait",
            "authentication": "authentication_required",
            "permission": "permission_denied",
            "validation": "attention_required",
            "conflict": "attention_required",
        }.get(failure_kind, "attention_required")

    def _finish_summary(
        self, summary: dict[str, Any], project_id: str
    ) -> dict[str, Any]:
        summary["blocked_details"] = self.blocked_details(project_id)
        summary["blocked"] = len(summary["blocked_details"])
        summary["next_retry_at"] = self.next_retry_at(project_id)
        if summary.get("state") == "complete" and summary["blocked"]:
            summary["state"] = "attention_required"
        elif summary.get("state") == "complete" and summary.get("deferred"):
            summary["state"] = "retry_wait"
        return summary

    def _record_request_failure(
        self, change_ids: list[str], failure: dict[str, Any]
    ) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        for change_id in change_ids:
            item = {**failure, "change_id": change_id}
            errors.append(item)
            if item["retryable"]:
                self._outbox.defer_outbox_id(change_id, item)
            else:
                self._outbox.block_outbox_id(
                    change_id,
                    item,
                    failure_kind=str(item["failure_kind"]),
                )
        return errors

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
        sent_ids = [
            str(c.get("change_id") or "") for c in changes if c.get("change_id")
        ]
        try:
            resp = self._push_once(project_id, changes)
        except Exception as exc:  # noqa: BLE001
            failure = self._request_failure(exc, phase="push")
            return 0, [], self._record_request_failure(sent_ids, failure)
        if not isinstance(resp, dict):
            failure = {
                "status": "error",
                "reason": "push_invalid_response",
                "detail": "Server returned an invalid synchronization response",
                "http_status": 0,
                "failure_kind": "transient",
                "retryable": True,
                "request_failed": True,
            }
            return 0, [], self._record_request_failure(sent_ids, failure)

        raw_results = resp.get("results")
        canonical_results = (
            [
                item
                for item in raw_results
                if isinstance(item, dict)
                and item.get("change_id")
                and item.get("status") in {"accepted", "conflict", "error"}
            ]
            if isinstance(raw_results, list)
            else []
        )
        if canonical_results:
            conflicts = [
                item for item in canonical_results if item["status"] == "conflict"
            ]
            errors = [
                self._normalize_error(item)
                for item in canonical_results
                if item["status"] == "error"
            ]
            processed = {
                str(item["change_id"])
                for item in canonical_results
                if item["status"] == "accepted"
            }
        else:
            # Compatibility with servers predating per-change receipt results.
            conflicts = list(resp.get("conflicts") or [])
            errors = [
                self._normalize_error(item)
                for item in list(resp.get("errors") or [])
                if isinstance(item, dict)
            ]
            dup_ids = [
                str(x) for x in (resp.get("duplicate_change_ids") or []) if x
            ]
            conflict_ids = set(self._extract_change_ids(conflicts))
            error_ids = set(self._extract_change_ids(errors))
            processed = (set(sent_ids) - conflict_ids - error_ids) | set(dup_ids)

        if processed:
            self._outbox.delete_outbox_ids(list(processed))

        for c in conflicts:
            cid = str(c.get("change_id") or "")
            if cid:
                self._outbox.block_outbox_id(
                    cid, c, failure_kind="conflict"
                )
        for e in errors:
            cid = str(e.get("change_id") or "")
            if cid:
                if bool(e.get("retryable")):
                    self._outbox.defer_outbox_id(cid, e)
                else:
                    self._outbox.block_outbox_id(
                        cid,
                        e,
                        failure_kind=str(e.get("failure_kind") or "error"),
                    )

        return (len(processed), conflicts, errors)

    def sync_project(self, project_id: str) -> dict[str, Any]:
        if not self._remote:
            raise RuntimeError(
                "No server configured (start the app online at least once)."
            )

        effective_project_id = project_id

        summary: dict[str, Any] = {
            "state": "complete",
            "pushed": 0,
            "conflicts": 0,
            "errors": 0,
            "deferred": 0,
            "blocked": 0,
            "blocked_details": [],
            "next_retry_at": None,
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
            deferred_errors = [e for e in errors if bool(e.get("retryable"))]
            blocked_errors = [e for e in errors if not bool(e.get("retryable"))]
            summary["deferred"] += len(self._extract_change_ids(deferred_errors))
            summary["errors"] += len(self._extract_change_ids(blocked_errors))

            request_failures = [e for e in errors if e.get("request_failed")]
            if request_failures:
                failure = request_failures[0]
                summary["state"] = self._state_for_failure_kind(
                    str(failure.get("failure_kind") or "error")
                )
                summary["sync_error"] = failure
                return self._finish_summary(summary, effective_project_id)

        since = self._store.get_last_server_time(effective_project_id)

        try:
            pull = self._remote.sync_pull(effective_project_id, since)
        except Exception as exc:  # noqa: BLE001
            status = getattr(exc, "status", None)
            if int(status or 0) == 413:
                try:
                    pull = self._pull_paginated(effective_project_id, since)
                except Exception as paginated_exc:  # noqa: BLE001
                    failure = self._request_failure(
                        paginated_exc, phase="pull"
                    )
                    summary["state"] = self._state_for_failure_kind(
                        str(failure["failure_kind"])
                    )
                    summary["sync_error"] = failure
                    return self._finish_summary(summary, effective_project_id)
            else:
                failure = self._request_failure(exc, phase="pull")
                summary["state"] = self._state_for_failure_kind(
                    str(failure["failure_kind"])
                )
                summary["sync_error"] = failure
                return self._finish_summary(summary, effective_project_id)

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
        return self._finish_summary(summary, effective_project_id)

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

        with self._store.write_transaction():
            self._store.conn.execute(
                "UPDATE projects SET name = ? WHERE id = ?;",
                (name, local_project_id),
            )
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
