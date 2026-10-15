"""Push the outbox, pull server changes and resolve conflicts for one project."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, NamedTuple

from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore, utc_iso
from riskapp_client.adapters.local_storage.sync_outbox_queue import OutboxStore
from riskapp_client.domain.domain_models import unique_project_name
from riskapp_client.domain.sync_protocol import (
    FailureKind,
    SyncState,
    acknowledged_version,
    classify_http_status,
    strict_int,
    sync_state_for_failure,
)
from riskapp_client.services.conflict_merge import merged_record

_SYNC_EPOCH = "1970-01-01T00:00:00"
_CONFLICT_RESOLUTIONS = {"keep_mine", "use_server", "later", "merge"}
_NO_SERVER = "No server configured (start the app online at least once)."
_PULL_KEYS = ("risks", "opportunities", "actions", "assessments", "helpdesk_tickets")
# Receipts stored by older servers may carry only a reason.
_FAILURE_KIND_BY_REASON = {
    "insufficient_permissions": FailureKind.PERMISSION,
    "internal_error": FailureKind.TRANSIENT,
}
_SERVER_VERSION_UNAVAILABLE = (
    "The current server version is unavailable; leave this conflict blocked for later."
)


class _SyncCancelled(RuntimeError):
    """Internal cooperative-cancellation signal."""


class _SyncFailed(Exception):
    """A push or pull request failed as a whole and ends this synchronization."""

    def __init__(self, failure: dict[str, Any]) -> None:
        super().__init__(failure.get("detail"))
        self.failure = failure


class PushOutcome(NamedTuple):
    """What one push request did to the outbox, for the run summary."""

    pushed: int
    conflicts: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    acknowledged: list[dict[str, Any]]


def _request_failure(reason: str, detail: str, http_status: int) -> dict[str, Any]:
    """Describe a push or pull request that failed as a whole."""
    failure_kind, retryable = classify_http_status(http_status)
    return {
        "status": "error",
        "reason": reason,
        "detail": detail,
        "http_status": http_status,
        "failure_kind": failure_kind,
        "retryable": retryable,
        "request_failed": True,
    }


def _failure_from_exception(exc: Exception, *, phase: str) -> dict[str, Any]:
    """Classify a transport failure; re-raise anything without an HTTP status."""
    status = getattr(exc, "status", None)
    if status is None:
        raise exc
    detail = str(getattr(exc, "detail", None) or exc)
    return _request_failure(f"{phase}_request_failed", detail, int(status or 0))


def _normalize_error(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    reason = str(normalized.get("reason") or "")
    failure_kind = str(normalized.get("failure_kind") or "")
    failure_kind = failure_kind or _FAILURE_KIND_BY_REASON.get(
        reason, FailureKind.VALIDATION
    )
    normalized["failure_kind"] = failure_kind
    normalized["retryable"] = bool(
        normalized.get("retryable") or failure_kind == FailureKind.TRANSIENT
    )
    return normalized


def _has_server_state(result: dict[str, Any]) -> bool:
    return (
        isinstance(result.get("server_record"), dict)
        or strict_int(result.get("server_version")) is not None
    )


def _result_matches_change(
    result: dict[str, Any], change: dict[str, Any], project_id: str
) -> bool:
    """A result may omit identity fields but must not contradict its change."""
    if result.get("status") not in ("accepted", "conflict", "error"):
        return False
    if change.get("entity") and result.get("entity") not in (None, change["entity"]):
        return False
    record = change.get("record")
    entity_id = record.get("id") if isinstance(record, dict) else None
    if entity_id and result.get("entity_id") not in (None, entity_id):
        return False
    server_record = result.get("server_record")
    return not isinstance(server_record, dict) or (
        (not entity_id or server_record.get("id") in (None, entity_id))
        and server_record.get("project_id") in (None, project_id)
    )


def _validated_push_results(
    project_id: str,
    changes: list[dict[str, Any]],
    response: object,
) -> list[dict[str, Any]] | None:
    """Validate the entire response before acknowledging any local work."""
    raw_results = response.get("results") if isinstance(response, dict) else None
    if not isinstance(raw_results, list) or not raw_results:
        return None
    sent = {str(c["change_id"]): c for c in changes if c.get("change_id")}
    seen: set[str] = set()
    for result in raw_results:
        change_id = result.get("change_id") if isinstance(result, dict) else None
        if (
            not isinstance(change_id, str)
            or change_id not in sent
            or change_id in seen
            or not _result_matches_change(result, sent[change_id], project_id)
        ):
            return None
        seen.add(change_id)
    return list(raw_results) if seen == set(sent) else None


def _acknowledged_versions(
    changes: list[dict[str, Any]], accepted: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Pair each accepted change's base version with the version it produced.

    Open editors use this to follow their own saves.
    """
    sent = {str(change.get("change_id") or ""): change for change in changes}
    acknowledged: list[dict[str, Any]] = []
    for item in accepted:
        version = acknowledged_version(item)
        if version is None:
            continue
        change = sent.get(str(item["change_id"]), {})
        record = change.get("record")
        record_id = record.get("id") if isinstance(record, dict) else None
        acknowledged.append(
            {
                "entity": str(item.get("entity") or change.get("entity") or ""),
                "entity_id": str(item.get("entity_id") or record_id or ""),
                "base_version": change.get("base_version"),
                "server_version": version,
            }
        )
    return acknowledged


def _empty_summary() -> dict[str, Any]:
    return {
        "state": SyncState.COMPLETE,
        "pushed": 0,
        "conflicts": 0,
        "errors": 0,
        "deferred": 0,
        "blocked": 0,
        "blocked_details": [],
        "next_retry_at": None,
        **{f"pulled_{key}": 0 for key in _PULL_KEYS},
    }


def _resolution(
    change_id: str,
    choice: str,
    conflict: dict[str, Any],
    *,
    resolved: bool = True,
    **details: Any,
) -> dict[str, Any]:
    return {
        "change_id": change_id,
        "resolution": choice,
        "resolved": resolved,
        "project_id": str(conflict["project_id"]),
        **details,
    }


def _require_unchanged_server_copy(conflict: dict[str, Any], expected: int) -> None:
    current = conflict.get("server_version")
    if isinstance(expected, bool) or strict_int(current) is None or current != expected:
        raise RuntimeError(
            "The server copy changed while the Conflict Center was "
            "open. Reopen it and review the latest values."
        )


def _saved_server_version(conflict: dict[str, Any]) -> int:
    raw = conflict.get("server_version")
    if raw is None:
        raise RuntimeError(_SERVER_VERSION_UNAVAILABLE)
    try:
        version = int(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(_SERVER_VERSION_UNAVAILABLE) from exc
    if version < 1:
        raise RuntimeError("The current server version is invalid")
    return version


class SyncService:
    def __init__(
        self,
        store: LocalStore,
        outbox: OutboxStore,
        remote: Any | None,
        *,
        release_authentication_blocks: bool = True,
    ) -> None:
        self._store = store
        self._outbox = outbox
        self._remote = remote
        if remote is not None and release_authentication_blocks:
            # A newly constructed online backend represents a fresh authenticated
            # session, so changes blocked by the previous session may try again.
            self._outbox.release_authentication_blocks()

    def can_sync(self) -> bool:
        return self._remote is not None

    def _require_remote(self) -> Any:
        if not self._remote:
            raise RuntimeError(_NO_SERVER)
        return self._remote

    @staticmethod
    def _notify_progress(
        progress: Callable[[str], None] | None,
        message: str,
    ) -> None:
        if progress is None:
            return
        try:
            progress(message)
        # UI callbacks are external to the sync operation and must not abort it.
        except Exception:  # pylint: disable=W0718
            logging.getLogger(__name__).debug(
                "Synchronization progress callback failed",
                exc_info=True,
            )

    @staticmethod
    def _check_cancel(should_cancel: Callable[[], bool] | None) -> None:
        if should_cancel is not None and should_cancel():
            raise _SyncCancelled

    @staticmethod
    def _validated_server_sequence(response: dict[str, Any]) -> int:
        raw = response.get("server_sequence")
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise RuntimeError("Synchronization returned an invalid server_sequence")
        return raw

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
            if item.get("failure_kind") == FailureKind.CONFLICT
        ]

    # ---- Conflict resolution ----

    def _require_conflict(self, change_id: str) -> dict[str, Any]:
        conflict = self._outbox.get_blocked_change(str(change_id))
        if conflict is None:
            raise KeyError("Synchronization conflict no longer exists")
        if conflict.get("failure_kind") != FailureKind.CONFLICT:
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

    def _normalize_server_record(self, conflict: dict[str, Any]) -> dict[str, Any]:
        raw = conflict.get("server_record")
        if not isinstance(raw, dict) or not raw:
            raise RuntimeError(
                "The server copy is unavailable for this conflict; choose "
                "Keep mine or leave it for later."
            )
        record = dict(raw)
        entity = str(conflict["entity"])
        project_id = str(conflict["project_id"])
        if str(record.get("id") or "") != str(conflict["entity_id"]):
            raise RuntimeError("The saved server copy does not match this item")
        record_project_id = record.get("project_id")
        if record_project_id and str(record_project_id) != project_id:
            raise RuntimeError("The saved server copy belongs to another project")
        record["project_id"] = project_id

        if entity in {"risk", "opportunity"} and str(record.get("type") or entity) != (
            entity
        ):
            raise RuntimeError(
                "This conflict changes the entity type and cannot be "
                "resolved automatically."
            )
        if entity in {"action", "assessment"}:
            self._resolve_legacy_parent(record, project_id)
        return record

    def _resolve_legacy_parent(self, record: dict[str, Any], project_id: str) -> None:
        """Older stored conflict payloads assigned item_id to both aliases.

        Resolve an ambiguous parent from the authoritative local parent rows.
        """
        item_id = str(record.get("item_id") or "")
        risk_id = str(record.get("risk_id") or "")
        opportunity_id = str(record.get("opportunity_id") or "")
        if not item_id:
            item_id = risk_id or opportunity_id
            record["item_id"] = item_id
        if not item_id or bool(risk_id) != bool(opportunity_id):
            return
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
        self,
        change_id: str,
        resolution: str,
        choices: dict[str, str] | None = None,
        *,
        expected_server_version: int | None = None,
    ) -> dict[str, Any]:
        """Resolve one persisted conflict without silently discarding either side."""
        choice = str(resolution or "").strip().lower()
        if choice not in _CONFLICT_RESOLUTIONS:
            raise ValueError(
                "resolution must be one of: keep_mine, use_server, later, merge"
            )
        change_id = str(change_id)
        if choice == "later":
            conflict = self._require_conflict(change_id)
            return _resolution(change_id, choice, conflict, resolved=False)

        with self._store.write_transaction():
            conflict = self._require_conflict(change_id)
            if expected_server_version is not None:
                _require_unchanged_server_copy(conflict, expected_server_version)
            if choice == "keep_mine":
                return self._keep_mine(change_id, conflict)
            server_record = self._normalize_server_record(conflict)
            if choice == "merge":
                return self._merge(change_id, conflict, server_record, choices or {})
            return self._use_server(change_id, conflict, server_record)

    def _keep_mine(self, change_id: str, conflict: dict[str, Any]) -> dict[str, Any]:
        """Requeue the local copy on the newest version either side has seen."""
        target_version = max(
            _saved_server_version(conflict), self._current_local_version(conflict)
        )
        replacement_id = self._outbox.requeue_conflict_with_new_id(
            change_id, target_version
        )
        if not replacement_id:
            raise RuntimeError("The conflict disappeared before it was resolved")
        return _resolution(
            change_id,
            "keep_mine",
            conflict,
            replacement_change_id=replacement_id,
            base_version=target_version,
        )

    def _take_server_copy(
        self, change_id: str, conflict: dict[str, Any], server_record: dict[str, Any]
    ) -> None:
        self._outbox.delete_outbox_ids([change_id])
        self._apply_server_record(conflict, server_record)

    def _merge(
        self,
        change_id: str,
        conflict: dict[str, Any],
        server_record: dict[str, Any],
        choices: dict[str, str],
    ) -> dict[str, Any]:
        """Start from the server copy and requeue only the fields the user kept."""
        version = strict_int(conflict.get("server_version"))
        if (
            version is None
            or version < 1
            or int(server_record.get("version") or 0) != version
            or self._current_local_version(conflict) > version
        ):
            raise RuntimeError(
                "The saved server copy is stale; synchronize again before merging"
            )
        record, selected = merged_record(
            {**conflict, "server_record": server_record}, choices
        )
        project_id = str(conflict["project_id"])
        entity = str(conflict["entity"])
        entity_id = str(conflict["entity_id"])
        self._take_server_copy(change_id, conflict, server_record)
        self._store.apply_merged_fields(entity, project_id, entity_id, record)
        replacement_id = self._outbox.queue_merged_upsert(
            project_id, entity, entity_id, version, record
        )
        self._store.reset_sync_watermark(project_id, _SYNC_EPOCH)
        return _resolution(
            change_id,
            "merge",
            conflict,
            replacement_change_id=replacement_id,
            base_version=version,
            local_fields=sorted(selected),
        )

    def _use_server(
        self, change_id: str, conflict: dict[str, Any], server_record: dict[str, Any]
    ) -> dict[str, Any]:
        self._take_server_copy(change_id, conflict, server_record)
        # The saved conflict record is a point-in-time copy. Rewind the
        # watermark so the next sync cannot miss a newer server update.
        self._store.reset_sync_watermark(str(conflict["project_id"]), _SYNC_EPOCH)
        return _resolution(change_id, "use_server", conflict)

    # ---- Push ----

    def _push_once(self, project_id: str, changes: list[dict[str, Any]]) -> object:
        return self._require_remote().sync_push(project_id, changes)

    def _park_failure(self, error: dict[str, Any]) -> None:
        """Schedule a retry for a transient failure; block anything else."""
        change_id = str(error["change_id"])
        if error["retryable"]:
            self._outbox.defer_outbox_id(change_id, error)
        else:
            self._outbox.block_outbox_id(
                change_id, error, failure_kind=str(error["failure_kind"])
            )

    def _fail_batch(
        self, change_ids: list[str], failure: dict[str, Any]
    ) -> PushOutcome:
        errors = [{**failure, "change_id": change_id} for change_id in change_ids]
        for error in errors:
            self._park_failure(error)
        return PushOutcome(0, [], errors, [])

    def _acknowledge(self, project_id: str, accepted: list[dict[str, Any]]) -> None:
        with_state = [item for item in accepted if _has_server_state(item)]
        if with_state:
            self._outbox.acknowledge_accepted_results(project_id, with_state)
        # An accepted result without server state, such as a replay whose
        # record no longer exists, only needs its outbox entry removed.
        stateless = [i["change_id"] for i in accepted if not _has_server_state(i)]
        if stateless:
            self._outbox.delete_outbox_ids(stateless)

    def _process_push(
        self, project_id: str, changes: list[dict[str, Any]]
    ) -> PushOutcome:
        sent_ids = [str(c["change_id"]) for c in changes if c.get("change_id")]
        # Commit the send boundary before network I/O. A create deleted or
        # edited while the request is in flight must assume version one may now
        # exist on the server, even if the response never reaches this process.
        self._outbox.mark_outbox_ids_attempted(sent_ids)
        try:
            response = self._push_once(project_id, changes)
        # Remote adapters expose different transport exception classes; the
        # shared failure normalizer re-raises exceptions it cannot classify.
        except Exception as exc:  # pylint: disable=W0718
            return self._fail_batch(
                sent_ids, _failure_from_exception(exc, phase="push")
            )
        results = _validated_push_results(project_id, changes, response)

        if not results:
            return self._fail_batch(
                sent_ids,
                _request_failure(
                    "push_invalid_response",
                    "Server returned an invalid synchronization response",
                    0,
                ),
            )
        accepted = [item for item in results if item["status"] == "accepted"]
        conflicts = [item for item in results if item["status"] == "conflict"]
        errors = [
            _normalize_error(item) for item in results if item["status"] == "error"
        ]
        self._acknowledge(project_id, accepted)
        for conflict in conflicts:
            self._outbox.block_outbox_id(
                conflict["change_id"], conflict, failure_kind=FailureKind.CONFLICT
            )
        for error in errors:
            self._park_failure(error)
        return PushOutcome(
            len(accepted), conflicts, errors, _acknowledged_versions(changes, accepted)
        )

    # ---- Synchronization run ----

    def sync_project(
        self,
        project_id: str,
        *,
        should_cancel: Callable[[], bool] | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """Push one batch of local changes, then pull and apply server changes."""
        self._require_remote()
        summary = _empty_summary()
        try:
            self._notify_progress(progress, "Preparing synchronization")
            self._check_cancel(should_cancel)

            if str(project_id).startswith("local-"):
                project_id = self._publish_local_project(project_id, summary, progress)
                self._check_cancel(should_cancel)

            changes = self._outbox.get_pending_changes(project_id, limit=100)
            if changes:
                self._push(project_id, changes, summary, progress)
                self._check_cancel(should_cancel)
            pull = self._download(project_id, should_cancel, progress)
            self._apply_pull(project_id, pull, summary, should_cancel, progress)
        except _SyncCancelled:
            summary.update(state=SyncState.CANCELLED, cancelled=True)
        except _SyncFailed as failed:
            summary.update(
                state=sync_state_for_failure(str(failed.failure["failure_kind"])),
                sync_error=failed.failure,
            )
        return self._finish_summary(summary, project_id)

    def _publish_local_project(
        self,
        project_id: str,
        summary: dict[str, Any],
        progress: Callable[[str], None] | None,
    ) -> str:
        self._notify_progress(progress, "Publishing local project")
        promoted = self._promote_local_project(project_id)
        if not promoted or promoted == project_id:
            return project_id
        summary["project_id_migrated_from"] = project_id
        summary["project_id_migrated_to"] = promoted
        return promoted

    def _push(
        self,
        project_id: str,
        changes: list[dict[str, Any]],
        summary: dict[str, Any],
        progress: Callable[[str], None] | None,
    ) -> None:
        """Push one batch and count it; a failed request ends the sync."""
        self._notify_progress(progress, f"Pushing {len(changes)} pending change(s)")
        outcome = self._process_push(project_id, changes)
        if outcome.acknowledged:
            summary["acknowledged"] = outcome.acknowledged
        deferred = sum(1 for error in outcome.errors if error["retryable"])
        summary["pushed"] += outcome.pushed
        summary["conflicts"] += len(outcome.conflicts)
        summary["deferred"] += deferred
        summary["errors"] += len(outcome.errors) - deferred
        for error in outcome.errors:
            if error.get("request_failed"):
                raise _SyncFailed(error)

    def _download(
        self,
        project_id: str,
        should_cancel: Callable[[], bool] | None,
        progress: Callable[[str], None] | None,
    ) -> dict[str, Any]:
        since_sequence = self._store.get_last_server_sequence(project_id)
        self._notify_progress(progress, "Pulling server changes")
        self._check_cancel(should_cancel)
        try:
            return self._fetch_pull(project_id, since_sequence, should_cancel, progress)
        except _SyncCancelled:
            raise
        # Adapters share a status-based failure contract; anything without a
        # status is re-raised by _failure_from_exception.
        except Exception as exc:  # pylint: disable=W0718
            raise _SyncFailed(_failure_from_exception(exc, phase="pull")) from exc

    def _fetch_pull(
        self,
        project_id: str,
        since_sequence: int,
        should_cancel: Callable[[], bool] | None,
        progress: Callable[[str], None] | None,
    ) -> dict[str, Any]:
        """Pull in one request, or in pages when the server answers 413."""

        try:
            pull = self._require_remote().sync_pull(
                project_id, since_sequence=since_sequence
            )
        except Exception as exc:  # pylint: disable=W0718
            if int(getattr(exc, "status", None) or 0) != 413:
                raise
            return self._pull_paginated(
                project_id,
                since_sequence,
                should_cancel=should_cancel,
                progress=progress,
            )
        self._check_cancel(should_cancel)
        return pull

    def _apply_pull(
        self,
        project_id: str,
        pull: dict[str, Any],
        summary: dict[str, Any],
        should_cancel: Callable[[], bool] | None,
        progress: Callable[[str], None] | None,
    ) -> None:
        server_time = str(pull.get("server_time") or utc_iso())
        server_sequence = self._validated_server_sequence(pull)
        # The pending check, every pulled row, and the watermark share one
        # BEGIN IMMEDIATE transaction. A UI edit either commits before this
        # block and is preserved, or waits and bases itself on the new row.
        with self._store.write_transaction():
            # Apply parents before children so an assessment containing only
            # item_id can still be classified as risk vs opportunity.
            for key in ("risks", "opportunities", "actions", "assessments"):
                self._check_cancel(should_cancel)
                items = pull.get(key) or []
                self._notify_progress(progress, f"Applying {len(items)} {key}")
                getattr(self._store, f"apply_pull_{key}")(project_id, items)
                summary[f"pulled_{key}"] = len(items)
            self._check_cancel(should_cancel)
            tickets = pull.get("helpdesk_tickets") or []
            if tickets:
                self._notify_progress(
                    progress, f"Applying {len(tickets)} help-desk ticket(s)"
                )
                self._store.apply_pull_helpdesk_tickets(project_id, tickets)
            summary["pulled_helpdesk_tickets"] = len(tickets)

            self._check_cancel(should_cancel)
            self._notify_progress(progress, "Finalizing synchronization")
            self._store.set_sync_watermark(project_id, server_time, server_sequence)

    def _finish_summary(
        self, summary: dict[str, Any], project_id: str
    ) -> dict[str, Any]:
        summary["blocked_details"] = self.blocked_details(project_id)
        summary["blocked"] = len(summary["blocked_details"])
        summary["next_retry_at"] = self.next_retry_at(project_id)
        if summary.get("state") == SyncState.COMPLETE and summary["blocked"]:
            summary["state"] = SyncState.ATTENTION_REQUIRED
        elif summary.get("state") == SyncState.COMPLETE and summary.get("deferred"):
            summary["state"] = SyncState.RETRY_WAIT
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
            name = unique_project_name(name, {ep.name for ep in existing})
        except AttributeError, RuntimeError:
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

    def _pull_paginated(
        self,
        project_id: str,
        since_sequence: int = 0,
        *,
        should_cancel: Callable[[], bool] | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        remote = self._require_remote()
        limit = 2000
        cursors: dict[str, str] = {}
        snapshot_sequence: int | None = None
        merged: dict[str, Any] = {
            "server_time": None,
            "server_sequence": None,
            **{key: [] for key in _PULL_KEYS},
        }

        page_number = 0
        while True:
            self._check_cancel(should_cancel)
            page_number += 1
            self._notify_progress(
                progress,
                f"Downloading synchronization page {page_number}",
            )
            resp = remote.sync_pull(
                project_id,
                since_sequence=since_sequence,
                limit_per_entity=limit,
                cursors=cursors or None,
                snapshot_sequence=snapshot_sequence,
            )
            self._check_cancel(should_cancel)
            page_sequence = self._validated_server_sequence(resp)
            if snapshot_sequence is None:
                # The first page fixes the snapshot every later page must match.
                snapshot_sequence = page_sequence
                merged["server_sequence"] = page_sequence
                merged["server_time"] = resp.get("server_time")
            elif page_sequence != snapshot_sequence:
                raise RuntimeError(
                    "Sync pagination sequence snapshot changed between pages"
                )
            for key in _PULL_KEYS:
                merged[key].extend(list(resp.get(key) or []))
            next_cursors = _next_page_cursors(resp, cursors)
            if next_cursors is None:
                break
            cursors = next_cursors

        return merged


def _next_page_cursors(
    resp: dict[str, Any], cursors: dict[str, str]
) -> dict[str, str] | None:
    """Return the cursors for the next page, or None after the last page."""
    has_more = resp.get("has_more") or {}
    next_cursors = resp.get("cursors") or {}
    if not isinstance(has_more, dict) or not isinstance(next_cursors, dict):
        raise RuntimeError("Invalid sync pagination metadata")
    more_keys = [key for key, more in has_more.items() if bool(more)]
    if not more_keys:
        return None
    stalled = [
        str(key)
        for key in more_keys
        if not next_cursors.get(key) or next_cursors.get(key) == cursors.get(key)
    ]
    if stalled:
        raise RuntimeError("Sync pagination did not advance for: " + ", ".join(stalled))
    return {str(key): str(value) for key, value in next_cursors.items() if value}
