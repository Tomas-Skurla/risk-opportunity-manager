"""Selection regressions for the real Actions parent dropdowns."""

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QComboBox
from riskapp_client.ui_v2.mixins.actions_mixin import ActionsMixin


class _ActionsHarness(ActionsMixin):
    def __init__(self, qtbot) -> None:
        risk_combo = QComboBox()
        opportunity_combo = QComboBox()
        qtbot.addWidget(risk_combo)
        qtbot.addWidget(opportunity_combo)
        self.actions_tab = SimpleNamespace(
            action_risk_combo=risk_combo,
            action_opp_combo=opportunity_combo,
        )
        self.current_project_id = "project-1"
        self._risk_title_by_id = {}
        self._opp_title_by_id = {}

    @staticmethod
    def _call_backend(_title, method, *args):
        return method(*args)


@pytest.mark.parametrize("kind", ["risk", "opportunity"])
def test_refresh_preserves_parent_id_and_leaves_deleted_parent_unselected(
    qtbot, kind
) -> None:
    window = _ActionsHarness(qtbot)
    combo = (
        window.actions_tab.action_risk_combo
        if kind == "risk"
        else window.actions_tab.action_opp_combo
    )
    combo.addItem("First", "first")
    combo.addItem("Second", "second")
    combo.setCurrentIndex(1)
    cache_attr = "_risk_title_by_id" if kind == "risk" else "_opp_title_by_id"
    items = [
        SimpleNamespace(id="first", title="First"),
        SimpleNamespace(id="second", title="Renamed second"),
    ]

    window._refresh_target_combo(combo, lambda _pid: items, cache_attr)
    assert combo.currentData() == "second"
    assert combo.currentText() == "Renamed second"

    items.reverse()
    window._refresh_target_combo(combo, lambda _pid: items, cache_attr)
    assert combo.currentData() == "second"

    items[:] = [items[1]]
    window._refresh_target_combo(combo, lambda _pid: items, cache_attr)
    assert combo.currentIndex() == -1
    assert combo.currentData() is None
    window._refresh_target_combo(combo, lambda _pid: items, cache_attr)
    assert combo.currentIndex() == -1

    window.current_project_id = None
    window._refresh_target_combo(combo, lambda _pid: items, cache_attr)
    assert combo.count() == 0
    assert getattr(window, cache_attr) == {}


def test_failed_refresh_keeps_selection_and_signal_blocking(qtbot) -> None:
    window = _ActionsHarness(qtbot)
    combo = window.actions_tab.action_risk_combo
    combo.addItem("Selected", "risk-1")
    combo.blockSignals(True)

    window._refresh_target_combo(combo, lambda _pid: None, "_risk_title_by_id")
    assert combo.currentData() == "risk-1"
    assert combo.signalsBlocked()

    window._refresh_target_combo(
        combo,
        lambda _pid: [SimpleNamespace(id="risk-1", title="Updated")],
        "_risk_title_by_id",
    )
    assert combo.currentData() == "risk-1"
    assert combo.signalsBlocked()
