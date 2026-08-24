"""Member management helpers."""

from __future__ import annotations

from typing import Any

from riskapp_client.domain.domain_models import Member


class MembersService:
    """Thin wrapper around remote member operations."""

    def __init__(self, remote: Any | None) -> None:
        self._remote = remote

    def list(self, project_id: str) -> list[Member]:
        if not self._remote:
            return []
        return self._remote.list_members(project_id)

    def add(self, project_id: str, *, user_email: str, role: str) -> None:
        """Add a member."""
        if not self._remote:
            raise RuntimeError("Members/roles management requires online mode.")
        self._remote.add_member(project_id, user_email=user_email, role=role)

    def remove(self, project_id: str, *, member_user_id: str) -> None:
        """Remove a member."""
        if not self._remote:
            raise RuntimeError("Members/roles management requires online mode.")
        self._remote.remove_member(project_id, member_user_id=member_user_id)
