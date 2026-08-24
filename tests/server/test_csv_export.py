from __future__ import annotations

import csv
import io

from fastapi.testclient import TestClient


def test_csv_export_neutralizes_spreadsheet_formulas(tmp_path, isolated_app_factory):
    """User-controlled CSV cells cannot execute as spreadsheet formulas."""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'csv.db'}")
    with TestClient(app) as client:
        registered = client.post(
            "/register",
            json={"email": "csv@example.com", "password": "Password123!"},
        ).json()
        headers = {"Authorization": f"Bearer {registered['access_token']}"}
        project_id = client.post(
            "/projects", json={"name": "CSV"}, headers=headers
        ).json()["id"]
        created = client.post(
            f"/projects/{project_id}/risks",
            json={
                "title": '=HYPERLINK("https://example.invalid")',
                "code": "+RUN",
                "probability": 2,
                "impact": 3,
            },
            headers=headers,
        )
        assert created.status_code == 201, created.text

        response = client.get(
            f"/projects/{project_id}/risks/export.csv", headers=headers
        )

        assert response.status_code == 200
        rows = list(csv.DictReader(io.StringIO(response.text)))
        assert rows[0]["title"].startswith("'=")
        assert rows[0]["code"].startswith("'+")
