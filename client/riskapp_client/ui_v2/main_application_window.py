
from __future__ import annotations

from PySide6.QtWidgets import QMainWindow  # pylint: disable=no-name-in-module

from riskapp_client.domain.domain_models import Backend
from riskapp_client.ui_v2.mixins.actions_mixin import ActionsMixin
from riskapp_client.ui_v2.mixins.assessments_mixin import AssessmentsMixin
from riskapp_client.ui_v2.mixins.global_state_mixin import CoreMixin
from riskapp_client.ui_v2.mixins.helpdesk_mixin import HelpDeskMixin
from riskapp_client.ui_v2.mixins.layout_mixin import LayoutMixin
from riskapp_client.ui_v2.mixins.matrix_mixin import MatrixMixin
from riskapp_client.ui_v2.mixins.members_mixin import MembersMixin
from riskapp_client.ui_v2.mixins.opportunities_mixin import OpportunitiesMixin
from riskapp_client.ui_v2.mixins.projects_sync_mixin import ProjectsSyncMixin
from riskapp_client.ui_v2.mixins.risks_mixin import RisksMixin
from riskapp_client.ui_v2.mixins.top_history_mixin import TopHistoryMixin


class MainWindow(  # pylint: disable=too-many-ancestors
    QMainWindow,
    LayoutMixin,
    CoreMixin,
    ProjectsSyncMixin,
    RisksMixin,
    OpportunitiesMixin,
    ActionsMixin,
    AssessmentsMixin,
    MembersMixin,
    MatrixMixin,
    TopHistoryMixin,
    HelpDeskMixin,
):
    """Main application window.

    Composed of multiple mixins to handle distinct UI components and state.
    """

    def __init__(self, backend: Backend) -> None:
        super().__init__()
        self.backend = backend
        self._init_state()
        self._build_ui()
        self._load_projects()
