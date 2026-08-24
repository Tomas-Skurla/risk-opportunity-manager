from __future__ import annotations


def test_online_project_list_uses_one_remote_request(tmp_path) -> None:
    """Listing projects does not make duplicate remote API calls."""
    from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore
    from riskapp_client.domain.domain_models import Project
    from riskapp_client.services.offline_first_facade import OfflineFirstBackend

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
