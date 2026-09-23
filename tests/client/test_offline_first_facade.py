from __future__ import annotations

import pytest
from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore
from riskapp_client.domain.domain_models import Project
from riskapp_client.services.offline_first_facade import OfflineFirstBackend


def test_online_project_list_uses_one_remote_request(tmp_path) -> None:
    """Listing projects does not make duplicate remote API calls."""
    class Remote:
        def __init__(self) -> None:
            self.calls = 0

        def list_projects(self):
            self.calls += 1
            return [Project(id="p1", name="Remote", description="", created_by="u1")]

    store = LocalStore(str(tmp_path / "offline.db"))
    try:
        remote = Remote()
        backend = OfflineFirstBackend(store, remote=remote)

        projects = backend.list_projects()

        assert [project.id for project in projects] == ["p1"]
        assert remote.calls == 1
    finally:
        store.close()


def test_automatic_project_refresh_does_not_hide_transport_failure(tmp_path) -> None:
    class Remote:
        @staticmethod
        def list_projects():
            raise RuntimeError("offline")

    store = LocalStore(str(tmp_path / "strict-projects.db"))
    backend = OfflineFirstBackend(store, remote=Remote())
    try:
        with pytest.raises(RuntimeError, match="offline"):
            backend.list_sync_projects()
    finally:
        store.close()


def test_automatic_project_refresh_includes_syncable_local_projects(tmp_path) -> None:
    class Remote:
        @staticmethod
        def list_projects():
            return [Project("server-1", "Remote", created_by="user-1")]

    store = LocalStore(str(tmp_path / "sync-projects.db"))
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
    try:
        assert [project.id for project in backend.list_sync_projects()] == [
            "server-1",
            "local-1",
        ]
        assert backend.can_auto_sync()
    finally:
        store.close()

    offline_store = LocalStore(str(tmp_path / "offline-only.db"))
    try:
        assert not OfflineFirstBackend(offline_store).can_auto_sync()
    finally:
        offline_store.close()
