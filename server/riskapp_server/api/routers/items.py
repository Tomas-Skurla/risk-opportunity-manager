"""Routes for the two scored item kinds, risks and opportunities."""

import uuid
from collections.abc import Callable, Sequence
from types import FunctionType, GenericAlias
from typing import Any, cast

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from riskapp_server.auth.service import get_current_user
from riskapp_server.core.filters import ItemFilterParams
from riskapp_server.core.items_crud import (
    create_item,
    delete_item,
    generate_report,
    item_assessments,
    item_csv_rows,
    list_items,
    require_item,
    status_value,
    update_item,
    upsert_assessment,
)
from riskapp_server.core.permissions import ensure_member, require_min_role
from riskapp_server.db.models import Item, RiskStatus, Role, User
from riskapp_server.db.session import get_db
from riskapp_server.schemas.models import (
    AssessmentIn,
    OpportunityAssessmentOut,
    OpportunityCreate,
    OpportunityOut,
    OpportunityUpdate,
    RiskAssessmentOut,
    RiskCreate,
    RiskOut,
    RiskUpdate,
    ScoreReportOut,
)


def _set_payload_schema(endpoint: Callable[..., Any], schema: type[BaseModel]) -> None:
    """Give FastAPI the kind's request model; mypy rejects a variable annotation."""
    cast(FunctionType, endpoint).__annotations__["payload"] = schema


def create_item_router(
    *,
    item_type: str,
    prefix: str,
    create_schema: type[BaseModel],
    update_schema: type[BaseModel],
    out_schema: type[BaseModel],
    assessment_out_schema: type[BaseModel],
) -> APIRouter:
    """Routes for one item kind under ``/projects/{project_id}/{prefix}``."""
    r = APIRouter(tags=[prefix])
    collection = f"/projects/{{project_id}}/{prefix}"
    one = f"{collection}/{{item_id}}"

    def of_kind(filters: ItemFilterParams) -> dict[str, Any]:
        return {**vars(filters), "item_type": item_type}

    def create_obj(
        project_id: uuid.UUID,
        payload: BaseModel,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> Any:
        require_min_role(db, project_id, user.id, min_role=Role.member)
        return create_item(db, user.id, project_id, payload, Item)

    _set_payload_schema(create_obj, create_schema)
    r.add_api_route(
        collection,
        create_obj,
        methods=["POST"],
        response_model=out_schema,
        status_code=201,
    )

    @r.get(collection, response_model=GenericAlias(list, out_schema))
    def list_objs(
        project_id: uuid.UUID,
        filters: ItemFilterParams = Depends(),
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> Sequence[Any]:
        ensure_member(db, project_id, user.id)
        return list_items(db, project_id, Item, of_kind(filters))

    @r.get(f"{collection}/export.csv")
    def export_csv(
        project_id: uuid.UUID,
        filters: ItemFilterParams = Depends(),
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> StreamingResponse:
        """Export the current filtered page as CSV."""
        ensure_member(db, project_id, user.id)
        return StreamingResponse(
            item_csv_rows(db, project_id, of_kind(filters)),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={prefix}_export.csv"
            },
        )

    def update_obj(
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        payload: BaseModel,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> Any:
        deleting = (
            status_value(getattr(payload, "status", None)) == RiskStatus.deleted.value
        )
        min_role = Role.manager if deleting else Role.member
        require_min_role(db, project_id, user.id, min_role=min_role)
        return update_item(db, project_id, item_id, payload, Item, item_type=item_type)

    _set_payload_schema(update_obj, update_schema)
    r.add_api_route(one, update_obj, methods=["PATCH"], response_model=out_schema)

    @r.delete(one, status_code=204, response_class=Response)
    def delete_obj(
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> Response:
        require_min_role(db, project_id, user.id, min_role=Role.manager)
        delete_item(db, project_id, item_id, Item, item_type=item_type)
        return Response(status_code=204)

    @r.get(f"{collection}/report", response_model=ScoreReportOut)
    def obj_report(
        project_id: uuid.UUID,
        filters: ItemFilterParams = Depends(),
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> ScoreReportOut:
        ensure_member(db, project_id, user.id)
        return generate_report(db, project_id, Item, of_kind(filters))

    @r.get(
        f"{one}/assessments", response_model=GenericAlias(list, assessment_out_schema)
    )
    def list_assessments(
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> Sequence[Any]:
        ensure_member(db, project_id, user.id)
        require_item(db, project_id, item_id, item_type)
        return item_assessments(db, item_id)

    @r.put(f"{one}/assessment", response_model=assessment_out_schema)
    def upsert_my_assessment(
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        payload: AssessmentIn,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> Any:
        """Upsert the calling user's assessment for a scored item."""
        require_min_role(db, project_id, user.id, min_role=Role.member)
        require_item(db, project_id, item_id, item_type)
        return upsert_assessment(db, item_id, user.id, payload)

    return r


risks_router = create_item_router(
    item_type="risk",
    prefix="risks",
    create_schema=RiskCreate,
    update_schema=RiskUpdate,
    out_schema=RiskOut,
    assessment_out_schema=RiskAssessmentOut,
)
opportunities_router = create_item_router(
    item_type="opportunity",
    prefix="opportunities",
    create_schema=OpportunityCreate,
    update_schema=OpportunityUpdate,
    out_schema=OpportunityOut,
    assessment_out_schema=OpportunityAssessmentOut,
)
