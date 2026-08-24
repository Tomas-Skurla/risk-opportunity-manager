"""Refresh token lifecycle: issue, rotate, revoke."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _register(c, email="user@example.com", password="SecurePass123!"):
    r = c.post("/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


def test_refresh_rotates_tokens(tmp_path, isolated_app_factory):
    """Refresh endpoint rotates both access and refresh tokens, revokes the old refresh"""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'ref.db'}")
    with TestClient(app) as c:
        tokens = _register(c)
        assert tokens.get("refresh_token")

        # Rotate: exchange refresh token for a new access + refresh pair
        r = c.post("/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert r.status_code == 200, r.text
        new_tokens = r.json()
        assert new_tokens["access_token"] != tokens["access_token"]
        assert new_tokens["refresh_token"] != tokens["refresh_token"]

        # New access token works
        r = c.get(
            "/users/me",
            headers={"Authorization": f"Bearer {new_tokens['access_token']}"},
        )
        assert r.status_code == 200

        # Old refresh token is revoked (one-time use)
        r = c.post("/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert r.status_code == 401


def test_refresh_with_garbage_token_returns_401(tmp_path, isolated_app_factory):
    """Refresh with an invalid/garbage token returns HTTP 401"""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'ref2.db'}")
    with TestClient(app) as c:
        r = c.post("/refresh", json={"refresh_token": "garbage-token-abc"})
        assert r.status_code == 401
