from __future__ import annotations

import base64
import hashlib

from fastapi.testclient import TestClient
from sqlalchemy import select

# Server imports follow isolated_app_factory's environment and module reloads.
# pylint: disable=import-outside-toplevel


def _legacy_pbkdf2_hash(password: str, *, iterations: int = 100_000) -> str:
    salt = b"legacy-test-salt"
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt, iterations
    )
    return (
        f"pbkdf2_sha256${iterations}$"
        f"{base64.b64encode(salt).decode()}$"
        f"{base64.b64encode(digest).decode()}"
    )


def test_bearer_hash_uses_token_hash_key_not_jwt_secret(
    monkeypatch, tmp_path, isolated_app_factory
) -> None:
    isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'hash-key.db'}")
    import riskapp_server.auth.service as auth_service

    monkeypatch.setattr(auth_service, "TOKEN_HASH_KEY", "token-hash-key-a")
    monkeypatch.setattr(auth_service, "SECRET_KEY", "jwt-signing-key-a")
    first = auth_service.hash_bearer_secret("opaque-token")

    monkeypatch.setattr(auth_service, "SECRET_KEY", "jwt-signing-key-b")
    assert auth_service.hash_bearer_secret("opaque-token") == first

    monkeypatch.setattr(auth_service, "TOKEN_HASH_KEY", "token-hash-key-b")
    assert auth_service.hash_bearer_secret("opaque-token") != first


def test_new_password_hashes_use_argon2id(
    tmp_path, isolated_app_factory
) -> None:
    isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'argon2.db'}")
    import riskapp_server.auth.service as auth_service

    stored_hash = auth_service.hash_pw("Password123!")

    assert stored_hash.startswith("$argon2id$")
    assert auth_service.verify_pw("Password123!", stored_hash) is True
    assert auth_service.verify_pw("WrongPassword123!", stored_hash) is False
    assert auth_service.password_needs_rehash(stored_hash) is False


def test_successful_login_lazily_upgrades_legacy_pbkdf2_hash(
    tmp_path, isolated_app_factory
) -> None:
    db_file = tmp_path / "legacy-password.db"
    app = isolated_app_factory(f"sqlite+pysqlite:///{db_file}")
    import riskapp_server.db.session as session

    password = "Password123!"
    legacy_hash = _legacy_pbkdf2_hash(password)

    with TestClient(app) as client:
        response = client.post(
            "/register",
            json={"email": "legacy@example.com", "password": password},
        )
        assert response.status_code == 201, response.text

        with session.SessionLocal() as db:
            user = db.execute(
                select(session.User).where(session.User.email == "legacy@example.com")
            ).scalar_one()
            user.password_hash = legacy_hash
            db.commit()

        response = client.post(
            "/login",
            data={"username": "legacy@example.com", "password": "WrongPassword1!"},
        )
        assert response.status_code == 401
        with session.SessionLocal() as db:
            user = db.execute(
                select(session.User).where(session.User.email == "legacy@example.com")
            ).scalar_one()
            assert user.password_hash == legacy_hash

        response = client.post(
            "/login",
            data={"username": "legacy@example.com", "password": password},
        )
        assert response.status_code == 200, response.text

        with session.SessionLocal() as db:
            user = db.execute(
                select(session.User).where(session.User.email == "legacy@example.com")
            ).scalar_one()
            assert user.password_hash.startswith("$argon2id$")
            assert user.password_hash != legacy_hash


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


def test_login_ip_limit_bounds_email_identity_churn(
    tmp_path, isolated_app_factory
) -> None:
    """Changing the email cannot bypass the client-IP login ceiling."""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'auth_ip_rate.db'}")
    # Import after app construction so this is the reloaded router instance.
    # pylint: disable-next=import-outside-toplevel
    from riskapp_server.api.routers import auth_routes

    auth_routes._login_ip_limiter.limit = 2  # pylint: disable=protected-access
    auth_routes._login_ip_limiter.reset()  # pylint: disable=protected-access
    with TestClient(app) as client:
        for index in range(2):
            response = client.post(
                "/login",
                data={
                    "username": f"unknown-{index}@example.com",
                    "password": "WrongPassword1!",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            assert response.status_code == 401

        blocked = client.post(
            "/login",
            data={
                "username": "another-new-user@example.com",
                "password": "WrongPassword1!",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) >= 1
