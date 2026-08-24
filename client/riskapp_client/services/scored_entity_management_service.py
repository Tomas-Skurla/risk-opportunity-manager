"""Shared write logic for risks and opportunities."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any, TypeVar

from riskapp_client.adapters.local_storage.sqlite_data_store import utc_iso
from riskapp_client.domain.scored_entity_fields import (
    DEFAULT_STATUS,
    SCORED_ENTITY_META_KEYS,
)

ModelT = TypeVar("ModelT")


@dataclass(frozen=True)
class ScoredEntityWiring:
    """Bind entity-specific store/outbox callables."""

    kind: str  # "risk" | "opportunity"
    id_kw: str  # "risk_id" | "opportunity_id"

    model_cls: type[ModelT]

    list_fn: Callable[[str], list[ModelT]]
    get_project_and_version_fn: Callable[[str], tuple[str, int]]
    get_row_fn: Callable[[str], Mapping[str, Any] | None]

    upsert_local_fn: Callable[..., None]

    queue_upsert_fn: Callable[[str, dict[str, Any]], None]
    queue_delete_fn: Callable[[str, str], None]
    discard_pending_changes_fn: Callable[[str, str], None]

    soft_delete_local_fn: Callable[[str], tuple[str, int]]

    next_code_fn: Callable[[str], str] | None = None


class ScoredEntityService:
    """Create/update scored entities locally and queue sync."""

    def __init__(self, wiring: ScoredEntityWiring) -> None:
        self._w = wiring

    def list(self, project_id: str) -> list[ModelT]:
        return self._w.list_fn(project_id)

    def create(
        self,
        project_id: str,
        *,
        title: str,
        probability: int,
        impact: int,
        meta: Mapping[str, Any],
    ) -> ModelT:
        entity_id = str(uuid.uuid4())
        now = utc_iso()

        record: dict[str, Any] = {
            "id": entity_id,
            "title": title,
            "probability": int(probability),
            "impact": int(impact),
            "status": (meta.get("status") or DEFAULT_STATUS),
            "identified_at": meta.get("identified_at") or now,
            "status_changed_at": meta.get("status_changed_at") or now,
        }

        # Copy only explicitly provided meta keys on create (keeps outbox smaller).
        for key in SCORED_ENTITY_META_KEYS:
            if key in record:
                continue
            if key in meta and meta.get(key) is not None:
                record[key] = meta.get(key)

        record["code"] = self._ensure_code(
            project_id, record.get("code"), existing=None
        )

        self._upsert_local(
            project_id=project_id, entity_id=entity_id, record=record, version=0
        )
        self._w.queue_upsert_fn(project_id, record)
        return self._w.model_cls(project_id=project_id, version=0, **record)

    def update(
        self,
        entity_id: str,
        *,
        title: str,
        probability: int,
        impact: int,
        meta: Mapping[str, Any],
    ) -> ModelT:
        """Update item."""
        project_id, version = self._w.get_project_and_version_fn(entity_id)
        now = utc_iso()

        existing = self._w.get_row_fn(entity_id)

        def _existing(key: str) -> Any:
            """Read a key from an optional sqlite row or mapping.

            LocalStore implementations commonly return sqlite3.Row (index-only) while
            tests/mocks may return a dict-like mapping.
            """

            if not existing:
                return None
            try:
                return existing[key]  # sqlite3.Row
            except (RuntimeError, ValueError, KeyError):
                # Mapping[str, Any]
                return existing.get(key)  # type: ignore[return-value]

        prev_status = _existing("status") or DEFAULT_STATUS
        new_status = meta.get("status") if "status" in meta else prev_status

        status_changed_at = meta.get("status_changed_at")
        if new_status != prev_status and not status_changed_at:
            status_changed_at = now

        record: dict[str, Any] = {
            "id": entity_id,
            "title": title,
            "probability": int(probability),
            "impact": int(impact),
            "status": new_status,
            "status_changed_at": (
                status_changed_at
                if status_changed_at is not None
                else _existing("status_changed_at")
            ),
        }

        for key in SCORED_ENTITY_META_KEYS:
            if key in ("status", "status_changed_at"):
                continue
            if key in meta:
                record[key] = meta.get(key)
            else:
                record[key] = _existing(key)

        record["code"] = self._ensure_code(
            project_id, record.get("code"), existing=_existing("code")
        )

        self._upsert_local(
            project_id=project_id, entity_id=entity_id, record=record, version=version
        )
        self._w.queue_upsert_fn(project_id, record)
        return self._w.model_cls(project_id=project_id, version=version, **record)

    def delete(self, entity_id: str) -> None:
        """Delete item."""
        project_id, version = self._w.soft_delete_local_fn(entity_id)

        # Entity was never synced to the server. Remote net effect should be
        # no-op, so remove any queued local upsert/delete instead of sending a
        # delete for an unknown remote entity.
        if int(version) < 1:
            self._w.discard_pending_changes_fn(project_id, entity_id)
            return

        self._w.queue_delete_fn(project_id, entity_id)

    def _ensure_code(self, project_id: str, code: Any, *, existing: Any) -> str | None:
        c = None
        if isinstance(code, str):
            c = code.strip() or None
        elif code is not None:
            c = str(code).strip() or None

        if not c:
            if isinstance(existing, str) and existing.strip():
                return existing.strip()
            if self._w.next_code_fn is not None:
                try:
                    return self._w.next_code_fn(project_id)
                except (AttributeError, RuntimeError):
                    logging.getLogger(__name__).debug(
                        "Auto-code generation failed", exc_info=True
                    )
                    return None
        return c

    def _upsert_local(
        self,
        *,
        project_id: str,
        entity_id: str,
        record: Mapping[str, Any],
        version: int,
    ) -> None:
        kwargs: MutableMapping[str, Any] = {
            self._w.id_kw: entity_id,
            "project_id": project_id,
            "title": str(record.get("title") or ""),
            "probability": int(record.get("probability") or 1),
            "impact": int(record.get("impact") or 1),
            "version": int(version),
            "is_deleted": False,
            "updated_at": utc_iso(),
            "dirty": 1,
        }

        for k in SCORED_ENTITY_META_KEYS:
            kwargs[k] = record.get(k)

        self._w.upsert_local_fn(**kwargs)
