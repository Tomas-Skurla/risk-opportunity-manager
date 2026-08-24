"""MainWindow mixin for the risk matrix view.

Computes and renders 5×5 count matrices from current risks/opportunities.
"""

from __future__ import annotations

import contextlib


class MatrixMixin:
    """MainWindow mixin: MatrixMixin"""

    def _on_matrix_kind_changed(self, text: str) -> None:
        with contextlib.suppress(AttributeError, RuntimeError, ValueError):
            self.matrix_tab.set_kind(text)
        self._refresh_matrix()

    def _render_matrix(self, table, items) -> None:
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
        kind = "risks"
        with contextlib.suppress(AttributeError, RuntimeError, ValueError):
            kind = (self.matrix_tab.kind_combo.currentText() or "Risks").strip().lower()
        if kind == "opportunities":
            opps = self._call_backend(
                "Backend error", self.backend.list_opportunities, pid
            )
            if opps is None:
                return
            self._render_matrix(self.opps_matrix_table, opps)
        elif kind == "both":
            risks = self._call_backend("Backend error", self.backend.list_risks, pid)
            if risks is None:
                return
            opps = self._call_backend(
                "Backend error", self.backend.list_opportunities, pid
            )
            if opps is None:
                return
            self._render_matrix(self.risks_matrix_table, risks)
            self._render_matrix(self.opps_matrix_table, opps)
        else:
            risks = self._call_backend("Backend error", self.backend.list_risks, pid)
            if risks is None:
                return
            self._render_matrix(self.risks_matrix_table, risks)
