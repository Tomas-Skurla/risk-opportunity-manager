"""Assessment upsert: create, update, version check, score recalc."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def _setup(c):
    r = c.post(
        "/register",
        json={"email": "a@test.com", "password": "Password123!"},
    )
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    r = c.post("/projects", json={"name": "P"}, headers=h)
    pid = r.json()["id"]

    r = c.post(
        f"/projects/{pid}/risks",
        json={
            "type": "risk",
            "title": "R1",
            "probability": 4,
            "impact": 3,
        },
        headers=h,
    )
    rid = r.json()["id"]
    return h, pid, rid


def test_create_and_update_assessment(tmp_path, isolated_app_factory):
    """Create then update an assessment, verifying score recalc and version bump"""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'assess.db'}")
    with TestClient(app) as c:
        h, pid, rid = _setup(c)

        # Create assessment
        r = c.put(
            f"/projects/{pid}/risks/{rid}/assessment",
            json={"probability": 5, "impact": 4, "notes": "Very likely"},
            headers=h,
        )
        assert r.status_code == 200
        a = r.json()
        assert a["probability"] == 5
        assert a["impact"] == 4
        assert a["score"] == 20  # 5 * 4
        assert a["version"] == 1

        # Update assessment
        r = c.put(
            f"/projects/{pid}/risks/{rid}/assessment",
            json={"probability": 2, "impact": 1, "notes": "Revised down"},
            headers=h,
        )
        assert r.status_code == 200
        a = r.json()
        assert a["score"] == 2  # 2 * 1
        assert a["version"] == 2


def test_list_assessments(tmp_path, isolated_app_factory):
    """List assessments for a risk returns the assessments created so far"""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'assess2.db'}")
    with TestClient(app) as c:
        h, pid, rid = _setup(c)

        c.put(
            f"/projects/{pid}/risks/{rid}/assessment",
            json={"probability": 3, "impact": 3},
            headers=h,
        )

        r = c.get(f"/projects/{pid}/risks/{rid}/assessments", headers=h)
        assert r.status_code == 200
        assert len(r.json()) == 1


def test_assessment_on_nonexistent_item_returns_404(tmp_path, isolated_app_factory):
    """Assessing a non-existent risk returns HTTP 404"""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'assess3.db'}")
    with TestClient(app) as c:
        h, pid, rid = _setup(c)
        fake_id = str(uuid.uuid4())
        r = c.put(
            f"/projects/{pid}/risks/{fake_id}/assessment",
            json={"probability": 3, "impact": 3},
            headers=h,
        )
        assert r.status_code == 404
