from __future__ import annotations

from riskapp_server.api.routers.crud_factory import create_crud_router
from riskapp_server.db.session import Assessment, Item
from riskapp_server.schemas.models import (
    RiskAssessmentOut,
    RiskCreate,
    RiskOut,
    RiskUpdate,
)

router = create_crud_router(
    prefix="risks",
    tags=["risks"],
    Model=Item,
    CreateSchema=RiskCreate,
    UpdateSchema=RiskUpdate,
    OutSchema=RiskOut,
    fixed_type="risk",
    AssessmentModel=Assessment,
    AssessmentOutSchema=RiskAssessmentOut,
)
