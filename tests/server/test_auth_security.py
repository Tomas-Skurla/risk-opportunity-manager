from __future__ import annotations

from fastapi.testclient import TestClient


def test_password_policy_rejects_weak_password(tmp_path, isolated_app_factory) -> None:
    """Password policy rejects weak passwords on register"""
    db_file = tmp_path / "auth_policy.db"
    app = isolated_app_factory(f"sqlite+pysqlite:///{db_file}")
    with TestClient(app) as c:
        r = c.post(
            "/register", json={"email": "x@example.com", "password": "password123"}
        )
        assert r.status_code == 400
        assert "password" in r.json().get("detail", {})


def test_login_rate_limit_kicks_in(tmp_path, isolated_app_factory) -> None:
    """Login rate limit triggers HTTP 429 after configured failed attempts"""
    db_file = tmp_path / "auth_rate.db"
    app = isolated_app_factory(f"sqlite+pysqlite:///{db_file}")
    with TestClient(app) as c:
        r = c.post(
            "/register", json={"email": "u@example.com", "password": "Password123!"}
        )
        assert r.status_code == 201
        for _ in range(2):
            r = c.post(
                "/login",
                data={"username": "u@example.com", "password": "WrongPassword1!"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            assert r.status_code == 401
        r = c.post(
            "/login",
            data={"username": "u@example.com", "password": "WrongPassword1!"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert r.status_code == 429
