"""MainWindow mixin for the Opportunities tab.

Filtering, table rendering, editor behavior, and CSV export for opportunities.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from riskapp_client.adapters.export import csv_data_exporter as export_csv
from riskapp_client.ui_v2.mixins.scored_entity_mixin import ScoredEntityMixin

if TYPE_CHECKING:
    from PySide6.QtWidgets import (
        QLabel,
        QTableWidget,
        QTableWidgetItem,
    )
    from riskapp_client.domain.domain_models import Opportunity
    from riskapp_client.ui_v2.components.custom_gui_widgets import RiskForm
    from riskapp_client.ui_v2.tabs.opportunities_tab import OpportunitiesTab


class OpportunitiesMixin(ScoredEntityMixin):
    """MainWindow mixin: OpportunitiesMixin"""

    backend: Any
    current_opportunity_id: str | None
    current_project_id: str | None
    opp_editor_label: QLabel
    opp_form: RiskForm
    opps_tab: OpportunitiesTab
    opps_table: QTableWidget
    _opp_cache: dict[str, Opportunity]
    _opp_editor_dirty: bool
    _opportunity_editor_base_version: int | None
    _mk_item: Callable[..., QTableWidgetItem]
    _refresh_action_opp_combo: Callable[[], None]
    _refresh_actions: Callable[..., None]
    _refresh_matrix: Callable[[], None]
    _sync_assessment_state: Callable[..., None]

    def _mark_opp_editor_dirty(self, *_args: object) -> None:
        self._opp_editor_dirty = True

    def _refresh_after_opportunity_change(self, select_id: str | None = None) -> None:
        """Redraw every view that shows opportunities, including action titles.

        The opportunity table may be filtered, so the full title list comes from
        the Actions combo refresh rather than from the table.
        """
        self._refresh_opportunities(select_id)
        self._refresh_action_opp_combo()
        self._refresh_actions()
        self._refresh_matrix()

    def _commit_opp_editor_changes(
        self, *, refresh: bool, select_id: str | None = None
    ) -> None:
        if self._commit_entity_editor_changes(
            self.current_opportunity_id,
            self._opp_editor_dirty,
            self.opp_form,
            self.backend.update_opportunity,
            self._refresh_after_opportunity_change if refresh else None,
            select_id,
            base_version=self._opportunity_editor_base_version,
        ):
            self._opp_editor_dirty = False

    def _export_opportunities_csv(self) -> None:
        self._export_entity_csv(
            "opportunities.csv", self._opp_cache, export_csv.export_opportunities
        )

    def _refresh_opportunities(
        self,
        select_id: str | None = None,
        *,
        use_remote_report: bool = True,
    ) -> None:
        pid = self.current_project_id
        if not pid:
            return
        res = self._refresh_entity(
            pid,
            self.opps_tab,
            self.backend.list_opportunities,
            (
                getattr(self.backend, "opportunities_report", None)
                if use_remote_report
                else None
            ),
            select_id,
        )
        if res is not None:
            self._opp_cache = res

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
            selected = self._opp_cache.get(new_id)
            self._opportunity_editor_base_version = (
                int(selected.version) if selected is not None else None
            )
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
        was_new = self.current_opportunity_id is None
        saved_id = self._save_entity(
            payload,
            self.current_opportunity_id,
            self.backend.update_opportunity,
            self.backend.create_opportunity,
            self._refresh_after_opportunity_change,
            self.opp_form,
            self.opp_editor_label,
            "Editor",
            [],
            base_version=self._opportunity_editor_base_version,
        )
        if saved_id:
            self.current_opportunity_id = saved_id
            if was_new:
                selected = self._opp_cache.get(saved_id)
                self._opportunity_editor_base_version = (
                    int(selected.version) if selected is not None else 0
                )
            self._opp_editor_dirty = False
            self._sync_assessment_state("opportunity", saved_id, self.opps_tab)

    def _delete_opportunity(self) -> None:

        self._delete_entity(
            current_id=self.current_opportunity_id,
            delete_backend_fn=self.backend.delete_opportunity,
            refresh_fn=self._refresh_after_opportunity_change,
            start_new_fn=self._start_new_opportunity,
        )
