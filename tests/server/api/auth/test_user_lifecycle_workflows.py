"""Account lifecycle workflows and invalidation boundaries."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from support import log_in, new_password, promote_to_superuser, register_user

# Database and router imports follow isolated_app_factory's module reloads.
# pylint: disable=import-outside-toplevel


def test_change_password_rejects_wrong_and_weak_credentials_before_success(
    api,
) -> None:
    user = register_user(api)
    me = api.get("/users/me", headers=user.headers)
    assert me.status_code == 200
    assert me.json()["id"] == user.id

    wrong = api.post(
        "/users/me/change-password",
        json={"old_password": "WrongPassword123!", "new_password": new_password()},
        headers=user.headers,
    )
    assert wrong.status_code == 401
    weak = api.post(
        "/users/me/change-password",
        json={"old_password": user.password, "new_password": "weakpassword"},
        headers=user.headers,
    )
    assert weak.status_code == 400

    changed_password = new_password()
    changed = api.post(
        "/users/me/change-password",
        json={"old_password": user.password, "new_password": changed_password},
        headers=user.headers,
    )
    assert changed.status_code == 204
    old_login = api.post(
        "/login", data={"username": user.email, "password": user.password}
    )
    assert old_login.status_code == 401
    log_in(api, user, password=changed_password)


def test_superuser_account_controls_and_reset_token_invalidation(
    tmp_path, isolated_app_factory
) -> None:
    app = isolated_app_factory(
        f"sqlite+pysqlite:///{tmp_path / 'account-admin.db'}",
        return_reset_token=True,
    )
    with TestClient(app) as client:
        import riskapp_server.api.routers.users as users_router

        # Configure the internal reset limiter for this boundary test.
        # pylint: disable-next=protected-access
        users_router._reset_limiter.limit = 2
        # pylint: disable-next=protected-access
        users_router._reset_limiter.reset()
        actor = register_user(client)
        target = register_user(client)

        forbidden = client.post(
            f"/admin/users/{target.id}/deactivate", headers=actor.headers
        )
        assert forbidden.status_code == 403
        promote_to_superuser(actor)

        missing_id = uuid.uuid4()
        assert (
            client.post(
                f"/admin/users/{missing_id}/deactivate", headers=actor.headers
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/admin/users/{missing_id}/activate", headers=actor.headers
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/admin/users/{missing_id}/set-password",
                json={"new_password": new_password()},
                headers=actor.headers,
            ).status_code
            == 404
        )

        first = client.post("/password-reset/request", json={"email": target.email})
        second = client.post("/password-reset/request", json={"email": target.email})
        assert first.status_code == second.status_code == 200
        first_token = first.json()["token"]
        second_token = second.json()["token"]
        limited = client.post("/password-reset/request", json={"email": target.email})
        assert limited.status_code == 429
        assert int(limited.headers["Retry-After"]) >= 1

        invalidated = client.post(
            "/password-reset/confirm",
            json={"token": first_token, "new_password": new_password()},
        )
        assert invalidated.status_code == 400

        deactivated = client.post(
            f"/admin/users/{target.id}/deactivate", headers=actor.headers
        )
        assert deactivated.status_code == 204
        inactive_reset = client.post(
            "/password-reset/confirm",
            json={"token": second_token, "new_password": new_password()},
        )
        assert inactive_reset.status_code == 400
        assert inactive_reset.json()["detail"] == "Account is inactive"
        old_login = client.post(
            "/login", data={"username": target.email, "password": target.password}
        )
        assert old_login.status_code == 401

        activated = client.post(
            f"/admin/users/{target.id}/activate", headers=actor.headers
        )
        assert activated.status_code == 204
        weak = client.post(
            f"/admin/users/{target.id}/set-password",
            json={"new_password": "weakpassword"},
            headers=actor.headers,
        )
        assert weak.status_code == 400
        admin_password = new_password()
        changed = client.post(
            f"/admin/users/{target.id}/set-password",
            json={"new_password": admin_password},
            headers=actor.headers,
        )
        assert changed.status_code == 204
        log_in(client, target, password=admin_password)
