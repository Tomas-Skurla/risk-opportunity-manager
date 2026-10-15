"""MainWindow mixin for the risk matrix view.

Computes and renders 5x5 count matrices from current risks/opportunities.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import QTableWidget, QTableWidgetItem
from riskapp_client.ui_v2.tabs.matrix_tab import matrix_kinds

if TYPE_CHECKING:
    from riskapp_client.ui_v2.tabs.matrix_tab import MatrixTab


class MatrixMixin:
    """MainWindow mixin: MatrixMixin"""

    backend: Any
    current_project_id: str | None
    matrix_tab: MatrixTab
    opps_matrix_table: QTableWidget
    risks_matrix_table: QTableWidget
    _call_backend: Callable[..., Any]
    _mk_item: Callable[..., QTableWidgetItem]

    def _on_matrix_kind_changed(self, text: str) -> None:
        self.matrix_tab.set_kind(text)
        self._refresh_matrix()

    def _render_matrix(
        self,
        table: QTableWidget,
        items: Iterable[Any],
    ) -> None:
        grid = [[0 for _ in range(5)] for __ in range(5)]
        for it in items:
            p = max(1, min(5, int(getattr(it, "probability", 1))))
            i = max(1, min(5, int(getattr(it, "impact", 1))))
            grid[p - 1][i - 1] += 1
        for rp in range(5):
            for ci in range(5):
                table.setItem(
                    rp, ci, self._mk_item(str(grid[rp][ci]), align_center=True)
                )
        table.resizeColumnsToContents()

    def _refresh_matrix(self) -> None:
        pid = self.current_project_id
        if not pid:
            return
        show_risks, show_opps = matrix_kinds(self.matrix_tab.kind_combo.currentText())
        risks = (
            self._call_backend("Backend error", self.backend.list_risks, pid)
            if show_risks
            else []
        )
        if risks is None:
            return
        opps = (
            self._call_backend("Backend error", self.backend.list_opportunities, pid)
            if show_opps
            else []
        )
        if opps is None:
            return
        if show_risks:
            self._render_matrix(self.risks_matrix_table, risks)
        if show_opps:
            self._render_matrix(self.opps_matrix_table, opps)
