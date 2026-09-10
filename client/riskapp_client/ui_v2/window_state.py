"""Explicit cross-cutting state owned by the main application window."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MainWindowState:
    """Selection and access state shared across otherwise independent mixins."""

    project_id: str | None = None
    risk_id: str | None = None
    opportunity_id: str | None = None
    action_id: str | None = None
    assessment_item_type: str = "risk"
    assessment_item_id: str | None = None
    role: str = "unknown"
    offline_mode: bool = False
    role_assumed: bool = False
