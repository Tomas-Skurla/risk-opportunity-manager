from __future__ import annotations

import csv
import io

from support import create_item, create_project, register_user


def test_csv_export_neutralizes_spreadsheet_formulas(api):
    """User-controlled CSV cells cannot execute as spreadsheet formulas."""
    user = register_user(api)
    project = create_project(api, user, name="CSV")
    create_item(
        api,
        project,
        user,
        kind="risk",
        title='=HYPERLINK("https://example.invalid")',
        code="+RUN",
    )
    response = api.get(f"/projects/{project.id}/risks/export.csv", headers=user.headers)
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows[0]["title"].startswith("'=")
    assert rows[0]["code"].startswith("'+")
