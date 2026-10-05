"""Sync helpers: build changes, push and pull them, and read the results."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient

from support.api import User


def new_change(
    entity: str,
    record: dict[str, Any],
    *,
    base_version: int | None = None,
    op: str = "upsert",
    change_id: str | None = None,
) -> dict[str, Any]:
    """A new sync change; it gets a fresh ``change_id`` unless one is given."""
    return {
        "change_id": change_id or str(uuid.uuid4()),
        "entity": entity,
        "op": op,
        "base_version": base_version,
        "record": record,
    }


def push(client: TestClient, project_id: str, user: User, *changes: dict[str, Any]):
    """Push ``changes`` to ``project_id`` as ``user``; return the response."""
    return client.post(
        f"/projects/{project_id}/sync/push",
        json={"project_id": project_id, "changes": list(changes)},
        headers=user.headers,
    )


def pull(
    client: TestClient,
    project_id: str,
    user: User,
    *,
    since_sequence: int = 0,
    **pagination: Any,
):
    """Pull ``project_id`` as ``user``; ``pagination`` is passed on as given."""
    return client.post(
        f"/projects/{project_id}/sync/pull",
        json={"project_id": project_id, "since_sequence": since_sequence, **pagination},
        headers=user.headers,
    )


def results_with(body: dict[str, Any], status: str) -> list[dict[str, Any]]:
    """The per-change results with ``status``: accepted, conflict or error."""
    return [result for result in body["results"] if result["status"] == status]


def newly_accepted(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Accepted changes applied by this push, not replays of earlier ones."""
    return [
        result for result in results_with(body, "accepted") if not result["replayed"]
    ]


def replayed(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Results answered from an earlier receipt instead of being applied again."""
    return [result for result in body["results"] if result["replayed"]]
