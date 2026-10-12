"""Structural checks for the mixins composed into the main window."""

from __future__ import annotations

from collections import defaultdict

from PySide6.QtWidgets import QMainWindow
from riskapp_client.ui_v2.main_application_window import MainWindow


def test_each_main_window_member_has_a_single_mixin_owner() -> None:
    """No two mixins define the same attribute at runtime.

    If they did, the order of MainWindow's base classes would silently decide
    which definition runs. Declarations that only help static analysis belong
    behind ``if TYPE_CHECKING:`` so they never exist at runtime.
    """
    owners: dict[str, list[str]] = defaultdict(list)
    for mixin in MainWindow.__bases__:
        if mixin is QMainWindow:
            continue
        for name in vars(mixin):
            if not (name.startswith("__") and name.endswith("__")):
                owners[name].append(mixin.__name__)

    shared = {name: found for name, found in owners.items() if len(found) > 1}
    assert shared == {}
