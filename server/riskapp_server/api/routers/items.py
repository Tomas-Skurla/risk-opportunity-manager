"""Combined router for risks and opportunities."""

from __future__ import annotations

from fastapi import APIRouter

from riskapp_server.api.routers.opportunities import router as opportunities_router
from riskapp_server.api.routers.risks import router as risks_router

router = APIRouter()
router.include_router(risks_router)
router.include_router(opportunities_router)
