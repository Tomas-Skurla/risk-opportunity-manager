"""Assessment operations for offline-first mode."""

from __future__ import annotations

import uuid

from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore, utc_iso
from riskapp_client.adapters.local_storage.sync_outbox_queue import OutboxStore
from riskapp_client.domain.domain_models import Assessment


class AssessmentService:
    """Create/update my assessment locally and queue sync."""

    def __init__(self, store: LocalStore, outbox: OutboxStore) -> None:
        self._store = store
        self._outbox = outbox

    def list(self, project_id: str, item_type: str, item_id: str) -> list[Assessment]:
        return self._store.list_assessments(project_id, item_type, item_id)

    def upsert_my(
        self,
        project_id: str,
        item_type: str,
        item_id: str,
        assessor_user_id: str,
        probability: int,
        impact: int,
        notes: str | None = None,
    ) -> Assessment:
        assessment_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"assessment:{item_id}:{assessor_user_id}")
        )
        updated_at = utc_iso()

        version = self._get_version_or_0(assessment_id)

        self._store.upsert_local_assessment(
            assessment_id=assessment_id,
            project_id=project_id,
            item_type=item_type,
            item_id=item_id,
            assessor_user_id=assessor_user_id,
            probability=int(probability),
            impact=int(impact),
            notes=notes or "",
            version=version,
            is_deleted=False,
            updated_at=updated_at,
            dirty=1,
        )
        # IMPORTANT: queue_assessment_upsert accepts keyword arguments only.
        # Also note that the server derives assessor_user_id from the JWT user,
        # so we do not send it as part of the sync record.
        self._outbox.queue_assessment_upsert(
            assessment_id,
            project_id,
            item_id=item_id,
            **(
                {"risk_id": item_id}
                if item_type == "risk"
                else {"opportunity_id": item_id}
            ),
            probability=int(probability),
            impact=int(impact),
            notes=(notes or ""),
        )

        return Assessment(
            id=assessment_id,
            item_id=item_id,
            assessor_user_id=assessor_user_id,
            probability=int(probability),
            impact=int(impact),
            notes=notes or "",
            updated_at=updated_at,
            version=version,
            is_deleted=False,
        )

    def _get_version_or_0(self, assessment_id: str) -> int:
        try:
            _, version = self._store.get_assessment_project_and_version(assessment_id)
            return int(version)
        except (RuntimeError, OSError, KeyError):  # noqa: BLE001
            return 0
