"""Refresh token lifecycle: issue, rotate, revoke."""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select


def _register(c, email="user@example.com", password="SecurePass123!"):
    r = c.post("/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


def _login(c, email="user@example.com", password="SecurePass123!"):
    response = c.post(
        "/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_refresh_recovers_one_lost_response_then_detects_reuse(
    tmp_path, isolated_app_factory
):
    """A recent token gets one recovery; repeated reuse revokes its family."""
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

        # A lost first response can be recovered once with the old token. The
        # unused replacement is revoked and a fresh replacement is returned.
        r = c.post("/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert r.status_code == 200, r.text
        recovered_tokens = r.json()
        assert recovered_tokens["refresh_token"] not in {
            tokens["refresh_token"],
            new_tokens["refresh_token"],
        }

        # Reusing that same ancestor again is no longer a recovery. It is reuse
        # detection, which revokes the active descendant in this family.
        r = c.post("/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert r.status_code == 401
        r = c.post(
            "/refresh", json={"refresh_token": recovered_tokens["refresh_token"]}
        )
        assert r.status_code == 401


def test_reuse_revokes_only_the_connected_login_family(
    tmp_path, isolated_app_factory
):
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'families.db'}")
    with TestClient(app) as c:
        first_login = _register(c)
        separate_login = _login(c)

        first_rotation = c.post(
            "/refresh", json={"refresh_token": first_login["refresh_token"]}
        ).json()
        second_rotation = c.post(
            "/refresh", json={"refresh_token": first_rotation["refresh_token"]}
        ).json()

        # The first token's direct replacement has already been used, so this
        # cannot be a lost-response recovery even though it is recent.
        reused = c.post(
            "/refresh", json={"refresh_token": first_login["refresh_token"]}
        )
        assert reused.status_code == 401
        assert (
            c.post(
                "/refresh",
                json={"refresh_token": second_rotation["refresh_token"]},
            ).status_code
            == 401
        )

        # A separate login is a separate family and remains usable.
        independent = c.post(
            "/refresh", json={"refresh_token": separate_login["refresh_token"]}
        )
        assert independent.status_code == 200, independent.text


def test_reuse_outside_grace_revokes_the_active_replacement(
    tmp_path, isolated_app_factory
):
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'grace.db'}")
    with TestClient(app) as c:
        original = _register(c)
        rotated = c.post(
            "/refresh", json={"refresh_token": original["refresh_token"]}
        ).json()

        # Imports follow isolated_app_factory's module reloads.
        # pylint: disable=import-outside-toplevel
        import riskapp_server.auth.service as auth_service
        import riskapp_server.db.session as session

        with session.SessionLocal() as db:
            stored = db.execute(
                select(session.RefreshToken).where(
                    session.RefreshToken.token_hash
                    == auth_service.hash_bearer_secret(original["refresh_token"])
                )
            ).scalar_one()
            stored.revoked_at = session.utcnow() - timedelta(
                seconds=auth_service.REFRESH_TOKEN_REUSE_GRACE_SECONDS + 1
            )
            db.commit()
        # pylint: enable=import-outside-toplevel

        assert (
            c.post(
                "/refresh", json={"refresh_token": original["refresh_token"]}
            ).status_code
            == 401
        )
        assert (
            c.post(
                "/refresh", json={"refresh_token": rotated["refresh_token"]}
            ).status_code
            == 401
        )


def test_parallel_duplicate_rotation_keeps_one_linear_family(
    tmp_path, isolated_app_factory
):
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'parallel.db'}")
    with TestClient(app) as c:
        original = _register(c)

        # Imports follow isolated_app_factory's module reloads.
        # pylint: disable=import-outside-toplevel
        import riskapp_server.auth.service as auth_service
        import riskapp_server.db.session as session

        barrier = threading.Barrier(2)

        def rotate() -> str:
            with session.SessionLocal() as db:
                barrier.wait()
                return auth_service.rotate_refresh_token(
                    db, original["refresh_token"]
                )[0]

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(rotate) for _ in range(2)]
            replacements = [future.result(timeout=10) for future in futures]

        with session.SessionLocal() as db:
            rows = list(
                db.execute(
                    select(session.RefreshToken)
                    .where(
                        session.RefreshToken.user_id
                        == uuid.UUID(original["user_id"])
                    )
                    .order_by(session.RefreshToken.issued_at)
                ).scalars()
            )
        # pylint: enable=import-outside-toplevel

        assert len(rows) == 3
        assert len({token.token_hash for token in rows}) == 3
        assert len([token for token in rows if token.revoked_at is None]) == 1
        assert len([token for token in rows if token.replaced_by_id is not None]) == 2
        active_hash = next(
            token.token_hash for token in rows if token.revoked_at is None
        )
        assert active_hash in {
            auth_service.hash_bearer_secret(replacement)
            for replacement in replacements
        }


def test_expired_and_inactive_refresh_tokens_are_rejected(
    tmp_path, isolated_app_factory
):
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'invalid.db'}")
    with TestClient(app) as c:
        expired = _register(c, email="expired@example.com")
        inactive = _register(c, email="inactive@example.com")

        # Imports follow isolated_app_factory's module reloads.
        # pylint: disable=import-outside-toplevel
        import riskapp_server.auth.service as auth_service
        import riskapp_server.db.session as session

        with session.SessionLocal() as db:
            expired_row = db.execute(
                select(session.RefreshToken).where(
                    session.RefreshToken.token_hash
                    == auth_service.hash_bearer_secret(expired["refresh_token"])
                )
            ).scalar_one()
            expired_row.expires_at = session.utcnow() - timedelta(seconds=1)
            inactive_user = db.get(session.User, uuid.UUID(inactive["user_id"]))
            assert inactive_user is not None
            inactive_user.is_active = False
            db.commit()
        # pylint: enable=import-outside-toplevel

        assert (
            c.post(
                "/refresh", json={"refresh_token": expired["refresh_token"]}
            ).status_code
            == 401
        )
        assert (
            c.post(
                "/refresh", json={"refresh_token": inactive["refresh_token"]}
            ).status_code
            == 401
        )


def test_refresh_helpers_commit_and_replace_an_existing_transaction(
    tmp_path, isolated_app_factory
):
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'helpers.db'}")
    with TestClient(app) as c:
        account = _register(c, email="helper@example.com")

        # Imports follow isolated_app_factory's module reloads.
        # pylint: disable=import-outside-toplevel,protected-access
        import riskapp_server.auth.service as auth_service
        import riskapp_server.db.session as session

        user_id = uuid.UUID(account["user_id"])
        with session.SessionLocal() as db:
            db.execute(select(session.User.id).where(session.User.id == user_id))
            assert db.in_transaction()
            auth_service._begin_refresh_transaction(db)
            issued = auth_service.issue_refresh_token(db, user_id)
            stored = db.execute(
                select(session.RefreshToken).where(
                    session.RefreshToken.token_hash
                    == auth_service.hash_bearer_secret(issued)
                )
            ).scalar_one_or_none()
            assert stored is not None
        # pylint: enable=import-outside-toplevel,protected-access


def test_broken_replacement_link_fails_closed(tmp_path, isolated_app_factory):
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'broken-link.db'}")
    with TestClient(app) as c:
        account = _register(c, email="broken@example.com")

        # Imports follow isolated_app_factory's module reloads.
        # pylint: disable=import-outside-toplevel,protected-access
        import riskapp_server.auth.service as auth_service
        import riskapp_server.db.session as session

        assert auth_service._refresh_family_ids([], uuid.uuid4()) == set()
        with session.SessionLocal() as db:
            stored = db.execute(
                select(session.RefreshToken).where(
                    session.RefreshToken.token_hash
                    == auth_service.hash_bearer_secret(account["refresh_token"])
                )
            ).scalar_one()
            stored.revoked_at = session.utcnow()
            stored.replaced_by_id = uuid.uuid4()
            db.commit()
        # pylint: enable=import-outside-toplevel,protected-access

        response = c.post(
            "/refresh", json={"refresh_token": account["refresh_token"]}
        )
        assert response.status_code == 401


def test_refresh_with_garbage_token_returns_401(tmp_path, isolated_app_factory):
    """Refresh with an invalid/garbage token returns HTTP 401"""
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'ref2.db'}")
    with TestClient(app) as c:
        r = c.post("/refresh", json={"refresh_token": "garbage-token-abc"})
        assert r.status_code == 401
