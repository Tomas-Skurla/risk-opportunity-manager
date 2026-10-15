"""The backend operations used by one-shot desktop background jobs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from riskapp_client.domain.domain_models import Project


class BackgroundJobBackend(Protocol):
    """Stable job operations; payloads retain the existing JSON-shaped results."""

    def list_projects(self) -> list[Project]: ...

    def list_sync_projects(self) -> list[Project]:
        """Refresh projects for automatic sync without falling back to the cache."""
        ...

    def export_authenticated_remote(self) -> object | None: ...

    def close(self) -> None:
        """Release resources in the thread that created this backend."""
        ...

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
