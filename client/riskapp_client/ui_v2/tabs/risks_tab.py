"""Risks tab widget."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QWidget

from riskapp_client.ui_v2.tabs.scored_entities_base_tab import ScoredEntitiesTab


class RisksTab(ScoredEntitiesTab):
    """Risks list + editor tab."""

    def __init__(
        self,
        *,
        on_export_csv: Callable[[], None],
        on_refresh: Callable[[], None],
        on_risk_clicked: Callable[[int, int], None],
        on_new_risk: Callable[[], None],
        on_save_risk: Callable[[dict], None],
        on_delete_item: Callable[[], None],
        on_mark_dirty: Callable[..., None],
        on_fit_table_card: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            entity_label_singular="risk",
            on_export_csv=on_export_csv,
            on_refresh=on_refresh,
            on_item_clicked=on_risk_clicked,
            on_new_item=on_new_risk,
            on_save_item=on_save_risk,
            on_delete_item=on_delete_item,
            on_mark_dirty=on_mark_dirty,
            on_fit_table_card=on_fit_table_card,
            parent=parent,
        )
        self.table_card = self.ui.table_card
        self.editor_card = self.ui.editor_card
