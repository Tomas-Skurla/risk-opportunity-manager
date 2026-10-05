"""Common API steps that tests would otherwise repeat."""

from __future__ import annotations

import itertools
import uuid
from dataclasses import dataclass, field, replace
from typing import Any

from fastapi.testclient import TestClient

from support.credentials import new_email, new_password

_item_numbers = itertools.count(1)


@dataclass(frozen=True)
class User:
    """A registered, logged-in account.

    Secrets stay out of the printed form, so a failure message never shows them.
    """

    email: str
    id: str
    password: str = field(repr=False)
    token: str = field(repr=False)
    refresh_token: str = field(repr=False)

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


@dataclass(frozen=True)
class Item:
    """A risk or opportunity as the server created it."""

    id: str
    kind: str
    title: str
    version: int
    data: dict[str, Any] = field(repr=False)
    """The full server response, for the fields tests rarely need."""


@dataclass(frozen=True)
class Project:
    """A project and the account that created it."""

    id: str
    owner: User


def register_user(
    client: TestClient, *, email: str | None = None, password: str | None = None
) -> User:
    """Register a regular account; unspecified credentials are generated."""
    email = email or new_email()
    password = password or new_password()
    response = client.post("/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    data = response.json()
    return User(
        email=email,
        id=data["user_id"],
        password=password,
        token=data["access_token"],
        refresh_token=data["refresh_token"],
    )


def log_in(client: TestClient, user: User, *, password: str | None = None) -> User:
    """Log in as ``user``; return it with the tokens of the new session.

    ``password`` replaces ``user.password``, for example after a password change.
    """
    password = password or user.password
    response = client.post(
        "/login", data={"username": user.email, "password": password}
    )
    assert response.status_code == 200, response.text
    data = response.json()
    return replace(
        user,
        password=password,
        token=data["access_token"],
        refresh_token=data["refresh_token"],
    )


def promote_to_superuser(user: User) -> None:
    """Make ``user`` a global superadmin directly in the database."""
    # Imported here so it follows isolated_app_factory's module reloads.
    # pylint: disable-next=import-outside-toplevel
    import riskapp_server.db.session as session

    with session.SessionLocal() as db:
        row = db.get(session.User, uuid.UUID(user.id))
        assert row is not None
        row.is_superuser = True
        db.commit()


def create_project(
    client: TestClient, owner: User, name: str = "Test project"
) -> Project:
    """Create a project; its creator becomes the project's admin."""
    response = client.post("/projects", json={"name": name}, headers=owner.headers)
    assert response.status_code == 201, response.text
    return Project(id=response.json()["id"], owner=owner)


def create_item(
    client: TestClient,
    project: Project,
    actor: User,
    *,
    kind: str,
    title: str | None = None,
    probability: int = 2,
    impact: int = 3,
    **fields: Any,
) -> Item:
    """Create a risk or opportunity as ``actor``.

    Without a ``title``, each item gets a distinct one such as ``Test risk 3``.
    Other item fields, such as ``code`` or ``status``, are sent as given.
    """
    title = title or f"Test {kind} {next(_item_numbers)}"
    collection = {"risk": "risks", "opportunity": "opportunities"}[kind]
    response = client.post(
        f"/projects/{project.id}/{collection}",
        json={
            "type": kind,
            "title": title,
            "probability": probability,
            "impact": impact,
            **fields,
        },
        headers=actor.headers,
    )
    assert response.status_code == 201, response.text
    data = response.json()
    return Item(
        id=data["id"],
        kind=data["type"],
        title=data["title"],
        version=data["version"],
        data=data,
    )


def add_member(client: TestClient, project: Project, user: User, role: str) -> None:
    """Add ``user`` to ``project`` with ``role``, acting as the project's owner."""
    response = client.post(
        f"/projects/{project.id}/members",
        json={"user_email": user.email, "role": role},
        headers=project.owner.headers,
    )
    assert response.status_code == 201, response.text
