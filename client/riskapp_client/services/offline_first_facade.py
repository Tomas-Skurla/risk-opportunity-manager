"""Offline-first backend: work on the local copy, send changes through the outbox."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from typing import Any

from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore
from riskapp_client.adapters.local_storage.sync_outbox_queue import OutboxStore
from riskapp_client.adapters.remote_api.rest_api_client import ApiError
from riskapp_client.domain.background_job_contracts import BackgroundJobBackend
from riskapp_client.domain.domain_models import (
    Action,
    Assessment,
    Backend,
    HelpDeskTicket,
    Member,
    Opportunity,
    Project,
    Risk,
    unique_project_name,
)
from riskapp_client.domain.sync_protocol import classify_http_status
from riskapp_client.services.action_management_service import ActionService
from riskapp_client.services.assessment_management_service import AssessmentService
from riskapp_client.services.entity_filters import (
    criteria_from_report_filters,
    filter_scored,
)
from riskapp_client.services.helpdesk_service import HelpDeskService
from riskapp_client.services.member_management_service import MembersService
from riskapp_client.services.scored_entity_management_service import (
    ScoredEntityService,
    ScoredEntityWiring,
)
from riskapp_client.services.synchronization_service import SyncService

logger = logging.getLogger(__name__)
# Upper bound of each score bucket in a report; the last one is open-ended.
_SCORE_BUCKETS = (("0-4", 4), ("5-9", 9), ("10-14", 14), ("15-19", 19), ("20-25", None))


def _optional_callable(
    owner: object | None,
    name: str,
) -> Callable[..., Any] | None:
    """Return a dynamically supported method only when it is callable."""
    candidate = getattr(owner, name, None)
    if not callable(candidate):
        return None
    return candidate


def _is_anonymous_local(project: Project) -> bool:
    """A local project created without an account; it can never be synced."""
    return str(project.id).startswith("local-") and not project.created_by


def _score_bucket(score: int) -> str:
    return next(
        label for label, upper in _SCORE_BUCKETS if upper is None or score <= upper
    )


def _local_scored_report(
    items: list[Risk] | list[Opportunity], filters: dict[str, Any]
) -> dict[str, Any]:
    """The server's report summary, computed from the local copy."""
    filtered = filter_scored(items, criteria_from_report_filters(filters))
    scores = [int(x.score or 0) for x in filtered]
    buckets = dict.fromkeys((label for label, _ in _SCORE_BUCKETS), 0)
    for score in scores:
        buckets[_score_bucket(score)] += 1
    return {
        "total": len(filtered),
        "project_total": len(items),
        "min_score": min(scores, default=None),
        "max_score": max(scores, default=None),
        "avg_score": sum(scores) / len(scores) if scores else None,
        "status_counts": dict(Counter(x.status or "concept" for x in filtered)),
        "category_counts": dict(Counter(x.category or "(none)" for x in filtered)),
        "owner_counts": dict(Counter(x.owner_user_id or "(none)" for x in filtered)),
        "score_buckets": buckets,
    }


class OfflineFirstBackend(Backend):
    """Backend implementation used by the Qt UI in offline-first mode."""

    def __init__(
        self,
        store: LocalStore,
        remote: Any | None = None,
        *,
        anonymous_offline: bool = False,
        remote_factory: Callable[[], Any] | None = None,
        release_authentication_blocks: bool = True,
    ) -> None:
        self.store = store
        self.remote = remote
        self._remote_factory = remote_factory
        self.anonymous_offline = anonymous_offline
        self.outbox = OutboxStore(store)
        self._risks = ScoredEntityService(
            ScoredEntityWiring(
                kind="risk",
                id_kw="risk_id",
                model_cls=Risk,
                list_fn=store.list_risks,
                get_project_and_version_fn=store.get_risk_project_and_version,
                get_row_fn=store.get_risk_row,
                upsert_local_fn=store.upsert_local_risk,
                queue_upsert_fn=self.outbox.queue_risk_upsert,
                queue_delete_fn=self.outbox.queue_risk_delete,
                discard_pending_changes_fn=self._discard_changes_of("risk"),
                soft_delete_local_fn=store.soft_delete_risk,
                write_transaction_fn=store.write_transaction,
                next_code_fn=store.next_risk_code,
                remote_create_may_exist_fn=self._remote_create_check_of("risk"),
            )
        )
        self._opps = ScoredEntityService(
            ScoredEntityWiring(
                kind="opportunity",
                id_kw="opportunity_id",
                model_cls=Opportunity,
                list_fn=store.list_opportunities,
                get_project_and_version_fn=store.get_opportunity_project_and_version,
                get_row_fn=store.get_opportunity_row,
                upsert_local_fn=store.upsert_local_opportunity,
                queue_upsert_fn=self.outbox.queue_opportunity_upsert,
                queue_delete_fn=self.outbox.queue_opportunity_delete,
                discard_pending_changes_fn=self._discard_changes_of("opportunity"),
                soft_delete_local_fn=store.soft_delete_opportunity,
                write_transaction_fn=store.write_transaction,
                next_code_fn=store.next_opportunity_code,
                remote_create_may_exist_fn=self._remote_create_check_of("opportunity"),
            )
        )
        self._actions = ActionService(store, self.outbox)
        self._assessments = AssessmentService(store, self.outbox)
        self._helpdesk = HelpDeskService(store, self.outbox)
        self._members = MembersService(remote)
        self._sync = SyncService(
            store,
            self.outbox,
            remote,
            release_authentication_blocks=release_authentication_blocks,
        )

    def create_background_backend(self) -> BackgroundJobBackend:
        """Build a worker-owned facade with its own SQLite connection."""
        remote = self.remote
        release_authentication_blocks = False
        fork_remote = _optional_callable(remote, "fork_authenticated")
        if fork_remote is not None:
            remote = fork_remote()
        elif remote is None and self._remote_factory is not None:
            # Connection recovery belongs in the worker thread. The factory is
            # retained only while an offline authenticated session is waiting
            # for its first successful reconnect.
            remote = self._remote_factory()
            release_authentication_blocks = True
        return OfflineFirstBackend(
            LocalStore(self.store.db_path),
            remote=remote,
            anonymous_offline=self.anonymous_offline,
            remote_factory=self._remote_factory,
            release_authentication_blocks=release_authentication_blocks,
        )

    def can_auto_sync(self) -> bool:
        """Return whether a worker can use or recover an authenticated session."""
        return self.remote is not None or self._remote_factory is not None

    def export_authenticated_remote(self) -> Any | None:
        """Return a thread-local authenticated client for the GUI facade."""
        fork_remote = _optional_callable(self.remote, "fork_authenticated")
        return fork_remote() if fork_remote is not None else self.remote

    def adopt_authenticated_remote(self, remote: Any) -> None:
        """Promote a successfully recovered worker session to the GUI facade."""
        if remote is None:
            raise ValueError("authenticated remote is required")
        self.remote = remote
        self._remote_factory = None
        self._members = MembersService(remote)
        self._sync = SyncService(self.store, self.outbox, remote)

    def _remote_for_project(self, project_id: str | None = None) -> Any | None:
        remote = self.remote
        if not remote:
            return None
        if project_id and str(project_id).startswith("local-"):
            return None
        return remote

    def _use_remote(self, project_id: str | None = None) -> bool:
        return self._remote_for_project(project_id) is not None

    def _discard_changes_of(self, entity: str) -> Callable[[str, str], None]:
        """Drop one entity's queued changes, called as (project_id, entity_id)."""

        def discard(project_id: str, entity_id: str) -> None:
            self.outbox.discard_entity_changes(
                project_id, entity=entity, entity_id=entity_id
            )

        return discard

    def _remote_create_check_of(self, entity: str) -> Callable[[str, str], bool]:
        """Ask whether an unacknowledged create may already exist on the server."""

        def may_exist(project_id: str, entity_id: str) -> bool:
            return self.outbox.remote_create_may_exist(
                project_id, entity=entity, entity_id=entity_id
            )

        return may_exist

    def list_sync_projects(self) -> list[Project]:
        """Refresh the authoritative project list without offline fallback."""
        if self.remote is None:
            raise RuntimeError("No authenticated server session is available.")
        remote_projects = list(self.remote.list_projects() or [])
        self.store.sync_projects(remote_projects)
        return self._with_syncable_local_projects(remote_projects)

    def list_projects(self) -> list[Project]:
        remote_projects = self._fetch_remote_projects()
        if remote_projects is not None:
            self.store.sync_projects(remote_projects)
            if not self.anonymous_offline:
                # Online, only /projects decides what the sidebar shows: the
                # cache keeps projects with local data after access is revoked.
                return self._with_syncable_local_projects(remote_projects)
        cached = self._visible_cached_projects()
        if cached or self.remote:
            return cached
        return [self._bootstrap_local_project()]

    def _fetch_remote_projects(self) -> list[Project] | None:
        """The server's project list, or None when the cache must be used."""
        if not self.remote:
            return None
        try:
            return list(self.remote.list_projects())
        except (ApiError, OSError) as exc:
            # Use the cache unless the request itself was invalid: an expired
            # session or revoked access must not hide local work.
            if (
                isinstance(exc, ApiError)
                and classify_http_status(exc.status)[0] == "validation"
            ):
                raise
            logger.warning(
                "Remote project list unavailable; using local cache: %s", exc
            )
            return None

    def _visible_cached_projects(self) -> list[Project]:
        """Anonymous sessions see only anonymous projects; accounts see the rest."""
        return [
            p
            for p in self.store.list_projects()
            if _is_anonymous_local(p) == bool(self.anonymous_offline)
        ]

    def _with_syncable_local_projects(
        self, remote_projects: list[Project]
    ) -> list[Project]:
        """Server projects plus local ones that will sync once published."""
        local = [
            p
            for p in self.store.list_projects()
            if str(p.id).startswith("local-") and p.created_by
        ]
        return list({str(p.id): p for p in [*remote_projects, *local]}.values())

    def _bootstrap_local_project(self) -> Project:
        """Reuse or create the project an offline-only session starts with."""
        meta_key = (
            "bootstrap_anon_project_id"
            if self.anonymous_offline
            else "bootstrap_user_project_id"
        )
        bootstrap_id = self.store.get_meta(meta_key)
        existing = self.store.get_project(str(bootstrap_id)) if bootstrap_id else None
        if existing:
            return existing
        project = self.store.create_local_project(
            name="Local Project",
            description="Offline project",
            created_by="" if self.anonymous_offline else None,
        )
        self.store.set_meta(meta_key, project.id)
        return project

    def create_project(self, *, name: str, description: str = "") -> Project:
        if self.remote:
            try:
                existing_names = {p.name for p in (self.remote.list_projects() or [])}
                name = unique_project_name(name, existing_names)
            except AttributeError, KeyError:
                logger.debug("Duplicate project name check failed", exc_info=True)
            project = self.remote.create_project(name=name, description=description)
            self.store.upsert_projects([project])
            return project
        local_names = {p.name for p in self.store.list_projects()}
        return self.store.create_local_project(
            name=unique_project_name(name, local_names),
            description=description,
            created_by="" if self.anonymous_offline else None,
        )

    def delete_project(self, project_id: str) -> None:
        remote = self._remote_for_project(project_id)
        if remote is None:
            raise RuntimeError("Sync this project to the server before deleting.")
        remote.delete_project(project_id)

    def list_members(self, project_id: str) -> list[Member]:
        if not self._use_remote(project_id):
            return []
        return self._members.list(project_id)

    def add_member(self, project_id: str, *, user_email: str, role: str) -> None:
        if not self._use_remote(project_id):
            raise RuntimeError("Members management requires a synced project.")
        self._members.add(project_id, user_email=user_email, role=role)

    def remove_member(self, project_id: str, *, member_user_id: str) -> None:
        if not self._use_remote(project_id):
            raise RuntimeError("Members management requires a synced project.")
        self._members.remove(project_id, member_user_id=member_user_id)

    def _scored_report(
        self,
        report_name: str,
        service: ScoredEntityService,
        project_id: str,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        """Ask the server for the report, or compute it from the local copy."""
        remote_report = _optional_callable(
            self._remote_for_project(project_id), report_name
        )
        if remote_report is not None:
            return dict(remote_report(project_id, **filters))
        return _local_scored_report(service.list(project_id), filters)

    def list_risks(self, project_id: str) -> list[Risk]:
        return self._risks.list(project_id)

    def risks_report(self, project_id: str, **filters: Any) -> dict[str, Any]:
        return self._scored_report("risks_report", self._risks, project_id, filters)

    def create_risk(
        self,
        project_id: str,
        *,
        title: str,
        probability: int,
        impact: int,
        **meta: Any,
    ) -> Risk:
        return self._risks.create(
            project_id,
            title=title,
            probability=probability,
            impact=impact,
            meta=meta,
        )

    def update_risk(
        self,
        project_id: str,
        risk_id: str,
        *,
        title: str,
        probability: int,
        impact: int,
        base_version: int | None = None,
        **meta: Any,
    ) -> Risk:
        with self.store.write_transaction():
            ent = self._risks.update(
                risk_id,
                title=title,
                probability=probability,
                impact=impact,
                meta=meta,
            )
            if base_version is not None:
                # The override belongs to the same unit of work as the local
                # entity update and outbox replacement.
                self.outbox.override_base_version(
                    project_id,
                    entity="risk",
                    entity_id=risk_id,
                    base_version=base_version,
                )
        return ent

    def delete_risk(self, project_id: str, risk_id: str) -> None:
        self._risks.delete(risk_id)

    # ---- Opportunities ----

    def list_opportunities(self, project_id: str) -> list[Opportunity]:
        return self._opps.list(project_id)

    def opportunities_report(self, project_id: str, **filters: Any) -> dict[str, Any]:
        return self._scored_report(
            "opportunities_report", self._opps, project_id, filters
        )

    def create_opportunity(
        self,
        project_id: str,
        *,
        title: str,
        probability: int,
        impact: int,
        **meta: Any,
    ) -> Opportunity:
        return self._opps.create(
            project_id,
            title=title,
            probability=probability,
            impact=impact,
            meta=meta,
        )

    def update_opportunity(
        self,
        project_id: str,
        opportunity_id: str,
        *,
        title: str,
        probability: int,
        impact: int,
        base_version: int | None = None,
        **meta: Any,
    ) -> Opportunity:
        with self.store.write_transaction():
            ent = self._opps.update(
                opportunity_id,
                title=title,
                probability=probability,
                impact=impact,
                meta=meta,
            )
            if base_version is not None:
                self.outbox.override_base_version(
                    project_id,
                    entity="opportunity",
                    entity_id=opportunity_id,
                    base_version=base_version,
                )
        return ent

    def delete_opportunity(self, project_id: str, opportunity_id: str) -> None:
        self._opps.delete(opportunity_id)

    # ---- Actions ----

    def list_actions(self, project_id: str) -> list[Action]:
        return self._actions.list(project_id)

    def create_action(self, project_id: str, **kwargs: Any) -> Action:
        return self._actions.create(project_id, **kwargs)

    def update_action(
        self,
        project_id: str,
        action_id: str,
        *,
        base_version: int | None = None,
        **kwargs: Any,
    ) -> Action:
        with self.store.write_transaction():
            action = self._actions.update(action_id, **kwargs)
            if base_version is not None:
                self.outbox.override_base_version(
                    project_id,
                    entity="action",
                    entity_id=action_id,
                    base_version=base_version,
                )
        return action

    # ---- Assessments ----

    def current_user_id(self) -> str | None:
        if self.remote and getattr(self.remote, "current_user_id", None):
            uid = self.remote.current_user_id()
            if uid:
                self.store.set_meta("user_id", uid)
                return uid
        return self.store.get_meta("user_id")

    def is_superuser(self) -> bool:
        if self.remote:
            return bool(getattr(self.remote, "is_superuser", False))
        return False

    def list_assessments(
        self, project_id: str, item_type: str, item_id: str
    ) -> list[Assessment]:
        return self._assessments.list(project_id, item_type, item_id)

    def upsert_my_assessment(
        self,
        project_id: str,
        item_type: str,
        item_id: str,
        probability: int,
        impact: int,
        notes: str | None = None,
    ) -> Assessment:
        uid = self.current_user_id()
        if not uid:
            raise ValueError("No user_id available (log in online at least once).")
        return self._assessments.upsert_my(
            project_id,
            item_type,
            item_id,
            uid,
            probability,
            impact,
            notes,
        )

    # ---- Snapshots / history ----

    def create_snapshot(
        self, project_id: str, *, kind: str | None = None
    ) -> dict[str, Any]:
        remote = self._remote_for_project(project_id)
        if remote is None:
            raise RuntimeError("Snapshots require a synced project.")
        return remote.create_snapshot(project_id, kind=kind)

    def top_history(
        self,
        project_id: str,
        *,
        kind: str = "risks",
        limit: int = 10,
        from_ts: str | None = None,
        to_ts: str | None = None,
    ) -> list[dict[str, Any]]:
        remote = self._remote_for_project(project_id)
        if remote is None:
            return []
        return remote.top_history(
            project_id, kind=kind, limit=limit, from_ts=from_ts, to_ts=to_ts
        )

    # ---- Sync ----

    def pending_count(self, project_id: str | None = None) -> int:
        return self._sync.pending_count(project_id)

    def blocked_count(self, project_id: str | None = None) -> int:
        return self._sync.blocked_count(project_id)

    def deferred_count(self, project_id: str | None = None) -> int:
        return self._sync.deferred_count(project_id)

    def conflict_count(self, project_id: str | None = None) -> int:
        return self._sync.conflict_count(project_id)

    def error_count(self, project_id: str | None = None) -> int:
        return self._sync.error_count(project_id)

    def last_sync_time(self, project_id: str | None = None) -> str | None:
        return self._sync.last_sync_time(project_id)

    def next_retry_at(self, project_id: str | None = None) -> str | None:
        return self._sync.next_retry_at(project_id)

    def can_sync(self) -> bool:
        return self._sync.can_sync()

    def sync_project(
        self,
        project_id: str,
        *,
        should_cancel: Callable[[], bool] | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        if should_cancel is None and progress is None:
            return self._sync.sync_project(project_id)
        return self._sync.sync_project(
            project_id,
            should_cancel=should_cancel,
            progress=progress,
        )

    def blocked_details(self, project_id: str | None = None) -> list[dict[str, Any]]:
        return self._sync.blocked_details(project_id)

    def conflict_details(self, project_id: str | None = None) -> list[dict[str, Any]]:
        return self._sync.conflict_details(project_id)

    def resolve_conflict(
        self,
        change_id: str,
        resolution: str,
        choices: dict[str, str] | None = None,
        *,
        expected_server_version: int | None = None,
    ) -> dict[str, Any]:
        if choices is None and expected_server_version is None:
            return self._sync.resolve_conflict(change_id, resolution)
        return self._sync.resolve_conflict(
            change_id,
            resolution,
            choices,
            expected_server_version=expected_server_version,
        )

    # ---- Help Desk ---------------------------------------------------------

    def list_helpdesk_tickets(self, project_id: str) -> list[HelpDeskTicket]:
        return self._helpdesk.list(project_id)

    def create_helpdesk_ticket(
        self,
        project_id: str,
        *,
        title: str,
        description: str = "",
        category: str = "other",
        priority: str = "medium",
        reporter_email: str = "",
    ) -> HelpDeskTicket:
        return self._helpdesk.create(
            project_id,
            title=title,
            description=description,
            category=category,
            priority=priority,
            reporter_email=reporter_email,
        )

    def update_helpdesk_ticket(
        self,
        ticket_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        category: str | None = None,
        priority: str | None = None,
        status: str | None = None,
    ) -> HelpDeskTicket:
        return self._helpdesk.update(
            ticket_id,
            title=title,
            description=description,
            category=category,
            priority=priority,
            status=status,
        )

    def delete_helpdesk_ticket(self, ticket_id: str) -> None:
        self._helpdesk.delete(ticket_id)
