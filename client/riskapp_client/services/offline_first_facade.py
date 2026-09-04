from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore
from riskapp_client.adapters.local_storage.sync_outbox_queue import OutboxStore
from riskapp_client.domain.domain_models import (
    Action,
    Assessment,
    Backend,
    HelpDeskTicket,
    Member,
    Opportunity,
    Project,
    Risk,
)
from riskapp_client.services.action_management_service import ActionService
from riskapp_client.services.assessment_management_service import AssessmentService
from riskapp_client.services.entity_filters import (
    ScoredFilterCriteria,
    filter_scored,
    parse_date,
)
from riskapp_client.services.helpdesk_service import HelpDeskService
from riskapp_client.services.member_management_service import MembersService
from riskapp_client.services.scored_entity_management_service import (
    ScoredEntityService,
    ScoredEntityWiring,
)
from riskapp_client.services.synchronization_service import SyncService


class OfflineFirstBackend(Backend):
    """Backend implementation used by the Qt UI in offline-first mode."""

    def __init__(
        self,
        store: LocalStore,
        remote: Any | None = None,
        *,
        anonymous_offline: bool = False,
    ) -> None:
        self.store = store
        self.remote = remote
        self.anonymous_offline = anonymous_offline
        self.outbox = OutboxStore(store)
        self._risks = self._make_scored_service(
            kind="risk",
            id_kw="risk_id",
            model_cls=Risk,
            list_fn=store.list_risks,
            get_project_and_version_fn=store.get_risk_project_and_version,
            get_row_fn=store.get_risk_row,
            upsert_local_fn=store.upsert_local_risk,
            queue_upsert_fn=self.outbox.queue_risk_upsert,
            queue_delete_fn=self.outbox.queue_risk_delete,
            soft_delete_local_fn=store.soft_delete_risk,
            next_code_fn=store.next_risk_code,
        )
        self._opps = self._make_scored_service(
            kind="opportunity",
            id_kw="opportunity_id",
            model_cls=Opportunity,
            list_fn=store.list_opportunities,
            get_project_and_version_fn=store.get_opportunity_project_and_version,
            get_row_fn=store.get_opportunity_row,
            upsert_local_fn=store.upsert_local_opportunity,
            queue_upsert_fn=self.outbox.queue_opportunity_upsert,
            queue_delete_fn=self.outbox.queue_opportunity_delete,
            soft_delete_local_fn=store.soft_delete_opportunity,
            next_code_fn=store.next_opportunity_code,
        )
        self._actions = ActionService(store, self.outbox)
        self._assessments = AssessmentService(store, self.outbox)
        self._helpdesk = HelpDeskService(store, self.outbox)
        self._members = MembersService(remote)
        self._sync = SyncService(store, self.outbox, remote)

    def _use_remote(self, project_id: str | None = None) -> bool:
        if not self.remote:
            return False
        return not (project_id and str(project_id).startswith("local-"))

    def _discard_scored_changes(
        self,
        entity: str,
        project_id: str,
        entity_id: str,
    ) -> None:
        self.outbox.discard_entity_changes(
            project_id,
            entity=entity,
            entity_id=entity_id,
        )

    def _make_scored_service(
        self,
        *,
        kind: str,
        id_kw: str,
        model_cls: type[Risk] | type[Opportunity],  # noqa: PYI055
        list_fn: Any,
        get_project_and_version_fn: Any,
        get_row_fn: Any,
        upsert_local_fn: Any,
        queue_upsert_fn: Any,
        queue_delete_fn: Any,
        soft_delete_local_fn: Any,
        next_code_fn: Any,
    ) -> ScoredEntityService:
        return ScoredEntityService(
            ScoredEntityWiring(
                kind=kind,
                id_kw=id_kw,
                model_cls=model_cls,
                list_fn=list_fn,
                get_project_and_version_fn=get_project_and_version_fn,
                get_row_fn=get_row_fn,
                upsert_local_fn=upsert_local_fn,
                queue_upsert_fn=queue_upsert_fn,
                queue_delete_fn=queue_delete_fn,
                discard_pending_changes_fn=(
                    lambda project_id, entity_id: self._discard_scored_changes(
                        kind,
                        project_id,
                        entity_id,
                    )
                ),
                soft_delete_local_fn=soft_delete_local_fn,
                next_code_fn=next_code_fn,
            )
        )

    def list_projects(self) -> list[Project]:
        if self.remote:
            try:
                remote_projects = self.remote.list_projects()
                self.store.sync_projects(remote_projects)

                # Important security/UI rule:
                # When online, the project picker must show only projects returned
                # by /projects for the authenticated user. The local SQLite cache
                # may still contain old projects after membership removal because
                # sync_projects() deliberately preserves cached projects that have
                # local data. That cache should not make inaccessible projects
                # visible in the sidebar.
                if self.anonymous_offline:
                    return [
                        p
                        for p in self.store.list_projects()
                        if str(p.id).startswith("local-") and not p.created_by
                    ]

                local_projects = [
                    p
                    for p in self.store.list_projects()
                    if str(p.id).startswith("local-") and p.created_by
                ]

                by_id: dict[str, Project] = {}
                for p in list(remote_projects) + local_projects:
                    by_id[str(p.id)] = p
                return list(by_id.values())
            except Exception:
                logging.getLogger(__name__).debug(
                    "Remote list_projects failed, using local cache", exc_info=True
                )

        projects = self.store.list_projects()

        if self.anonymous_offline:
            projects = [
                p
                for p in projects
                if str(p.id).startswith("local-") and not p.created_by
            ]
        else:
            projects = [
                p
                for p in projects
                if not (str(p.id).startswith("local-") and not p.created_by)
            ]

        if projects:
            return projects

        if not self.remote:
            meta_key = (
                "bootstrap_anon_project_id"
                if self.anonymous_offline
                else "bootstrap_user_project_id"
            )
            bootstrap_id = self.store.get_meta(meta_key)
            if bootstrap_id:
                existing = self.store.get_project(str(bootstrap_id))
                if existing:
                    return [existing]

            p = self.store.create_local_project(
                name="Local Project",
                description="Offline project",
                created_by="" if self.anonymous_offline else None,
            )
            self.store.set_meta(meta_key, p.id)
            return [p]

        return projects

    def create_project(self, *, name: str, description: str = "") -> Project:
        if self.remote:
            try:
                existing_names = {p.name for p in (self.remote.list_projects() or [])}
                if name in existing_names:
                    n = 2
                    while f"{name} ({n})" in existing_names:
                        n += 1
                    name = f"{name} ({n})"
            except (AttributeError, KeyError):
                logging.getLogger(__name__).debug(
                    "Duplicate project name check failed", exc_info=True
                )
            project = self.remote.create_project(name=name, description=description)
            self.store.upsert_projects([project])
            return project
        local_names = {p.name for p in self.store.list_projects()}
        if name in local_names:
            n = 2
            while f"{name} ({n})" in local_names:
                n += 1
            name = f"{name} ({n})"
        return self.store.create_local_project(
            name=name,
            description=description,
            created_by="" if self.anonymous_offline else None,
        )

    def delete_project(self, project_id: str) -> None:
        if not self._use_remote(project_id):
            raise RuntimeError("Sync this project to the server before deleting.")
        self.remote.delete_project(project_id)

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

    def _generate_scored_report(self, items: list, filters: dict) -> dict:
        dt_from = parse_date(str(filters.get("from_date") or ""))
        dt_to = parse_date(str(filters.get("to_date") or ""))
        if dt_to:
            dt_to = dt_to.replace(hour=23, minute=59, second=59)

        crit = ScoredFilterCriteria(
            search=str(filters.get("search") or ""),
            min_score=int(filters.get("min_score") or 0),
            max_score=int(filters.get("max_score") or 999_999),
            status=str(filters.get("status") or "(any)"),
            category_contains=str(filters.get("category") or ""),
            owner_user_id=(
                str(filters.get("owner_user_id"))
                if filters.get("owner_user_id")
                else None
            ),
            owner_unassigned=bool(filters.get("owner_unassigned")),
            identified_from=dt_from,
            identified_to=dt_to,
        )
        filtered = filter_scored(items, crit)
        scores = [int(x.score or 0) for x in filtered]

        buckets = {"0-4": 0, "5-9": 0, "10-14": 0, "15-19": 0, "20-25": 0}
        for sc in scores:
            v = int(sc or 0)
            if v <= 4:
                buckets["0-4"] += 1
            elif v <= 9:
                buckets["5-9"] += 1
            elif v <= 14:
                buckets["10-14"] += 1
            elif v <= 19:
                buckets["15-19"] += 1
            else:
                buckets["20-25"] += 1

        return {
            "total": len(filtered),
            "project_total": len(items),
            "min_score": min(scores) if scores else None,
            "max_score": max(scores) if scores else None,
            "avg_score": (sum(scores) / len(scores)) if scores else None,
            "status_counts": dict(Counter((x.status or "concept") for x in filtered)),
            "category_counts": dict(
                Counter((x.category or "(none)") for x in filtered)
            ),
            "owner_counts": dict(
                Counter((x.owner_user_id or "(none)") for x in filtered)
            ),
            "score_buckets": buckets,
        }

    def list_risks(self, project_id: str) -> list[Risk]:
        return self._risks.list(project_id)

    def risks_report(self, project_id: str, **filters) -> dict:
        if self._use_remote(project_id) and getattr(self.remote, "risks_report", None):
            return dict(self.remote.risks_report(project_id, **filters))

        items = self._risks.list(project_id)
        return self._generate_scored_report(items, filters)

    def create_risk(
        self, project_id: str, *, title: str, probability: int, impact: int, **meta
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
        **meta,
    ) -> Risk:
        ent = self._risks.update(
            risk_id,
            title=title,
            probability=probability,
            impact=impact,
            meta=meta,
        )
        if base_version is not None:
            # Thread through explicit base_version overrides.
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

    def opportunities_report(self, project_id: str, **filters) -> dict:
        if self._use_remote(project_id) and getattr(
            self.remote, "opportunities_report", None
        ):
            return dict(self.remote.opportunities_report(project_id, **filters))

        items = self._opps.list(project_id)
        return self._generate_scored_report(items, filters)

    def create_opportunity(
        self, project_id: str, *, title: str, probability: int, impact: int, **meta
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
        **meta,
    ) -> Opportunity:
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

    def update_action(self, project_id: str, action_id: str, **kwargs: Any) -> Action:
        return self._actions.update(action_id, **kwargs)

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

    def create_snapshot(self, project_id: str, *, kind: str | None = None):
        if not self._use_remote(project_id):
            raise RuntimeError("Snapshots require a synced project.")
        return self.remote.create_snapshot(project_id, kind=kind)

    def top_history(
        self,
        project_id: str,
        *,
        kind: str = "risks",
        limit: int = 10,
        from_ts: str | None = None,
        to_ts: str | None = None,
    ):
        if not self._use_remote(project_id):
            return []
        return self.remote.top_history(
            project_id, kind=kind, limit=limit, from_ts=from_ts, to_ts=to_ts
        )

    # ---- Sync ----

    def pending_count(self, project_id: str | None = None) -> int:
        return self._sync.pending_count(project_id)

    def blocked_count(self, project_id: str | None = None) -> int:
        return self._sync.blocked_count(project_id)

    def conflict_count(self, project_id: str | None = None) -> int:
        return self._sync.conflict_count(project_id)

    def error_count(self, project_id: str | None = None) -> int:
        return self._sync.error_count(project_id)

    def last_sync_time(self, project_id: str | None = None) -> str | None:
        return self._sync.last_sync_time(project_id)

    def can_sync(self) -> bool:
        return self._sync.can_sync()

    def sync_project(self, project_id: str):
        return self._sync.sync_project(project_id)

    def blocked_details(self, project_id: str | None = None) -> list[dict[str, Any]]:
        return self._sync.blocked_details(project_id)

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
