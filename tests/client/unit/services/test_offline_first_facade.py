from __future__ import annotations

import pytest
from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore
from riskapp_client.domain.domain_models import Project
from riskapp_client.services.offline_first_facade import OfflineFirstBackend


def test_online_project_list_uses_one_remote_request(local_store) -> None:
    """Listing projects does not make duplicate remote API calls."""

    class Remote:
        def __init__(self) -> None:
            self.calls = 0

        def list_projects(self):
            self.calls += 1
            return [Project(id="p1", name="Remote", description="", created_by="u1")]

    remote = Remote()
    backend = OfflineFirstBackend(local_store, remote=remote)

    projects = backend.list_projects()

    assert [project.id for project in projects] == ["p1"]
    assert remote.calls == 1


def test_automatic_project_refresh_does_not_hide_transport_failure(local_store) -> None:
    class Remote:
        @staticmethod
        def list_projects():
            raise RuntimeError("offline")

    backend = OfflineFirstBackend(local_store, remote=Remote())
    with pytest.raises(RuntimeError, match="offline"):
        backend.list_sync_projects()


def test_automatic_project_refresh_includes_syncable_local_projects(tmp_path) -> None:
    class Remote:
        @staticmethod
        def list_projects():
            return [Project("server-1", "Remote", created_by="user-1")]

    with LocalStore(str(tmp_path / "sync-projects.db")) as store:
        store.create_local_project(
            name="Draft",
            project_id="local-1",
            created_by="user-1",
        )
        store.create_local_project(
            name="Private",
            project_id="local-private",
            created_by="",
        )
        backend = OfflineFirstBackend(store, remote=Remote())
        assert [project.id for project in backend.list_sync_projects()] == [
            "server-1",
            "local-1",
        ]
        assert backend.can_auto_sync()
    with LocalStore(str(tmp_path / "offline-only.db")) as offline_store:
        assert not OfflineFirstBackend(offline_store).can_auto_sync()


@pytest.mark.parametrize("status", [0, 408, 429, 503, 401, 403, 404])
def test_project_list_uses_cache_unless_the_request_is_invalid(local_store, status):
    from unittest.mock import Mock

    from riskapp_client.adapters.remote_api.rest_api_client import ApiError

    local_store.create_local_project(
        name="Cached", project_id="cached", created_by="u1"
    )
    remote = Mock()
    remote.list_projects.side_effect = ApiError(status, "unavailable")
    backend = OfflineFirstBackend(local_store, remote=remote)
    backend.create_risk("cached", title="Unsynced", probability=2, impact=2)
    queued = backend.outbox.get_pending_changes("cached")
    if status == 404:
        with pytest.raises(ApiError):
            backend.list_projects()
    else:
        assert [project.id for project in backend.list_projects()] == ["cached"]
        assert backend.outbox.get_pending_changes("cached") == queued
        assert [risk.title for risk in backend.list_risks("cached")] == ["Unsynced"]
        if status in (401, 403):
            with pytest.raises(ApiError):
                backend.list_sync_projects()


def test_project_list_does_not_hide_cache_write_failure(local_store, monkeypatch):
    import sqlite3
    from unittest.mock import Mock

    remote = Mock()
    remote.list_projects.return_value = [Project("remote", "Remote")]
    backend = OfflineFirstBackend(local_store, remote=remote)

    def fail(_projects):
        raise sqlite3.DatabaseError("disk failure")

    monkeypatch.setattr(local_store, "sync_projects", fail)
    with pytest.raises(sqlite3.DatabaseError, match="disk failure"):
        backend.list_projects()


def test_project_list_does_not_hide_unexpected_adapter_failure(local_store):
    from unittest.mock import Mock

    remote = Mock()
    remote.list_projects.side_effect = ValueError("adapter bug")
    with pytest.raises(ValueError, match="adapter bug"):
        OfflineFirstBackend(local_store, remote=remote).list_projects()
