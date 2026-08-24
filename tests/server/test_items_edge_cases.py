"""Item CRUD edge cases: duplicate code, stale base_version, filter mutex."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def _setup(c: TestClient):
    r = c.post(
        "/register",
        json={"email": "edge@test.com", "password": "Password123!"},
    )
    assert r.status_code == 201, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}

    pid = c.post("/projects", json={"name": "P"}, headers=h).json()["id"]
    return h, pid


def test_duplicate_item_code_returns_409(tmp_path, isolated_app_factory):
    """Creating a second risk with the same explicit code returns HTTP 409"""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'edge_code.db'}")
    with TestClient(app) as c:
        h, pid = _setup(c)

        r = c.post(
            f"/projects/{pid}/risks",
            json={
                "type": "risk",
                "title": "First",
                "probability": 2,
                "impact": 2,
                "code": "R-DUPLICATE",
            },
            headers=h,
        )
        assert r.status_code == 201, r.text

        r = c.post(
            f"/projects/{pid}/risks",
            json={
                "type": "risk",
                "title": "Second",
                "probability": 2,
                "impact": 2,
                "code": "R-DUPLICATE",
            },
            headers=h,
        )
        assert r.status_code == 409, r.text
        assert "code" in r.json()["detail"].lower()


def test_item_patch_with_stale_base_version_returns_409(tmp_path, isolated_app_factory):
    """Risk PATCH with stale base_version returns 409 with version_mismatch reason"""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'edge_version.db'}")
    with TestClient(app) as c:
        h, pid = _setup(c)

        risk = c.post(
            f"/projects/{pid}/risks",
            json={
                "type": "risk",
                "title": "Versioned",
                "probability": 3,
                "impact": 3,
            },
            headers=h,
        ).json()
        assert risk["version"] == 1

        r = c.patch(
            f"/projects/{pid}/risks/{risk['id']}",
            json={"title": "Renamed", "base_version": 999},
            headers=h,
        )
        assert r.status_code == 409, r.text
        detail = r.json()["detail"]
        assert detail["reason"] == "version_mismatch"
        assert detail["server_version"] == 1


def test_owner_user_id_and_owner_unassigned_are_mutually_exclusive(
    tmp_path, isolated_app_factory
):
    """Listing with both owner_user_id and owner_unassigned set returns HTTP 422"""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'edge_owner.db'}")
    with TestClient(app) as c:
        h, pid = _setup(c)

        some_uuid = str(uuid.uuid4())
        r = c.get(
            f"/projects/{pid}/risks",
            params={"owner_user_id": some_uuid, "owner_unassigned": "true"},
            headers=h,
        )
        assert r.status_code == 422, r.text
        assert "owner" in str(r.json()["detail"]).lower()
