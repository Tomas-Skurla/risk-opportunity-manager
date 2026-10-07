"""Interaction tests for the separate field merge dialog."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QComboBox, QDialog
from riskapp_client.ui_v2.components.conflict_field_merge_dialog import (
    ConflictFieldMergeDialog,
)


def _conflict() -> dict:
    return {
        "entity": "risk",
        "entity_id": "risk-1",
        "title": "Supplier outage",
        "op": "upsert",
        "server_version": 7,
        "record": {"id": "risk-1", "title": "Local", "probability": 4},
        "server_record": {"id": "risk-1", "title": "Server", "probability": 2},
    }


def test_field_rows_require_at_least_one_local_choice(qtbot) -> None:
    dialog = ConflictFieldMergeDialog(_conflict())
    qtbot.addWidget(dialog)

    assert dialog.ui.item_label.text() == "Supplier outage"
    assert dialog.ui.version_label.text() == "Based on saved server version 7"
    assert dialog.ui.field_table.columnCount() == 4
    assert dialog.ui.field_table.rowCount() == 2
    for column, expected in enumerate(("Title", "Local", "Server")):
        item = dialog.ui.field_table.item(0, column)
        assert item is not None
        assert item.text() == expected
    assert not dialog.ui.queue_merge_btn.isEnabled()
    title_choice = dialog.ui.field_table.cellWidget(0, 3)
    assert isinstance(title_choice, QComboBox)
    assert dialog.choices() == {"title": "server", "probability": "server"}

    title_choice.setCurrentIndex(1)
    assert dialog.ui.queue_merge_btn.isEnabled()
    assert dialog.choices() == {"title": "mine", "probability": "server"}
    dialog.ui.queue_merge_btn.click()
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_deletion_has_no_field_merge_dialog() -> None:
    conflict = _conflict()
    conflict["server_record"]["is_deleted"] = True
    with pytest.raises(ValueError, match="cannot be merged"):
        ConflictFieldMergeDialog(conflict)
