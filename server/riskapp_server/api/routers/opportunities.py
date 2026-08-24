from __future__ import annotations

from riskapp_server.api.routers.crud_factory import create_crud_router
from riskapp_server.db.session import Assessment, Item
from riskapp_server.schemas.models import (
    OpportunityAssessmentOut,
    OpportunityCreate,
    OpportunityOut,
    OpportunityUpdate,
)

router = create_crud_router(
    prefix="opportunities",
    tags=["opportunities"],
    Model=Item,
    CreateSchema=OpportunityCreate,
    UpdateSchema=OpportunityUpdate,
    OutSchema=OpportunityOut,
    fixed_type="opportunity",
    AssessmentModel=Assessment,
    AssessmentOutSchema=OpportunityAssessmentOut,
)
