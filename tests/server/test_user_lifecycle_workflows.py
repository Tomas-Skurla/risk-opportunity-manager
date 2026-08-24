"""Account lifecycle workflows and invalidation boundaries."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def _register(client: TestClient, email: str, password: str = "Password123!"):
    response = client.post("/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    data = response.json()
    return data, {"Authorization": f"Bearer {data['access_token']}"}


def _promote_to_superuser(user_id: str) -> None:
    import riskapp_server.db.session as session
    from riskapp_server.db.session import User
    from sqlalchemy.orm import Session

    with Session(session.engine) as db:
        user = db.get(User, uuid.UUID(user_id))
        assert user is not None
        user.is_superuser = True
        db.add(user)
        db.commit()


def _login(client: TestClient, email: str, password: str):
    return client.post(
        "/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


def test_change_password_rejects_wrong_and_weak_credentials_before_success(
    tmp_path, isolated_app_factory
) -> None:
    app = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'change-password.db'}")
    with TestClient(app) as client:
        account, headers = _register(client, "change@example.com")
        me = client.get("/users/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["id"] == account["user_id"]

        wrong = client.post(
            "/users/me/change-password",
            json={"old_password": "WrongPassword123!", "new_password": "NewPass123!"},
            headers=headers,
        )
        assert wrong.status_code == 401
        weak = client.post(
            "/users/me/change-password",
            json={"old_password": "Password123!", "new_password": "weakpassword"},
            headers=headers,
        )
        assert weak.status_code == 400

        changed = client.post(
            "/users/me/change-password",
            json={
                "old_password": "Password123!",
                "new_password": "NewPassword456!",
            },
            headers=headers,
        )
        assert changed.status_code == 204
        assert _login(client, "change@example.com", "Password123!").status_code == 401
        assert (
            _login(client, "change@example.com", "NewPassword456!").status_code
            == 200
        )


def test_superuser_account_controls_and_reset_token_invalidation(
    tmp_path, isolated_app_factory
) -> None:
    app = isolated_app_factory(
        f"sqlite+pysqlite:///{tmp_path / 'account-admin.db'}",
        return_reset_token=True,
    )
    with TestClient(app) as client:
        import riskapp_server.api.routers.users as users_router

        users_router._reset_limiter.limit = 2
        users_router._reset_limiter.reset()
        actor, actor_headers = _register(client, "actor@example.com")
        target, _ = _register(client, "target@example.com")
        target_id = target["user_id"]

        forbidden = client.post(
            f"/admin/users/{target_id}/deactivate", headers=actor_headers
        )
        assert forbidden.status_code == 403
        _promote_to_superuser(actor["user_id"])

        missing_id = uuid.uuid4()
        assert (
            client.post(
                f"/admin/users/{missing_id}/deactivate", headers=actor_headers
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/admin/users/{missing_id}/activate", headers=actor_headers
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/admin/users/{missing_id}/set-password",
                json={"new_password": "AnotherPassword123!"},
                headers=actor_headers,
            ).status_code
            == 404
        )

        first = client.post(
            "/password-reset/request", json={"email": "target@example.com"}
        )
        second = client.post(
            "/password-reset/request", json={"email": "target@example.com"}
        )
        assert first.status_code == second.status_code == 200
        first_token = first.json()["token"]
        second_token = second.json()["token"]
        limited = client.post(
            "/password-reset/request", json={"email": "target@example.com"}
        )
        assert limited.status_code == 429
        assert int(limited.headers["Retry-After"]) >= 1

        invalidated = client.post(
            "/password-reset/confirm",
            json={"token": first_token, "new_password": "ResetPassword123!"},
        )
        assert invalidated.status_code == 400

        deactivated = client.post(
            f"/admin/users/{target_id}/deactivate", headers=actor_headers
        )
        assert deactivated.status_code == 204
        inactive_reset = client.post(
            "/password-reset/confirm",
            json={"token": second_token, "new_password": "ResetPassword123!"},
        )
        assert inactive_reset.status_code == 400
        assert inactive_reset.json()["detail"] == "Account is inactive"
        assert _login(client, "target@example.com", "Password123!").status_code == 401

        activated = client.post(
            f"/admin/users/{target_id}/activate", headers=actor_headers
        )
        assert activated.status_code == 204
        weak = client.post(
            f"/admin/users/{target_id}/set-password",
            json={"new_password": "weakpassword"},
            headers=actor_headers,
        )
        assert weak.status_code == 400
        changed = client.post(
            f"/admin/users/{target_id}/set-password",
            json={"new_password": "AdminChanged123!"},
            headers=actor_headers,
        )
        assert changed.status_code == 204
        assert (
            _login(client, "target@example.com", "AdminChanged123!").status_code
            == 200
        )
