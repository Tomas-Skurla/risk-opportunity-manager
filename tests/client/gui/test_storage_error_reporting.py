"""Database save failures reach the UI while the transaction rolls back."""

import sqlite3

import pytest
from PySide6.QtWidgets import QMessageBox, QWidget
from riskapp_client.services.offline_first_facade import OfflineFirstBackend
from riskapp_client.ui_v2.mixins.global_state_mixin import CoreMixin


def test_failed_save_reports_database_error_and_rolls_back(
    qtbot, local_store, monkeypatch
):
    widget = QWidget()
    qtbot.addWidget(widget)
    local_store.create_local_project(name="Project", project_id="p1")
    backend = OfflineFirstBackend(local_store)
    original = local_store._upsert_row

    def fail_after_write(*args, **kwargs):
        original(*args, **kwargs)
        raise sqlite3.OperationalError("simulated disk full")

    monkeypatch.setattr(local_store, "_upsert_row", fail_after_write)
    messages = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda _parent, title, message: messages.append((title, message)),
    )
    result = CoreMixin._call_backend(
        widget,
        "Save risk",
        backend.create_risk,
        "p1",
        title="Draft",
        probability=2,
        impact=2,
    )
    assert result is None
    assert messages == [("Save risk", "simulated disk full")]
    assert local_store.conn.execute("SELECT count(*) FROM risks").fetchone()[0] == 0
    assert backend.outbox.pending_count("p1") == 0


def test_programming_error_is_not_hidden(qtbot):
    widget = QWidget()
    qtbot.addWidget(widget)

    def fail():
        raise ValueError("programming error")

    with pytest.raises(ValueError, match="programming error"):
        CoreMixin._call_backend(widget, "Save", fail)
