"""Behavior tests for scored-entity mapping and offline orchestration."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from riskapp_client.adapters.mappers.scored_entity_mapper import (
    normalize_scored_payload_inplace,
    scored_entity_from_mapping,
    scored_entity_to_mapping,
)
from riskapp_client.domain.domain_models import Opportunity, Project, Risk
from riskapp_client.services.offline_first_facade import OfflineFirstBackend
from riskapp_client.services.scored_entity_management_service import (
    ScoredEntityService,
    ScoredEntityWiring,
)


class GetFallbackMapping(Mapping[str, object]):
    """Mapping that exercises the service's ``.get`` fallback."""

    def __init__(self, values: dict[str, object]) -> None:
        self.values = values

    def __getitem__(self, key: str) -> object:
        raise ValueError(key)

    def __iter__(self) -> Iterator[str]:
        return iter(self.values)

    def __len__(self) -> int:
        return len(self.values)

    def get(self, key: str, default=None):
        return self.values.get(key, default)


_DEFAULT_NEXT_CODE = object()


def _service(
    *,
    row: Mapping[str, object] | None = None,
    version: int = 2,
    next_code=_DEFAULT_NEXT_CODE,
):
    if next_code is _DEFAULT_NEXT_CODE:
        next_code = Mock(return_value="R-002")
    calls = SimpleNamespace(
        upsert=Mock(),
        queue_upsert=Mock(),
        queue_delete=Mock(),
        discard=Mock(),
        soft_delete=Mock(return_value=("project-1", version)),
        next_code=next_code,
    )
    wiring = ScoredEntityWiring(
        kind="risk",
        id_kw="risk_id",
        model_cls=Risk,
        list_fn=Mock(return_value=[]),
        get_project_and_version_fn=Mock(return_value=("project-1", version)),
        get_row_fn=Mock(return_value=row),
        upsert_local_fn=calls.upsert,
        queue_upsert_fn=calls.queue_upsert,
        queue_delete_fn=calls.queue_delete,
        discard_pending_changes_fn=calls.discard,
        soft_delete_local_fn=calls.soft_delete,
        next_code_fn=next_code,
    )
    return ScoredEntityService(wiring), calls, wiring


def test_scored_payload_normalization_covers_strict_and_lenient_inputs() -> None:
    empty: dict[str, object] = {}
    normalize_scored_payload_inplace(empty)
    assert empty == {}

    payload: dict[str, object] = {
        "probability": " 4 ",
        "impact": True,
        "impact_cost": "5",
        "impact_time": "",
        "impact_scope": False,
        "impact_quality": "invalid",
        "description": "  details  ",
    }
    normalize_scored_payload_inplace(payload)
    assert payload == {
        "probability": 4,
        "impact": 1,
        "impact_cost": 5,
        "impact_time": None,
        "impact_scope": None,
        "impact_quality": None,
        "description": "details",
    }

    with pytest.raises(ValueError, match="probability must be an integer"):
        normalize_scored_payload_inplace({"probability": "bad"})

    lenient = {"probability": "bad", "impact": None}
    normalize_scored_payload_inplace(lenient, strict_required_ints=False)
    assert lenient == {"probability": 1, "impact": 1}


def test_scored_mapping_round_trip_and_validation() -> None:
    with pytest.raises(ValueError, match="empty"):
        scored_entity_from_mapping({}, model_cls=Risk)
    with pytest.raises(KeyError, match="id.*project_id"):
        scored_entity_from_mapping({"id": "risk-1"}, model_cls=Risk)

    risk = scored_entity_from_mapping(
        {
            "id": " risk-1 ",
            "project_id": " project-1 ",
            "title": None,
            "probability": "4",
            "impact": "bad",
            "impact_cost": "2",
            "impact_time": False,
            "owner_user_id": "  user-1 ",
            "identified_at": " 2026-01-01 ",
            "description": "  ",
            "is_deleted": 1,
            "version": "3",
        },
        model_cls=Risk,
    )
    assert risk.id == "risk-1"
    assert risk.project_id == "project-1"
    assert risk.title == ""
    assert risk.probability == 4
    assert risk.impact == 2
    assert risk.owner_user_id == "user-1"
    assert risk.description is None
    assert risk.is_deleted is True

    full = scored_entity_to_mapping(risk)
    assert full["project_id"] == "project-1"
    assert full["score"] == 8
    assert full["version"] == 3

    compact = scored_entity_to_mapping(
        risk,
        include_project_id=False,
        include_sync=False,
        include_score=False,
        include_nones=False,
    )
    assert "project_id" not in compact
    assert "version" not in compact
    assert "score" not in compact
    assert "description" not in compact


def test_scored_service_create_update_delete_and_code_fallbacks(monkeypatch) -> None:
    monkeypatch.setattr(
        "riskapp_client.services.scored_entity_management_service.uuid.uuid4",
        lambda: "risk-new",
    )
    service, calls, wiring = _service(
        row=GetFallbackMapping(
            {
                "status": "active",
                "status_changed_at": "old-status-date",
                "code": "R-001",
                "description": "old description",
            }
        )
    )

    created = service.create(
        "project-1",
        title="Created",
        probability=2,
        impact=3,
        meta={
            "status": None,
            "description": "details",
            "owner_user_id": None,
            "code": " ",
        },
    )
    assert created.id == "risk-new"
    assert created.code == "R-002"
    assert created.score == 6
    assert calls.upsert.call_args.kwargs["dirty"] == 1
    calls.queue_upsert.assert_called_once()

    updated = service.update(
        "risk-1",
        title="Updated",
        probability=5,
        impact=4,
        meta={"status": "closed", "category": "ops", "code": None},
    )
    assert updated.version == 2
    assert updated.status == "closed"
    assert updated.status_changed_at != "old-status-date"
    assert updated.code == "R-001"
    assert updated.description == "old description"

    service.delete("risk-1")
    calls.queue_delete.assert_called_once_with("project-1", "risk-1")

    assert service._ensure_code("project-1", 42, existing=None) == "42"
    assert service._ensure_code("project-1", " explicit ", existing=None) == "explicit"

    no_counter, _, _ = _service(next_code=None)
    assert no_counter._ensure_code("project-1", None, existing=None) is None

    unsynced, unsynced_calls, _ = _service(version=0)
    unsynced.delete("local-risk")
    unsynced_calls.discard.assert_called_once_with("project-1", "local-risk")
    unsynced_calls.queue_delete.assert_not_called()

    broken_code = Mock(side_effect=RuntimeError("counter unavailable"))
    broken, _, _ = _service(next_code=broken_code)
    assert broken._ensure_code("project-1", "", existing="") is None


def _facade(**values) -> OfflineFirstBackend:
    backend = object.__new__(OfflineFirstBackend)
    defaults = {
        "remote": None,
        "anonymous_offline": False,
        "store": Mock(),
        "outbox": Mock(),
        "_risks": Mock(),
        "_opps": Mock(),
        "_actions": Mock(),
        "_assessments": Mock(),
        "_helpdesk": Mock(),
        "_members": Mock(),
        "_sync": Mock(),
    }
    defaults.update(values)
    for name, value in defaults.items():
        setattr(backend, name, value)
    return backend


def test_offline_facade_project_visibility_bootstrap_and_naming() -> None:
    remote_projects = [Project("server-1", "Remote", created_by="owner")]
    local_user = Project("local-user", "Draft", created_by="owner")
    local_anon = Project("local-anon", "Private", created_by="")
    store = Mock()
    store.list_projects.return_value = [local_user, local_anon]
    remote = Mock()
    remote.list_projects.return_value = remote_projects
    backend = _facade(store=store, remote=remote)

    assert [p.id for p in backend.list_projects()] == ["server-1", "local-user"]
    store.sync_projects.assert_called_once_with(remote_projects)

    backend.anonymous_offline = True
    assert [p.id for p in backend.list_projects()] == ["local-anon"]

    remote.list_projects.side_effect = RuntimeError("offline")
    assert [p.id for p in backend.list_projects()] == ["local-anon"]

    backend.remote = None
    backend.anonymous_offline = False
    store.list_projects.return_value = []
    store.get_meta.return_value = "local-existing"
    existing = Project("local-existing", "Existing")
    store.get_project.return_value = existing
    assert backend.list_projects() == [existing]

    store.get_project.return_value = None
    created = Project("local-created", "Local Project")
    store.create_local_project.return_value = created
    assert backend.list_projects() == [created]
    store.set_meta.assert_called_with("bootstrap_user_project_id", "local-created")

    store.list_projects.return_value = [
        Project("p1", "Name"),
        Project("p2", "Name (2)"),
    ]
    local_created = Project("p3", "Name (3)")
    store.create_local_project.return_value = local_created
    assert backend.create_project(name="Name").name == "Name (3)"
    store.create_local_project.assert_called_with(
        name="Name (3)", description="", created_by=None
    )

    remote = Mock()
    remote.list_projects.return_value = [Project("p1", "Name")]
    remote.create_project.return_value = Project("server-2", "Name (2)")
    backend.remote = remote
    result = backend.create_project(name="Name", description="desc")
    assert result.id == "server-2"
    remote.create_project.assert_called_with(name="Name (2)", description="desc")
    store.upsert_projects.assert_called_with([result])


def test_offline_facade_permissions_reports_and_delegation() -> None:
    remote = Mock()
    remote.is_superuser = True
    store = Mock()
    backend = _facade(store=store, remote=remote)

    assert backend._use_remote("server-1") is True
    assert backend._use_remote("local-1") is False
    backend.remote = None
    assert backend._use_remote("server-1") is False
    backend.remote = remote

    with pytest.raises(RuntimeError, match="before deleting"):
        backend.delete_project("local-1")
    backend.delete_project("server-1")
    remote.delete_project.assert_called_once_with("server-1")

    assert backend.list_members("local-1") == []
    with pytest.raises(RuntimeError, match="synced project"):
        backend.add_member("local-1", user_email="u@example.test", role="member")
    with pytest.raises(RuntimeError, match="synced project"):
        backend.remove_member("local-1", member_user_id="user-1")

    backend.list_members("server-1")
    backend.add_member("server-1", user_email="u@example.test", role="manager")
    backend.remove_member("server-1", member_user_id="user-1")
    backend._members.list.assert_called_once_with("server-1")
    backend._members.add.assert_called_once()
    backend._members.remove.assert_called_once()

    risks = [
        Risk("r1", "local-1", title="A", probability=1, impact=2, status="open"),
        Risk(
            "r2",
            "local-1",
            title="B",
            probability=2,
            impact=3,
            status="active",
            category="ops",
            owner_user_id="user-1",
        ),
        Risk("r3", "local-1", title="C", probability=5, impact=5, status="closed"),
    ]
    backend._risks.list.return_value = risks
    report = backend.risks_report("local-1", min_score=0, max_score=25, status="(any)")
    assert report["total"] == 3
    assert report["min_score"] == 2
    assert report["max_score"] == 25
    assert report["score_buckets"] == {
        "0-4": 1,
        "5-9": 1,
        "10-14": 0,
        "15-19": 0,
        "20-25": 1,
    }

    remote.risks_report.return_value = {"total": 99}
    assert backend.risks_report("server-1") == {"total": 99}
    remote.opportunities_report.return_value = {"total": 7}
    assert backend.opportunities_report("server-1") == {"total": 7}

    backend._risks.create.return_value = Risk("r4", "p", title="new")
    backend.create_risk("p", title="new", probability=2, impact=2, category="ops")
    backend.update_risk(
        "p", "r4", title="changed", probability=3, impact=4, base_version=8
    )
    backend.delete_risk("p", "r4")
    backend.outbox.override_base_version.assert_called_with(
        "p", entity="risk", entity_id="r4", base_version=8
    )
    backend._risks.delete.assert_called_once_with("r4")

    backend._opps.create.return_value = Opportunity("o1", "p", title="new")
    backend.create_opportunity("p", title="new", probability=2, impact=2)
    backend.update_opportunity(
        "p", "o1", title="changed", probability=3, impact=4, base_version=9
    )
    backend.delete_opportunity("p", "o1")
    backend.outbox.override_base_version.assert_called_with(
        "p", entity="opportunity", entity_id="o1", base_version=9
    )


def test_offline_facade_user_snapshot_sync_and_feature_wrappers() -> None:
    remote = Mock()
    remote.current_user_id.return_value = "user-1"
    remote.is_superuser = True
    store = Mock()
    backend = _facade(store=store, remote=remote)

    assert backend.current_user_id() == "user-1"
    store.set_meta.assert_called_with("user_id", "user-1")
    remote.current_user_id.return_value = None
    store.get_meta.return_value = "cached-user"
    assert backend.current_user_id() == "cached-user"
    assert backend.is_superuser() is True

    store.get_meta.return_value = None
    with pytest.raises(ValueError, match="No user_id"):
        backend.upsert_my_assessment("p", "risk", "r", 2, 3)
    store.get_meta.return_value = "cached-user"
    backend.upsert_my_assessment("p", "risk", "r", 2, 3, "notes")
    backend._assessments.upsert_my.assert_called_once_with(
        "p", "risk", "r", "cached-user", 2, 3, "notes"
    )

    with pytest.raises(RuntimeError, match="Snapshots require"):
        backend.create_snapshot("local-1")
    assert backend.top_history("local-1") == []
    backend.create_snapshot("server-1", kind="risks")
    backend.top_history("server-1", kind="opportunities", limit=4)
    remote.create_snapshot.assert_called_once_with("server-1", kind="risks")
    remote.top_history.assert_called_once()

    backend.list_actions("p")
    backend.create_action("p", title="a")
    backend.update_action("p", "a1", title="b")
    backend.list_assessments("p", "risk", "r")
    backend.pending_count("p")
    backend.blocked_count("p")
    backend.conflict_count("p")
    backend.error_count("p")
    backend.last_sync_time("p")
    backend.can_sync()
    backend.sync_project("p")
    backend.blocked_details("p")
    backend.list_helpdesk_tickets("p")
    backend.create_helpdesk_ticket("p", title="ticket")
    backend.update_helpdesk_ticket("t1", status="closed")
    backend.delete_helpdesk_ticket("t1")

    backend._actions.list.assert_called_once_with("p")
    backend._actions.create.assert_called_once()
    backend._actions.update.assert_called_once()
    backend._assessments.list.assert_called_once_with("p", "risk", "r")
    backend._sync.sync_project.assert_called_once_with("p")
    backend._sync.conflict_count.assert_called_once_with("p")
    backend._sync.error_count.assert_called_once_with("p")
    backend._sync.last_sync_time.assert_called_once_with("p")
    backend._helpdesk.delete.assert_called_once_with("t1")
