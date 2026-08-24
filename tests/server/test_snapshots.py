"""Snapshot router: create, latest, top."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _setup(c: TestClient):
    r = c.post(
        "/register",
        json={"email": "snap@test.com", "password": "Password123!"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    r = c.post("/projects", json={"name": "Snap Project"}, headers=h)
    assert r.status_code == 201, r.text
    return h, r.json()["id"]


def _create_risk(c, h, pid, *, title, probability, impact):
    r = c.post(
        f"/projects/{pid}/risks",
        json={
            "type": "risk",
            "title": title,
            "probability": probability,
            "impact": impact,
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_create_snapshot_and_fetch_top_history(tmp_path, isolated_app_factory):
    """Snapshot create returns counts and the top endpoint orders items by score desc"""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'snap.db'}")
    with TestClient(app) as c:
        h, pid = _setup(c)

        # Three risks with distinct scores so ordering is unambiguous.
        _create_risk(c, h, pid, title="Low", probability=1, impact=2)  # score 2
        _create_risk(c, h, pid, title="Mid", probability=3, impact=4)  # score 12
        _create_risk(c, h, pid, title="Critical", probability=5, impact=5)  # score 25

        r = c.post(
            f"/projects/{pid}/snapshots?kind=risks",
            headers=h,
        )
        assert r.status_code == 201, r.text
        snap = r.json()
        batch_id = snap["batch_id"]
        assert snap["risks"] == 3
        assert snap["opportunities"] == 0

        r = c.get(f"/projects/{pid}/snapshots/latest?kind=risks", headers=h)
        assert r.status_code == 200, r.text
        latest = r.json()
        assert latest["batch_id"] == batch_id
        assert latest["kind"] == "risk"
        assert latest["count"] == 3

        r = c.get(
            f"/projects/{pid}/snapshots/{batch_id}/top?kind=risk&limit=2",
            headers=h,
        )
        assert r.status_code == 200, r.text
        top = r.json()["top"]
        assert [t["title"] for t in top] == ["Critical", "Mid"]
        assert top[0]["score"] == 25
        assert top[1]["score"] == 12

        r = c.get(f"/projects/{pid}/snapshots/latest?kind=bogus", headers=h)
        assert r.status_code == 400
