"""The backend operations used by one-shot desktop background jobs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, TypedDict

from riskapp_client.domain.domain_models import Project


class SyncCallbacks(TypedDict, total=False):
    """Cooperative callbacks supported by production synchronization."""

    should_cancel: Callable[[], bool]
    progress: Callable[[str], None]


class BackgroundJobBackend(Protocol):
    """Stable job operations; payloads retain the existing JSON-shaped results."""

    def list_projects(self) -> list[Project]: ...

    def sync_project(
        self,
        project_id: str,
        *,
        should_cancel: Callable[[], bool] | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, Any]: ...

    def create_snapshot(
        self, project_id: str, *, kind: str | None = None
    ) -> dict[str, Any]: ...

    def top_history(
        self,
        project_id: str,
        *,
        kind: str = "risks",
        limit: int = 10,
        from_ts: str | None = None,
        to_ts: str | None = None,
    ) -> list[dict[str, Any]]: ...


BackendFactory = Callable[[], BackgroundJobBackend]
