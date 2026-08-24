from __future__ import annotations

from fastapi.testclient import TestClient


def test_register_create_project_create_items_and_matrix(
    tmp_path, isolated_app_factory
) -> None:
    """Register, create project, add risk + opportunity, and verify matrix counts"""
    db_file = tmp_path / "api_smoke.db"
    app = isolated_app_factory(f"sqlite+pysqlite:///{db_file}")
    with TestClient(app) as c:
        r = c.post(
            "/register",
            json={"email": "admin@example.com", "password": "Password123!"},
        )
        assert r.status_code == 201, r.text
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        r = c.post(
            "/projects",
            json={"name": "Demo Project", "description": ""},
            headers=headers,
        )
        assert r.status_code == 201, r.text
        project_id = r.json()["id"]
        r = c.post(
            f"/projects/{project_id}/risks",
            json={"type": "risk", "title": "Risk A", "probability": 4, "impact": 3},
            headers=headers,
        )
        assert r.status_code == 201, r.text
        r = c.post(
            f"/projects/{project_id}/opportunities",
            json={
                "type": "opportunity",
                "title": "Opp A",
                "probability": 2,
                "impact": 5,
            },
            headers=headers,
        )
        assert r.status_code == 201, r.text
        r = c.get(f"/projects/{project_id}/matrix?kind=both", headers=headers)
        assert r.status_code == 200, r.text
        payload = r.json()
        assert payload["kind"] == "both"
        assert payload["risks"][3][2] == 1
        assert payload["opportunities"][1][4] == 1
