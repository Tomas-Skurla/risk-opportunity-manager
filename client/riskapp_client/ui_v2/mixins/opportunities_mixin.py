"""MainWindow mixin for the Opportunities tab.

Filtering, table rendering, editor behavior, and CSV export for opportunities.
"""

from __future__ import annotations

from riskapp_client.adapters.local_storage import csv_data_exporter as export_csv
from riskapp_client.services import entity_filters as filters
from riskapp_client.ui_v2.mixins.scored_entity_mixin import ScoredEntityMixin


class OpportunitiesMixin(ScoredEntityMixin):
    """MainWindow mixin: OpportunitiesMixin"""

    def _mark_opp_editor_dirty(self, *args) -> None:
        self._opp_editor_dirty = True

    def _commit_opp_editor_changes(
        self, *, refresh: bool, select_id: str | None = None
    ) -> None:
        if self._commit_entity_editor_changes(
            self.current_opportunity_id,
            self._opp_editor_dirty,
            self.opp_form,
            self.backend.update_opportunity,
            self._refresh_opportunities if refresh else None,
            select_id,
        ):
            self._opp_editor_dirty = False

    def _export_opportunities_csv(self) -> None:
        self._export_entity_csv(
            "opportunities.csv", self._opp_cache, export_csv.export_opportunities
        )

    def _refresh_opportunities(self, select_id: str | None = None) -> None:
        pid = self.current_project_id
        if not pid:
            return
        filters_dict = {
            "min_score": self.opp_filter_min_score,
            "max_score": self.opp_filter_max_score,
            "search": self.opp_filter_search,
            "status": self.opp_filter_status,
            "category": self.opp_filter_category,
            "owner": self.opp_filter_owner,
            "from_date": self.opp_filter_from,
            "to_date": self.opp_filter_to,
        }
        res = self._refresh_entity(
            pid,
            self.backend.list_opportunities,
            filters.filter_opportunities,
            filters.OpportunityFilterCriteria,
            self.opp_filter_report,
            self.opps_table,
            filters_dict,
            self._mk_item,
            getattr(self.backend, "opportunities_report", None),
            select_id,
        )
        if res is not None:
            self._opp_cache = res
            self._opp_title_by_id = {o.id: o.title for o in res.values()}

    def _on_opportunity_clicked(self, row: int, col: int) -> None:
        new_id = self._on_entity_clicked(
            row,
            col,
            self.opps_table,
            self._opp_cache,
            self.current_opportunity_id,
            self._opp_editor_dirty,
            self._commit_opp_editor_changes,
            self.opp_form,
            self.opp_editor_label,
            "Editor",
        )
        if new_id:
            self.current_opportunity_id = new_id
            self._opp_editor_dirty = False
            self._sync_assessment_state("opportunity", new_id, self.opps_tab)

    def _start_new_opportunity(self) -> None:
        self._commit_opp_editor_changes(refresh=True)
        self.current_opportunity_id = None
        self.opp_editor_label.setText("Editor (new opportunity)")
        self.opp_form.set_values(title="", probability=3, impact=3)
        self._opp_editor_dirty = False
        self.opps_table.clearSelection()
        self._sync_assessment_state("opportunity", None, self.opps_tab)

    def _save_opportunity(self, payload: dict) -> None:
        extra = [self._refresh_action_opp_combo, self._refresh_actions]
        saved_id = self._save_entity(
            payload,
            self.current_opportunity_id,
            self.backend.update_opportunity,
            self.backend.create_opportunity,
            self._refresh_opportunities,
            self.opp_form,
            self.opp_editor_label,
            "Editor",
            extra,
        )
        if saved_id:
            self.current_opportunity_id = saved_id
            self._opp_editor_dirty = False
            self._sync_assessment_state("opportunity", saved_id, self.opps_tab)

    def _delete_opportunity(self) -> None:
        def refresh_all():
            self._refresh_opportunities()
            self._refresh_action_opp_combo()
            self._refresh_actions()
            self._refresh_matrix()

        self._delete_entity(
            current_id=self.current_opportunity_id,
            delete_backend_fn=self.backend.delete_opportunity,
            refresh_fn=refresh_all,
            start_new_fn=self._start_new_opportunity,
        )
