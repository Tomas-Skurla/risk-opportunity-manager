"""MainWindow mixin for the Assessments tab."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from riskapp_client.domain.domain_models import Member
from riskapp_client.ui_v2.components.custom_gui_widgets import fill_table

if TYPE_CHECKING:
    from PySide6.QtWidgets import QTableWidgetItem
    from riskapp_client.ui_v2.tabs.assessments_tab import AssessmentsTab


class AssessmentsMixin:
    """MainWindow mixin: AssessmentsMixin"""

    # Supplied by MainWindow, CoreMixin, and LayoutMixin.
    backend: Any
    assessments_tab: AssessmentsTab
    current_project_id: str | None
    current_assessment_item_id: str | None
    current_assessment_item_type: str
    _cached_members: list[Member]
    _risk_title_by_id: dict[str, str]
    _opp_title_by_id: dict[str, str]

    _call_backend: Callable[..., Any]
    _mk_item: Callable[..., QTableWidgetItem]
    _update_sync_status: Callable[[], None]

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
        item_id = self.current_assessment_item_id
        item_type = self.current_assessment_item_type
        tab.target_label.setText(self._assessment_target_text(item_type, item_id))
        tab.assessments_table.setRowCount(0)
        if not pid or not item_id:
            self._reset_assessment_form()
            return
        assessments = self._call_backend(
            "Backend error", self.backend.list_assessments, pid, item_type, item_id
        )
        if assessments is None:
            return

        email_by_uid = {str(m.user_id): m.email for m in self._cached_members}
        fill_table(
            tab.assessments_table,
            (
                (
                    self._mk_item(
                        email_by_uid.get(
                            a.assessor_user_id or "", (a.assessor_user_id or "")[:8]
                        )
                    ),
                    self._mk_item(str(a.probability), align_center=True),
                    self._mk_item(str(a.impact), align_center=True),
                    self._mk_item(str(a.score), align_center=True),
                    self._mk_item(a.notes or ""),
                    self._mk_item(a.updated_at or ""),
                )
                for a in assessments
            ),
        )

        tab.assessments_table.resizeColumnsToContents()
        my_uid = self._current_user_id()
        mine = [
            a for a in assessments if my_uid and (a.assessor_user_id or "") == my_uid
        ]
        if mine:
            tab.assess_p.setValue(int(mine[-1].probability))
            tab.assess_i.setValue(int(mine[-1].impact))
            tab.assess_notes.setText(mine[-1].notes or "")
        else:
            self._reset_assessment_form()

    def _assessment_target_text(self, item_type: str, item_id: str | None) -> str:
        if not item_id:
            return "Target: (none)"
        titles = {"risk": self._risk_title_by_id, "opportunity": self._opp_title_by_id}
        title = titles.get(item_type, {}).get(item_id, "")
        noun = "Risk" if item_type == "risk" else "Opportunity"
        return f"Target: {noun}{' · ' + title if title else ''}"

    def _current_user_id(self) -> str | None:
        try:
            return self.backend.current_user_id()
        except AttributeError, RuntimeError:
            return None

    def _save_assessment(self) -> None:
        tab = self.assessments_tab
        pid = self.current_project_id
        item_id = self.current_assessment_item_id
        item_type = self.current_assessment_item_type
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
