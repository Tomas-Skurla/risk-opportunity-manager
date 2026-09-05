"""Qt interaction tests for the minimal Conflict Center."""

from __future__ import annotations

from unittest.mock import Mock

from PySide6.QtWidgets import QDialog, QMessageBox
from riskapp_client.ui_v2.components.conflict_center_dialog import (
    ConflictCenterDialog,
)


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
    assert dialog.table.item(0, 0).text() == "Risk"
    assert dialog.table.item(0, 1).text() == "Supplier outage"
    assert dialog.table.item(0, 3).text() == "version_mismatch"
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
        lambda *args, **kwargs: QMessageBox.Yes,
    )

    dialog._resolve_selected("keep_mine")

    resolver.assert_called_once_with("change-1", "keep_mine")
    resolved.assert_called_once_with("change-1", "keep_mine")
    assert dialog.conflicts_remaining() == 0
    assert dialog.result() == QDialog.Accepted


def test_declining_confirmation_does_not_resolve(qtbot, monkeypatch) -> None:
    resolver = Mock()
    dialog = ConflictCenterDialog([_conflict()], resolver)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.No,
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
        lambda *args, **kwargs: QMessageBox.Yes,
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
    assert dialog.result() == QDialog.Rejected
    assert dialog.conflicts_remaining() == 1


def test_use_server_is_disabled_without_a_saved_server_copy(qtbot) -> None:
    conflict = _conflict()
    conflict["server_record"] = None
    dialog = ConflictCenterDialog([conflict], Mock())
    qtbot.addWidget(dialog)

    assert not dialog.use_server_btn.isEnabled()
    assert "Server copy unavailable" in dialog.server_copy.toPlainText()
