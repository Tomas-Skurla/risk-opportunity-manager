"""End-to-end client/server regressions for cross-device synchronization."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore
from riskapp_client.adapters.local_storage.sync_outbox_queue import OutboxStore
from riskapp_client.services.offline_first_facade import OfflineFirstBackend
from riskapp_client.services.synchronization_service import SyncService


class _RemoteError(RuntimeError):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class _InProcessRemote:
    """Small adapter that connects the real client to an in-process API."""

    def __init__(
        self,
        client: TestClient,
        project_id: str,
        headers: dict[str, str],
    ) -> None:
        self.client = client
        self.project_id = project_id
        self.headers = headers
        self.fail_pull = False

    @staticmethod
    def _body(response: Any) -> dict[str, Any]:
        if response.status_code >= 400:
            body = response.json()
            detail = str(body.get("detail") or response.text)
            raise _RemoteError(response.status_code, detail)
        parsed = response.json()
        assert isinstance(parsed, dict)
        return parsed

    def sync_push(
        self, project_id: str, changes: list[dict[str, Any]]
    ) -> dict[str, Any]:
        assert project_id == self.project_id
        response = self.client.post(
            f"/projects/{project_id}/sync/push",
            json={"project_id": project_id, "changes": changes},
            headers=self.headers,
        )
        return self._body(response)

    def sync_pull(
        self,
        project_id: str,
        since: str,
        *,
        since_sequence: int = 0,
        limit_per_entity: int | None = None,
        cursors: dict[str, str] | None = None,
        snapshot_time: str | None = None,
        snapshot_sequence: int | None = None,
    ) -> dict[str, Any]:
        assert project_id == self.project_id
        if self.fail_pull:
            raise _RemoteError(503, "simulated pull outage")
        payload: dict[str, Any] = {
            "project_id": project_id,
            "since": since,
            "since_sequence": since_sequence,
        }
        optional = {
            "limit_per_entity": limit_per_entity,
            "cursors": cursors,
            "snapshot_time": snapshot_time,
            "snapshot_sequence": snapshot_sequence,
        }
        payload.update(
            {key: value for key, value in optional.items() if value is not None}
        )
        response = self.client.post(
            f"/projects/{project_id}/sync/pull",
            json=payload,
            headers=self.headers,
        )
        return self._body(response)


def _server_project(client: TestClient, email: str) -> tuple[str, dict[str, str]]:
    registered = client.post(
        "/register",
        json={"email": email, "password": "Password123!"},
    )
    assert registered.status_code == 201, registered.text
    headers = {
        "Authorization": f"Bearer {registered.json()['access_token']}"
    }
    project = client.post(
        "/projects",
        json={"name": "Cross-device synchronization"},
        headers=headers,
    )
    assert project.status_code == 201, project.text
    return project.json()["id"], headers


def _backend(
    db_path: Any,
    project_id: str,
    remote: _InProcessRemote,
) -> OfflineFirstBackend:
    store = LocalStore(str(db_path))
    store.create_local_project(name="Project", project_id=project_id)
    return OfflineFirstBackend(store, remote=remote)


def test_editing_after_a_conflict_keeps_the_conflict_blocked(
    tmp_path,
    isolated_app_factory,
) -> None:
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'server.db'}")
    with TestClient(app) as client:
        project_id, headers = _server_project(client, "devices@test.com")
        created = client.post(
            f"/projects/{project_id}/risks",
            json={
                "type": "risk",
                "code": "R-001",
                "title": "Original",
                "probability": 2,
                "impact": 2,
            },
            headers=headers,
        )
        assert created.status_code == 201, created.text
        risk_id = created.json()["id"]

        remote = _InProcessRemote(client, project_id, headers)
        alice = _backend(tmp_path / "alice.db", project_id, remote)
        bob = _backend(tmp_path / "bob.db", project_id, remote)
        try:
            assert alice.sync_project(project_id)["state"] == "complete"
            assert bob.sync_project(project_id)["state"] == "complete"

            bob.update_risk(
                project_id,
                risk_id,
                title="Bob's value",
                probability=5,
                impact=5,
            )
            assert bob.sync_project(project_id)["state"] == "complete"

            alice.update_risk(
                project_id,
                risk_id,
                title="Alice's value",
                probability=3,
                impact=3,
            )
            conflicted = alice.sync_project(project_id)
            assert conflicted["conflicts"] == 1
            before = alice.conflict_details(project_id)
            assert len(before) == 1
            conflict_id = before[0]["change_id"]

            alice.update_risk(
                project_id,
                risk_id,
                title="Alice edited again",
                probability=4,
                impact=3,
            )

            after = alice.conflict_details(project_id)
            assert len(after) == 1
            assert after[0]["change_id"] == conflict_id
            assert after[0]["record"]["title"] == "Alice edited again"
            assert after[0]["base_version"] == created.json()["version"]
            row = alice.store.get_risk_row(risk_id)
            assert row is not None
            assert row["version"] == created.json()["version"]
        finally:
            alice.store.close()
            bob.store.close()


def test_accepted_push_survives_a_failed_pull_and_can_then_be_deleted(
    tmp_path,
    isolated_app_factory,
) -> None:
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'server.db'}")
    with TestClient(app) as client:
        project_id, headers = _server_project(client, "lost-pull@test.com")
        remote = _InProcessRemote(client, project_id, headers)
        backend = _backend(tmp_path / "device.db", project_id, remote)
        try:
            risk = backend.create_risk(
                project_id,
                title="Created offline",
                probability=2,
                impact=3,
            )
            remote.fail_pull = True

            result = backend.sync_project(project_id)

            assert result["state"] == "retry_wait"
            row = backend.store.get_risk_row(risk.id)
            assert row is not None
            assert row["version"] == 1
            assert backend.pending_count(project_id) == 0

            backend.delete_risk(project_id, risk.id)
            pending = backend.outbox.get_pending_changes(project_id)
            assert len(pending) == 1
            assert pending[0]["op"] == "delete"
            assert pending[0]["base_version"] == 1

            remote.fail_pull = False
            assert backend.sync_project(project_id)["state"] == "complete"
            pulled = remote.sync_pull(
                project_id,
                "1970-01-01T00:00:00",
                since_sequence=0,
            )
            server_row = next(
                item for item in pulled["risks"] if item["id"] == risk.id
            )
            assert server_row["is_deleted"] is True
        finally:
            backend.store.close()


def test_two_offline_devices_with_the_same_code_converge(
    tmp_path,
    isolated_app_factory,
) -> None:
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'server.db'}")
    with TestClient(app) as client:
        project_id, headers = _server_project(client, "codes@test.com")
        remote = _InProcessRemote(client, project_id, headers)
        first = _backend(tmp_path / "first.db", project_id, remote)
        second = _backend(tmp_path / "second.db", project_id, remote)
        try:
            first_risk = first.create_risk(
                project_id, title="First", probability=2, impact=2
            )
            second_risk = second.create_risk(
                project_id, title="Second", probability=3, impact=3
            )
            assert first_risk.code == second_risk.code == "R-001"

            assert first.sync_project(project_id)["state"] == "complete"
            second_result = second.sync_project(project_id)

            assert second_result["state"] == "complete"
            assert second_result["errors"] == 0
            second_row = second.store.get_risk_row(second_risk.id)
            assert second_row is not None
            assert second_row["code"] == "R-002"
            assert second.pending_count(project_id) == 0

            pulled = remote.sync_pull(
                project_id,
                "1970-01-01T00:00:00",
                since_sequence=0,
            )
            codes = {
                item["id"]: item["code"]
                for item in pulled["risks"]
                if item["id"] in {first_risk.id, second_risk.id}
            }
            assert codes == {
                first_risk.id: "R-001",
                second_risk.id: "R-002",
            }
        finally:
            first.store.close()
            second.store.close()


def test_two_local_creates_accept_server_code_reallocation_as_one_batch(
    tmp_path,
    isolated_app_factory,
) -> None:
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'server.db'}")
    with TestClient(app) as client:
        project_id, headers = _server_project(client, "code-batch@test.com")
        remote = _InProcessRemote(client, project_id, headers)
        first = _backend(tmp_path / "first.db", project_id, remote)
        second = _backend(tmp_path / "second.db", project_id, remote)
        try:
            first.create_risk(
                project_id,
                title="Already on server",
                probability=2,
                impact=2,
            )
            assert first.sync_project(project_id)["state"] == "complete"

            local_one = second.create_risk(
                project_id,
                title="First local create",
                probability=3,
                impact=3,
            )
            local_two = second.create_risk(
                project_id,
                title="Second local create",
                probability=4,
                impact=4,
            )
            assert (local_one.code, local_two.code) == ("R-001", "R-002")

            result = second.sync_project(project_id)

            assert result["state"] == "complete"
            assert result["pushed"] == 2
            assert second.pending_count(project_id) == 0
            first_row = second.store.get_risk_row(local_one.id)
            second_row = second.store.get_risk_row(local_two.id)
            assert first_row is not None and first_row["code"] == "R-002"
            assert second_row is not None and second_row["code"] == "R-003"
        finally:
            first.store.close()
            second.store.close()


def test_pull_rows_and_watermark_are_one_local_transaction(tmp_path) -> None:
    store = LocalStore(str(tmp_path / "atomic-pull.db"))
    try:
        project = store.create_local_project(name="Project", project_id="project-1")
        store.upsert_local_risk(
            risk_id="risk-1",
            project_id=project.id,
            title="Before",
            probability=2,
            impact=2,
            version=1,
            dirty=0,
        )
        remote = Mock()
        remote.sync_pull.return_value = {
            "server_time": "2026-09-16T12:00:00",
            "server_sequence": 2,
            "risks": [
                {
                    "id": "risk-1",
                    "project_id": project.id,
                    "type": "risk",
                    "title": "After",
                    "probability": 4,
                    "impact": 4,
                    "version": 2,
                    "is_deleted": False,
                    "updated_at": "2026-09-16T12:00:00",
                }
            ],
            "opportunities": [],
            "actions": [],
            "assessments": [],
            "helpdesk_tickets": [],
        }
        original_apply = store.apply_pull_opportunities

        def fail_after_risks(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("simulated local apply failure")

        store.apply_pull_opportunities = fail_after_risks  # type: ignore[method-assign]
        service = SyncService(store, OutboxStore(store), remote)

        with pytest.raises(RuntimeError, match="simulated local apply failure"):
            service.sync_project(project.id)

        row = store.get_risk_row("risk-1")
        assert row is not None
        assert row["title"] == "Before"
        assert row["version"] == 1
        assert store.get_last_server_sequence(project.id) == 0
        store.apply_pull_opportunities = original_apply  # type: ignore[method-assign]
    finally:
        store.close()
