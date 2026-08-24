"""Password reset: request → confirm → login with new password."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_full_password_reset_flow(tmp_path, isolated_app_factory):
    """Full password reset flow: request token, confirm, login with new, reject old"""
    app = isolated_app_factory(
        f"sqlite+pysqlite:///{tmp_path / 'reset.db'}", return_reset_token=True
    )
    with TestClient(app) as c:
        # Register
        r = c.post(
            "/register",
            json={"email": "reset@example.com", "password": "OldPassword123!"},
        )
        assert r.status_code == 201

        # Request password reset
        r = c.post("/password-reset/request", json={"email": "reset@example.com"})
        assert r.status_code == 200
        token = r.json().get("token")
        assert token, "Reset token should be returned in dev mode"

        # Confirm reset with new password
        r = c.post(
            "/password-reset/confirm",
            json={"token": token, "new_password": "NewPassword456!"},
        )
        assert r.status_code == 204

        # Login with new password works
        r = c.post(
            "/login",
            data={"username": "reset@example.com", "password": "NewPassword456!"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert r.status_code == 200

        # Login with old password fails
        r = c.post(
            "/login",
            data={"username": "reset@example.com", "password": "OldPassword123!"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert r.status_code == 401


def test_reset_token_cannot_be_reused(tmp_path, isolated_app_factory):
    """Password reset token is single-use and the second confirm returns HTTP 400"""
    app = isolated_app_factory(
        f"sqlite+pysqlite:///{tmp_path / 'reset2.db'}", return_reset_token=True
    )
    with TestClient(app) as c:
        c.post(
            "/register",
            json={"email": "x@example.com", "password": "Password123!"},
        )
        r = c.post("/password-reset/request", json={"email": "x@example.com"})
        token = r.json()["token"]

        # First use succeeds
        r = c.post(
            "/password-reset/confirm",
            json={"token": token, "new_password": "Changed1234!"},
        )
        assert r.status_code == 204

        # Second use fails (token is consumed)
        r = c.post(
            "/password-reset/confirm",
            json={"token": token, "new_password": "Again123456!"},
        )
        assert r.status_code == 400


def test_reset_for_nonexistent_email_doesnt_reveal_existence(
    tmp_path, isolated_app_factory
):
    """Reset request for unknown email returns generic 200 without leaking existence"""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'reset3.db'}")
    with TestClient(app) as c:
        r = c.post("/password-reset/request", json={"email": "nobody@example.com"})
        # Should return 200 with a generic message, not 404
        assert r.status_code == 200
        assert "token" not in r.json()  # no token for nonexistent user
