"""MainWindow mixin for the Risks tab.

Filtering, table rendering, editor behavior, column sizing, and CSV export for risks.
"""

from __future__ import annotations

from riskapp_client.adapters.local_storage import csv_data_exporter as export_csv
from riskapp_client.services import entity_filters as filters
from riskapp_client.ui_v2.mixins.scored_entity_mixin import ScoredEntityMixin


class RisksMixin(ScoredEntityMixin):
    """MainWindow mixin: RisksMixin"""

    def _export_risks_csv(self) -> None:
        self._export_entity_csv("risks.csv", self._risk_cache, export_csv.export_risks)

    def _refresh_risks(self, select_id: str | None = None) -> None:
        pid = self.current_project_id
        if not pid:
            return
        filters_dict = {
            "min_score": self.filter_min_score,
            "max_score": self.filter_max_score,
            "search": self.filter_search,
            "status": self.filter_status,
            "category": self.filter_category,
            "owner": self.filter_owner,
            "from_date": self.filter_from,
            "to_date": self.filter_to,
        }
        res = self._refresh_entity(
            pid,
            self.backend.list_risks,
            filters.filter_risks,
            filters.RiskFilterCriteria,
            self.filter_report,
            self.risks_table,
            filters_dict,
            self._mk_item,
            getattr(self.backend, "risks_report", None),
            select_id,
        )
        if res is not None:
            self._risk_cache = res
        self.risks_table.resizeColumnsToContents()
        self._fit_table_card()

    def _on_risk_clicked(self, row: int, col: int) -> None:
        new_id = self._on_entity_clicked(
            row,
            col,
            self.risks_table,
            self._risk_cache,
            self.current_risk_id,
            self._editor_dirty,
            self._commit_editor_changes,
            self.risk_form,
            self.editor_label,
            "Editor",
        )
        if new_id:
            self.current_risk_id = new_id
            self._editor_dirty = False
            self._sync_assessment_state("risk", new_id, self.risks_tab)

    def _fit_table_card(self, max_height: int = 260) -> None:
        self._fit_table_to_contents(self.risks_table, max_height=max_height)

    def _mark_editor_dirty(self, *args) -> None:
        self._editor_dirty = True

    def _commit_editor_changes(
        self, *, refresh: bool, select_id: str | None = None
    ) -> None:
        def ref_cb(select_id):
            self._refresh_risks(select_id)
            self._refresh_matrix()

        if self._commit_entity_editor_changes(
            self.current_risk_id,
            self._editor_dirty,
            self.risk_form,
            self.backend.update_risk,
            ref_cb if refresh else None,
            select_id,
        ):
            self._editor_dirty = False

    def _start_new_risk(self) -> None:
        self._commit_editor_changes(refresh=True)
        self.current_risk_id = None
        self.editor_label.setText("Editor (new risk)")
        self.risk_form.set_values(title="", probability=3, impact=3)
        self._editor_dirty = False
        self.risks_table.clearSelection()
        self.risks_table.setCurrentItem(None)
        self._sync_assessment_state("risk", None, self.risks_tab)

    def _save_risk(self, payload: dict) -> None:
        extra = [
            self._refresh_action_risk_combo,
            self._refresh_actions,
            self._refresh_matrix,
        ]
        saved_id = self._save_entity(
            payload,
            self.current_risk_id,
            self.backend.update_risk,
            self.backend.create_risk,
            self._refresh_risks,
            self.risk_form,
            self.editor_label,
            "Editor",
            extra,
        )
        if saved_id:
            self.current_risk_id = saved_id
            self._editor_dirty = False
            self._sync_assessment_state("risk", saved_id, self.risks_tab)

    def _delete_risk(self) -> None:
        def refresh_all():
            self._refresh_risks()
            self._refresh_action_risk_combo()
            self._refresh_actions()
            self._refresh_matrix()

        self._delete_entity(
            current_id=self.current_risk_id,
            delete_backend_fn=self.backend.delete_risk,
            refresh_fn=refresh_all,
            start_new_fn=self._start_new_risk,
        )
