"""Local SQLite copy of the user's projects, plus the server state it was synced to."""

from __future__ import annotations

from riskapp_client.adapters.local_storage.entity_store import EntityStoreMixin
from riskapp_client.adapters.local_storage.project_store import ProjectStoreMixin
from riskapp_client.adapters.local_storage.server_state import ServerStateMixin
from riskapp_client.adapters.local_storage.sqlite_base import utc_iso

__all__ = ["LocalStore", "utc_iso"]


class LocalStore(ServerStateMixin, EntityStoreMixin, ProjectStoreMixin):
    """One SQLite database for the offline-first client.
    - ``ProjectStoreMixin``: projects and key/value metadata
    - ``EntityStoreMixin``: local edits to project items
    - ``ServerStateMixin``: pulled server rows, push acknowledgements, watermarks
    """
