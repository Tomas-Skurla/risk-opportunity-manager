from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from support import new_email, new_password, register_user

# Server imports follow isolated_app_factory's environment and module reloads.
# pylint: disable=import-outside-toplevel


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


def test_new_password_hashes_use_argon2id(tmp_path, isolated_app_factory) -> None:
    isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'argon2.db'}")
    from riskapp_server.auth import passwords

    password = new_password()
    stored_hash = passwords.hash_pw(password)

    assert stored_hash.startswith("$argon2id$")
    assert passwords.verify_pw(password, stored_hash) is True
    assert passwords.verify_pw(new_password(), stored_hash) is False
    assert passwords.password_needs_rehash(stored_hash) is False
    # Anything that is not an Argon2 hash is rejected, never interpreted.
    old_format = "pbkdf2_sha256$1$c2FsdA==$aGFzaA=="
    assert passwords.verify_pw(password, old_format) is False
    assert passwords.password_needs_rehash("not-a-hash") is False


def test_successful_login_upgrades_outdated_argon2_hash(
    tmp_path, isolated_app_factory
) -> None:
    from argon2 import PasswordHasher

    db_file = tmp_path / "outdated-hash.db"
    app = isolated_app_factory(f"sqlite+pysqlite:///{db_file}")
    import riskapp_server.db.session as session

    with TestClient(app) as client:
        user = register_user(client)
        outdated_hash = PasswordHasher(time_cost=1, memory_cost=8 * 1024).hash(
            user.password
        )

        def stored_hash() -> str:
            with session.SessionLocal() as db:
                return db.execute(
                    select(session.User.password_hash).where(
                        session.User.email == user.email
                    )
                ).scalar_one()

        with session.SessionLocal() as db:
            row = db.execute(
                select(session.User).where(session.User.email == user.email)
            ).scalar_one()
            row.password_hash = outdated_hash
            db.commit()

        response = client.post(
            "/login",
            data={"username": user.email, "password": "WrongPassword1!"},
        )
        assert response.status_code == 401
        assert stored_hash() == outdated_hash

        response = client.post(
            "/login",
            data={"username": user.email, "password": user.password},
        )
        assert response.status_code == 200, response.text
        assert stored_hash() != outdated_hash
        assert stored_hash().startswith("$argon2id$v=19$m=19456,t=2,p=1$")


def test_password_policy_rejects_weak_password(api) -> None:
    """Password policy rejects weak passwords on register"""
    r = api.post("/register", json={"email": new_email(), "password": "password123"})
    assert r.status_code == 400
    assert "password" in r.json().get("detail", {})


def test_login_rate_limit_kicks_in(api) -> None:
    """Login rate limit triggers HTTP 429 after configured failed attempts"""
    user = register_user(api)
    for _ in range(2):
        r = api.post(
            "/login", data={"username": user.email, "password": "WrongPassword1!"}
        )
        assert r.status_code == 401
    r = api.post("/login", data={"username": user.email, "password": "WrongPassword1!"})
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
