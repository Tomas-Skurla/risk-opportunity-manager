"""Regression tests for sync batch idempotency and safe failures."""

from __future__ import annotations

import uuid
from typing import cast

import pytest
from fastapi import HTTPException
from riskapp_server.sync import engine
from sqlalchemy.orm import Session
from support import (
    create_project,
    new_change,
    newly_accepted,
    pull,
    push,
    register_user,
    replayed,
    results_with,
)


def test_changed_payload_with_same_id_is_rejected_without_reapplying(api) -> None:
    user = register_user(api)
    project_id = create_project(api, user, name="Batch Sync").id
    change_id = str(uuid.uuid4())
    risk_id = str(uuid.uuid4())
    response = push(
        api,
        project_id,
        user,
        new_change(
            "risk",
            {
                "id": risk_id,
                "title": "First value",
                "probability": 2,
                "impact": 3,
            },
            base_version=0,
            change_id=change_id,
        ),
        new_change(
            "risk",
            {
                "id": risk_id,
                "title": "Must not be applied",
                "probability": 5,
                "impact": 5,
            },
            base_version=0,
            change_id=change_id,
        ),
    )

    assert response.status_code == 200
    assert len(newly_accepted(response.json())) == 1
    assert replayed(response.json()) == []
    assert (
        results_with(response.json(), "error")[0]["reason"]
        == "change_id_payload_mismatch"
    )
    assert response.json()["results"][1]["replayed"] is False

    response = pull(api, project_id, user)
    risk = next(item for item in response.json()["risks"] if item["id"] == risk_id)
    assert risk["title"] == "First value"


def test_commit_failure_rolls_back_without_exposing_database_details(
    monkeypatch,
) -> None:
    class FailingSession:
        rolled_back = False

        def commit(self) -> None:
            raise RuntimeError("database password=interview-secret")

        def rollback(self) -> None:
            self.rolled_back = True

    session = FailingSession()
    monkeypatch.setattr(engine, "ensure_member", lambda *_args: "member")

    with pytest.raises(HTTPException) as caught:
        # The failure-injection double implements only the exercised Session calls.
        engine.push_changes(cast(Session, session), uuid.uuid4(), uuid.uuid4(), [])

    assert caught.value.status_code == 500
    assert caught.value.detail == "Sync push commit failed"
    assert "interview-secret" not in str(caught.value.detail)
    assert session.rolled_back is True
