"""Qt interaction tests for the minimal Conflict Center."""

from __future__ import annotations

import sqlite3
from unittest.mock import Mock

from PySide6.QtWidgets import QComboBox, QDialog, QMessageBox
from riskapp_client.ui_v2.components.conflict_center_dialog import (
    ConflictCenterDialog,
)
from riskapp_client.ui_v2.components.conflict_field_merge_dialog import (
    ConflictFieldMergeDialog,
)

# These tests intentionally call the private resolution step to cover its outcomes.
# pylint: disable=protected-access


def _conflict(
    change_id: str = "change-1", *, server_record: dict | None = None
) -> dict:
    return {
        "change_id": change_id,
        "project_id": "project-1",
        "entity": "risk",
        "entity_id": "risk-1",
        "title": "Supplier outage",
        "op": "upsert",
        "reason": "version_mismatch",
        "server_version": 7,
        "server_updated_at": "2026-09-04T12:00:00",
        "record": {
            "id": "risk-1",
            "title": "Local title",
            "probability": 5,
            "impact": 4,
        },
        "server_record": (
            server_record
            if server_record is not None
            else {
                "id": "risk-1",
                "title": "Server title",
                "probability": 2,
                "impact": 3,
                "version": 7,
            }
        ),
    }


def test_dialog_lists_conflict_and_compares_both_copies(qtbot) -> None:
    dialog = ConflictCenterDialog([_conflict()], Mock())
    qtbot.addWidget(dialog)

    assert dialog.objectName() == "conflict_center_dialog"
    assert dialog.ui.conflict_table is dialog.table
    assert dialog.ui.local_copy is dialog.local_copy
    assert dialog.ui.server_copy is dialog.server_copy
    assert dialog.ui.local_group.title() == "Local copy"
    assert dialog.ui.server_group.title() == "Server copy"
    assert dialog.table.rowCount() == 1
    entity_item = dialog.table.item(0, 0)
    title_item = dialog.table.item(0, 1)
    reason_item = dialog.table.item(0, 3)
    assert entity_item is not None and entity_item.text() == "Risk"
    assert title_item is not None and title_item.text() == "Supplier outage"
    assert reason_item is not None and reason_item.text() == "version_mismatch"
    assert '"title": "Local title"' in dialog.local_copy.toPlainText()
    assert '"title": "Server title"' in dialog.server_copy.toPlainText()
    assert dialog.keep_mine_btn.isEnabled()
    assert dialog.use_server_btn.isEnabled()
    assert dialog.conflicts_remaining() == 1


def test_keep_mine_requires_confirmation_and_removes_resolved_row(
    monkeypatch, qtbot
) -> None:
    resolver = Mock(
        return_value={
            "resolved": True,
            "resolution": "keep_mine",
            "replacement_change_id": "change-2",
        }
    )
    dialog = ConflictCenterDialog([_conflict()], resolver)
    qtbot.addWidget(dialog)
    resolved = Mock()
    dialog.conflict_resolved.connect(resolved)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    dialog._resolve_selected("keep_mine")

    resolver.assert_called_once_with("change-1", "keep_mine")
    resolved.assert_called_once_with("change-1", "keep_mine")
    assert dialog.conflicts_remaining() == 0
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_declining_confirmation_does_not_resolve(qtbot, monkeypatch) -> None:
    resolver = Mock()
    dialog = ConflictCenterDialog([_conflict()], resolver)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )

    dialog._resolve_selected("use_server")

    resolver.assert_not_called()
    assert dialog.conflicts_remaining() == 1


def test_resolution_failure_is_reported_and_conflict_remains(
    qtbot, monkeypatch
) -> None:
    resolver = Mock(side_effect=RuntimeError("server copy is stale"))
    dialog = ConflictCenterDialog([_conflict()], resolver)
    qtbot.addWidget(dialog)
    critical = Mock()
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(QMessageBox, "critical", critical)

    dialog._resolve_selected("use_server")

    critical.assert_called_once()
    assert "server copy is stale" in critical.call_args.args[2]
    assert dialog.conflicts_remaining() == 1


def test_later_closes_without_mutating_conflicts(qtbot) -> None:
    resolver = Mock()
    dialog = ConflictCenterDialog([_conflict()], resolver)
    qtbot.addWidget(dialog)

    dialog.later_btn.click()

    resolver.assert_not_called()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.conflicts_remaining() == 1


def test_use_server_is_disabled_without_a_saved_server_copy(qtbot) -> None:
    conflict = _conflict()
    conflict["server_record"] = None
    dialog = ConflictCenterDialog([conflict], Mock())
    qtbot.addWidget(dialog)

    assert not dialog.use_server_btn.isEnabled()
    assert "Server copy unavailable" in dialog.server_copy.toPlainText()


def test_field_choices_send_explicit_selection_to_resolver(qtbot, monkeypatch) -> None:
    resolver = Mock(return_value={"resolved": True, "resolution": "merge"})
    dialog = ConflictCenterDialog([_conflict()], resolver)
    qtbot.addWidget(dialog)
    assert dialog.merge_btn.isEnabled()
    assert dialog.ui.merge_btn is dialog.merge_btn
    assert not hasattr(dialog, "field_table")

    def choose_title(merge: ConflictFieldMergeDialog) -> int:
        assert merge.ui.field_table.rowCount() == 3
        choice = merge.ui.field_table.cellWidget(0, 3)
        assert isinstance(choice, QComboBox)
        choice.setCurrentIndex(1)
        merge.ui.queue_merge_btn.click()
        return merge.result()

    monkeypatch.setattr(ConflictFieldMergeDialog, "exec", choose_title)
    dialog.merge_btn.click()
    resolver.assert_called_once_with(
        "change-1", "merge",
        {"title": "mine", "probability": "server", "impact": "server"},
    )


def test_cancelling_merge_leaves_conflict_blocked(qtbot, monkeypatch) -> None:
    resolver = Mock()
    dialog = ConflictCenterDialog([_conflict()], resolver)
    qtbot.addWidget(dialog)

    def cancel(merge: ConflictFieldMergeDialog) -> int:
        merge.ui.cancel_btn.click()
        return merge.result()

    monkeypatch.setattr(ConflictFieldMergeDialog, "exec", cancel)
    dialog.merge_btn.click()
    resolver.assert_not_called()
    assert dialog.conflicts_remaining() == 1


def test_deleted_record_cannot_be_merged(qtbot) -> None:
    conflict = _conflict()
    conflict["server_record"]["is_deleted"] = True
    dialog = ConflictCenterDialog([conflict], Mock())
    qtbot.addWidget(dialog)
    assert not dialog.merge_btn.isEnabled()


def test_merge_sqlite_failure_is_reported_and_conflict_remains(
    qtbot, monkeypatch
) -> None:
    resolver = Mock(side_effect=sqlite3.IntegrityError("merged write failed"))
    dialog = ConflictCenterDialog([_conflict()], resolver)
    qtbot.addWidget(dialog)
    critical = Mock()
    monkeypatch.setattr(QMessageBox, "critical", critical)

    dialog._resolve_selected(
        "merge", {"title": "mine", "probability": "server", "impact": "server"}
    )

    resolver.assert_called_once_with(
        "change-1", "merge",
        {"title": "mine", "probability": "server", "impact": "server"},
    )
    critical.assert_called_once()
    assert "merged write failed" in critical.call_args.args[2]
    assert dialog.conflicts_remaining() == 1
