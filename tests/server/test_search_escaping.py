"""Search wildcard escaping."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_search_for_percent_does_not_match_everything(tmp_path, isolated_app_factory):
    """Search for literal '%' is escaped and does not match every record"""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'search.db'}")
    with TestClient(app) as c:
        r = c.post(
            "/register",
            json={"email": "s@test.com", "password": "Password123!"},
        )
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = c.post("/projects", json={"name": "P"}, headers=h)
        pid = r.json()["id"]

        c.post(
            f"/projects/{pid}/risks",
            json={
                "type": "risk",
                "title": "Server outage",
                "probability": 4,
                "impact": 4,
            },
            headers=h,
        )
        c.post(
            f"/projects/{pid}/risks",
            json={
                "type": "risk",
                "title": "Data loss",
                "probability": 3,
                "impact": 5,
            },
            headers=h,
        )

        literal = c.post(
            f"/projects/{pid}/risks",
            json={
                "type": "risk",
                "title": "Budget 100% overrun",
                "probability": 2,
                "impact": 2,
            },
            headers=h,
        ).json()

        # A literal "%" should match only the title that contains it.
        r = c.get(
            f"/projects/{pid}/risks?search=%25",  # %25 is URL-encoded "%"
            headers=h,
        )
        assert r.status_code == 200
        assert [item["id"] for item in r.json()] == [literal["id"]]


def test_search_for_underscore_does_not_match_single_char(
    tmp_path, isolated_app_factory
):
    """Search for literal '_' is escaped and does not match arbitrary single chars"""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'search2.db'}")
    with TestClient(app) as c:
        r = c.post(
            "/register",
            json={"email": "s@test.com", "password": "Password123!"},
        )
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        r = c.post("/projects", json={"name": "P"}, headers=h)
        pid = r.json()["id"]

        c.post(
            f"/projects/{pid}/risks",
            json={
                "type": "risk",
                "title": "ABC",
                "probability": 1,
                "impact": 1,
            },
            headers=h,
        )

        literal = c.post(
            f"/projects/{pid}/risks",
            json={
                "type": "risk",
                "title": "ABC_DEF",
                "probability": 1,
                "impact": 1,
            },
            headers=h,
        ).json()

        # "_" should match the literal underscore, not any arbitrary character.
        r = c.get(f"/projects/{pid}/risks?search=_", headers=h)
        assert r.status_code == 200
        assert [item["id"] for item in r.json()] == [literal["id"]]
