"""Focused behavior tests for the risks window mixin."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from riskapp_client.ui_v2.mixins.risks_mixin import RisksMixin


def test_fit_table_card_delegates_to_shared_table_sizing() -> None:
    table = object()
    host = SimpleNamespace(
        risks_table=table,
        _fit_table_to_contents=Mock(),
    )

    RisksMixin._fit_table_card(host, max_height=144)

    host._fit_table_to_contents.assert_called_once_with(table, max_height=144)
