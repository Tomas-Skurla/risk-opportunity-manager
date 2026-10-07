"""An open editor keeps saving cleanly after its own changes are synchronized."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from PySide6.QtWidgets import QMessageBox
from riskapp_client.domain.domain_models import Project
from riskapp_client.services.offline_first_facade import OfflineFirstBackend
from riskapp_client.ui_v2.main_application_window import MainWindow
from support import InProcessRemote, create_item, create_project, register_user

# The test drives the real window's editor and sync slots directly.
# pylint: disable=protected-access

_COLLECTIONS = {"risk": "risks", "opportunity": "opportunities", "action": "actions"}


def _start_new(window: MainWindow, kind: str) -> None:
    if kind == "risk":
        window._start_new_risk()
    elif kind == "opportunity":
        window._start_new_opportunity()
    else:
        window._start_new_action()
        window.actions_tab.action_risk_combo.setCurrentIndex(0)


def _save(window: MainWindow, kind: str, title: str) -> None:
    payload = {"title": title, "probability": 2, "impact": 2}
    if kind == "risk":
        window._save_risk(payload)
    elif kind == "opportunity":
        window._save_opportunity(payload)
    else:
        window.actions_tab.action_title.setText(title)
        window._save_action()


@pytest.mark.parametrize("kind", ["risk", "opportunity", "action"])
def test_editing_on_after_own_sync_does_not_conflict(
    kind, tmp_path, local_store, isolated_app_factory, qtbot, monkeypatch
) -> None:
    for dialog in ("information", "warning"):
        monkeypatch.setattr(QMessageBox, dialog, lambda *_args: None)
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'server.sqlite3'}")
    with TestClient(app) as client:
        user = register_user(client)
        project = create_project(client, user, name="Editors")
        create_item(client, project, user, kind="risk", title="Action parent")
        local_store.upsert_projects([Project(project.id, "Editors")])
        backend = OfflineFirstBackend(local_store)
        window = MainWindow(backend)
        qtbot.addWidget(window)
        window.top_tab.auto_snap_timer.stop()
        qtbot.waitUntil(lambda: not window._background_jobs.is_busy)
        backend.adopt_authenticated_remote(InProcessRemote(client, user))
        assert backend.sync_project(project.id)["state"] == "complete"
        window.current_project_id = project.id
        window._refresh_all_views(include_remote=False)

        def sync(*, automatic: bool = False) -> dict:
            result = backend.sync_project(project.id)
            if automatic:
                window._automatic_sync_succeeded(
                    {"state": result["state"], "projects": [result]}
                )
            else:
                window._sync_succeeded(result)
            return result

        _start_new(window, kind)
        _save(window, kind, "Created")
        results = [sync()]  # the create becomes version 1
        _save(window, kind, "Edited once")
        results.append(sync(automatic=True))
        _save(window, kind, "Edited twice")
        results.append(sync())

        assert [(r["state"], r["pushed"], r["conflicts"]) for r in results] == [
            ("complete", 1, 0)
        ] * 3
        response = client.get(
            f"/projects/{project.id}/{_COLLECTIONS[kind]}", headers=user.headers
        )
        saved = [row for row in response.json() if row["title"] != "Action parent"]
        assert [(row["title"], row["version"]) for row in saved] == [
            ("Edited twice", 3)
        ]
        window.close()
