"""Password reset: request → confirm → login with new password."""

from __future__ import annotations

from fastapi.testclient import TestClient
from support import log_in, new_password, register_user


def test_full_password_reset_flow(tmp_path, isolated_app_factory):
    """Full password reset flow: request token, confirm, login with new, reject old"""
    app = isolated_app_factory(
        f"sqlite+pysqlite:///{tmp_path / 'reset.db'}", return_reset_token=True
    )
    with TestClient(app) as c:
        user = register_user(c)

        # Request password reset
        r = c.post("/password-reset/request", json={"email": user.email})
        assert r.status_code == 200
        token = r.json().get("token")
        assert token, "Reset token should be returned in dev mode"

        # Confirm reset with new password
        changed = new_password()
        r = c.post(
            "/password-reset/confirm",
            json={"token": token, "new_password": changed},
        )
        assert r.status_code == 204

        # Login with new password works
        log_in(c, user, password=changed)

        # Login with old password fails
        r = c.post("/login", data={"username": user.email, "password": user.password})
        assert r.status_code == 401


def test_reset_token_cannot_be_reused(tmp_path, isolated_app_factory):
    """Password reset token is single-use and the second confirm returns HTTP 400"""
    app = isolated_app_factory(
        f"sqlite+pysqlite:///{tmp_path / 'reset2.db'}", return_reset_token=True
    )
    with TestClient(app) as c:
        user = register_user(c)
        r = c.post("/password-reset/request", json={"email": user.email})
        token = r.json()["token"]

        # First use succeeds
        r = c.post(
            "/password-reset/confirm",
            json={"token": token, "new_password": new_password()},
        )
        assert r.status_code == 204

        # Second use fails (token is consumed)
        r = c.post(
            "/password-reset/confirm",
            json={"token": token, "new_password": new_password()},
        )
        assert r.status_code == 400


def test_reset_for_nonexistent_email_doesnt_reveal_existence(api):
    """Reset request for unknown email returns generic 200 without leaking existence"""
    r = api.post("/password-reset/request", json={"email": "nobody@example.com"})
    # Should return 200 with a generic message, not 404
    assert r.status_code == 200
    assert "token" not in r.json()  # no token for nonexistent user
