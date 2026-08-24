"""MainWindow mixin for the Assessments tab."""

from __future__ import annotations

import logging
from typing import Any

from riskapp_client.domain.domain_models import Assessment


class AssessmentsMixin:
    """MainWindow mixin: AssessmentsMixin"""

    def _sync_assessment_state(
        self, entity_type: str, entity_id: str, tab: Any
    ) -> None:
        """Synchronize global assessment state and UI toggles."""
        self.current_assessment_item_type = entity_type
        self.current_assessment_item_id = entity_id
        if tab:
            tab.delete_btn.setVisible(bool(entity_id))
        self._refresh_assessments()

    def _reset_assessment_form(self) -> None:
        self.assessments_tab.assess_p.setValue(3)
        self.assessments_tab.assess_i.setValue(3)
        self.assessments_tab.assess_notes.setText("")

    def _refresh_assessments(self) -> None:
        tab = self.assessments_tab
        pid = self.current_project_id
        item_id = getattr(self, "current_assessment_item_id", None)
        item_type = getattr(self, "current_assessment_item_type", "risk")
        # Update the header label when we can resolve the title.
        try:
            title = ""
            if item_id and item_type == "risk":
                title = (getattr(self, "_risk_title_by_id", {}) or {}).get(item_id, "")
            elif item_id and item_type == "opportunity":
                title = (getattr(self, "_opp_title_by_id", {}) or {}).get(item_id, "")
            nice = "Risk" if item_type == "risk" else "Opportunity"
            tab.target_label.setText(
                f"Target: {nice}{(' · ' + title) if title else ''}"
                if item_id
                else "Target: (none)"
            )
        except (AttributeError, RuntimeError):
            logging.getLogger(__name__).debug("Failed to refresh assessments header", exc_info=True)
        tab.assessments_table.setRowCount(0)
        if not pid or not item_id:
            self._reset_assessment_form()
            return
        assessments = self._call_backend(
            "Backend error", self.backend.list_assessments, pid, item_type, item_id
        )
        if assessments is None:
            return
        my_uid = None
        if hasattr(self.backend, "current_user_id"):
            try:
                my_uid = self.backend.current_user_id()  # type: ignore[attr-defined]
            except (AttributeError, RuntimeError):
                my_uid = None
        my_row: Assessment | None = None
        # Build uid→email lookup from cached members.
        email_by_uid: dict[str, str] = {}
        for m in getattr(self, "_cached_members", []):
            email_by_uid[str(m.user_id)] = m.email
        for a in assessments:
            row = tab.assessments_table.rowCount()
            tab.assessments_table.insertRow(row)
            assessor = a.assessor_user_id or ""
            assessor_display = email_by_uid.get(assessor, assessor[:8] if assessor else "")
            tab.assessments_table.setItem(row, 0, self._mk_item(assessor_display))
            tab.assessments_table.setItem(
                row, 1, self._mk_item(str(a.probability), align_center=True)
            )
            tab.assessments_table.setItem(
                row, 2, self._mk_item(str(a.impact), align_center=True)
            )
            tab.assessments_table.setItem(
                row, 3, self._mk_item(str(a.score), align_center=True)
            )
            tab.assessments_table.setItem(row, 4, self._mk_item(a.notes or ""))
            tab.assessments_table.setItem(row, 5, self._mk_item(a.updated_at or ""))
            if my_uid and assessor == my_uid:
                my_row = a
        tab.assessments_table.resizeColumnsToContents()
        if my_row:
            tab.assess_p.setValue(int(my_row.probability))
            tab.assess_i.setValue(int(my_row.impact))
            tab.assess_notes.setText(my_row.notes or "")
        else:
            self._reset_assessment_form()

    def _save_assessment(self) -> None:
        tab = self.assessments_tab
        pid = self.current_project_id
        item_id = getattr(self, "current_assessment_item_id", None)
        item_type = getattr(self, "current_assessment_item_type", "risk")
        if not pid or not item_id:
            return
        p = int(tab.assess_p.value())
        i = int(tab.assess_i.value())
        notes = (tab.assess_notes.text() or "").strip()
        if (
            self._call_backend(
                "Assessment save failed",
                self.backend.upsert_my_assessment,
                pid,
                item_type,
                item_id,
                p,
                i,
                notes,
            )
            is None
        ):
            return
        self._refresh_assessments()
        self._update_sync_status()
