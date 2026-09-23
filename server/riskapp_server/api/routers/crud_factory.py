import csv
import io
import uuid
from collections.abc import Callable, Iterator, Sequence
from enum import Enum
from types import FunctionType, GenericAlias
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from riskapp_server.auth.service import get_current_user
from riskapp_server.core.csv_export import safe_csv_cell
from riskapp_server.core.filters import ItemFilterParams, apply_item_filters
from riskapp_server.core.items_crud import (
    claim_base_version,
    create_item,
    delete_item,
    generate_report,
    list_items,
    update_item,
)
from riskapp_server.core.permissions import ensure_member, require_min_role
from riskapp_server.core.scoring import recalculate_item_scores
from riskapp_server.db.session import RiskStatus, Role, User, get_db, utcnow
from riskapp_server.schemas.models import AssessmentIn, ScoreReportOut


def _set_payload_schema(
    endpoint: Callable[..., Any], schema: type[BaseModel]
) -> None:
    """Install a concrete request model before FastAPI inspects an endpoint."""
    cast(FunctionType, endpoint).__annotations__["payload"] = schema


def create_crud_router(
    *,
    prefix: str,
    tags: Sequence[str | Enum],
    Model: type[Any],
    CreateSchema: type[BaseModel],
    UpdateSchema: type[BaseModel],
    OutSchema: type[BaseModel],
    fixed_type: str | None = None,
    AssessmentModel: type[Any] | None = None,
    AssessmentOutSchema: type[BaseModel] | None = None,
) -> APIRouter:
    """Create crud router."""
    r = APIRouter(tags=list(tags))

    def create_obj(
        project_id: uuid.UUID,
        payload: BaseModel,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> Any:
        require_min_role(db, project_id, user.id, min_role=Role.member)
        return create_item(db, user.id, project_id, payload, Model)

    _set_payload_schema(create_obj, CreateSchema)
    r.add_api_route(
        f"/projects/{{project_id}}/{prefix}",
        create_obj,
        methods=["POST"],
        response_model=OutSchema,
        status_code=201,
    )

    @r.get(
        f"/projects/{{project_id}}/{prefix}",
        response_model=GenericAlias(list, OutSchema),
    )
    def list_objs(
        project_id: uuid.UUID,
        filters: ItemFilterParams = Depends(),
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> Sequence[Any]:

        ensure_member(db, project_id, user.id)
        f = vars(filters)
        if fixed_type:
            f["item_type"] = fixed_type
        return list_items(db, project_id, Model, f)

    @r.get(f"/projects/{{project_id}}/{prefix}/export.csv")
    def export_csv(
        project_id: uuid.UUID,
        filters: ItemFilterParams = Depends(),
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> StreamingResponse:
        """Export the current filtered page as CSV."""
        ensure_member(db, project_id, user.id)
        f = vars(filters)
        if fixed_type:
            f["item_type"] = fixed_type

        base_where = [Model.project_id == project_id]
        # Exclude soft-deleted rows when the model has is_deleted.
        if hasattr(Model, "is_deleted"):
            base_where.append(Model.is_deleted.is_(False))

        stmt = apply_item_filters(
            select(Model).where(*base_where),
            Model,
            search=f.get("search"),
            item_type=f.get("item_type"),
            min_score=f.get("min_score"),
            max_score=f.get("max_score"),
            status=f.get("status"),
            category=f.get("category"),
            owner_user_id=f.get("owner_user_id"),
            owner_unassigned=bool(f.get("owner_unassigned")),
            from_date=f.get("from_date"),
            to_date=f.get("to_date"),
        ).order_by(Model.score.desc(), Model.title.asc())

        # `limit`/`offset` are often Optional[int] in query models.
        raw_limit = f.get("limit", 100)
        raw_offset = f.get("offset", 0)
        limit = int(raw_limit) if raw_limit is not None else 100
        offset = int(raw_offset) if raw_offset is not None else 0
        if limit:
            stmt = stmt.limit(limit)
        if offset:
            stmt = stmt.offset(offset)

        raw_cols = [
            "id",
            "type" if hasattr(Model, "type") else None,
            "code",
            "title",
            "category",
            "status",
            "probability",
            "impact",
            "score",
            "owner_user_id",
            "identified_at",
            "updated_at",
            "version",
            "is_deleted",
        ]
        cols = [c for c in raw_cols if c is not None]

        def rows() -> Iterator[bytes]:
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(cols)
            yield buf.getvalue().encode()
            buf.seek(0)
            buf.truncate(0)

            for obj in db.execute(stmt).scalars():
                w.writerow([safe_csv_cell(getattr(obj, c, "")) for c in cols])
                yield buf.getvalue().encode()
                buf.seek(0)
                buf.truncate(0)

        headers = {"Content-Disposition": f"attachment; filename={prefix}_export.csv"}
        return StreamingResponse(rows(), media_type="text/csv", headers=headers)

    def update_obj(
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        payload: BaseModel,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> Any:
        status_val = getattr(payload, "status", None)
        status_s = str(getattr(status_val, "value", status_val) or "").lower().strip()
        min_role = Role.manager if status_s == RiskStatus.deleted.value else Role.member
        require_min_role(db, project_id, user.id, min_role=min_role)
        return update_item(
            db, project_id, item_id, payload, Model, item_type=fixed_type
        )

    _set_payload_schema(update_obj, UpdateSchema)
    r.add_api_route(
        f"/projects/{{project_id}}/{prefix}/{{item_id}}",
        update_obj,
        methods=["PATCH"],
        response_model=OutSchema,
    )

    @r.delete(
        f"/projects/{{project_id}}/{prefix}/{{item_id}}",
        status_code=204,
        response_class=Response,
    )
    def delete_obj(
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> Response:

        require_min_role(db, project_id, user.id, min_role=Role.manager)
        delete_item(db, project_id, item_id, Model, item_type=fixed_type)
        return Response(status_code=204)

    @r.get(f"/projects/{{project_id}}/{prefix}/report", response_model=ScoreReportOut)
    def obj_report(
        project_id: uuid.UUID,
        filters: ItemFilterParams = Depends(),
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> ScoreReportOut:
        ensure_member(db, project_id, user.id)
        f = vars(filters)
        if fixed_type:
            f["item_type"] = fixed_type
        return generate_report(db, project_id, Model, f)

    if AssessmentModel and AssessmentOutSchema:
        parent_id_field = f"{Model.__name__.lower()}_id"

        @r.get(
            f"/projects/{{project_id}}/{prefix}/{{item_id}}/assessments",
            response_model=GenericAlias(list, AssessmentOutSchema),
        )
        def list_assessments(
            project_id: uuid.UUID,
            item_id: uuid.UUID,
            db: Session = Depends(get_db),
            user: User = Depends(get_current_user),
        ) -> Sequence[Any]:
            ensure_member(db, project_id, user.id)
            if not db.execute(
                select(Model.id).where(
                    Model.project_id == project_id,
                    Model.id == item_id,
                    Model.is_deleted.is_(False),
                    *(
                        [Model.type == fixed_type]
                        if fixed_type and hasattr(Model, "type")
                        else []
                    ),
                )
            ).first():
                raise HTTPException(status_code=404, detail="Item not found")
            return (
                db.execute(
                    select(AssessmentModel)
                    .where(
                        getattr(AssessmentModel, parent_id_field) == item_id,
                        AssessmentModel.is_deleted.is_(False),
                    )
                    .order_by(AssessmentModel.updated_at.desc())
                )
                .scalars()
                .all()
            )

        @r.put(
            f"/projects/{{project_id}}/{prefix}/{{item_id}}/assessment",
            response_model=AssessmentOutSchema,
        )
        def upsert_my_assessment(
            project_id: uuid.UUID,
            item_id: uuid.UUID,
            payload: AssessmentIn,
            db: Session = Depends(get_db),
            user: User = Depends(get_current_user),
        ) -> Any:
            """Upsert the calling user's assessment for a scored item."""
            require_min_role(db, project_id, user.id, min_role=Role.member)
            if not db.execute(
                select(Model.id).where(
                    Model.id == item_id,
                    Model.project_id == project_id,
                    Model.is_deleted.is_(False),
                    *(
                        [Model.type == fixed_type]
                        if fixed_type and hasattr(Model, "type")
                        else []
                    ),
                )
            ).first():
                raise HTTPException(status_code=404, detail="Item not found")

            assessment = (
                db.execute(
                    select(AssessmentModel).where(
                        getattr(AssessmentModel, parent_id_field) == item_id,
                        AssessmentModel.assessor_user_id == user.id,
                    )
                )
                .scalars()
                .first()
            )

            now = utcnow()
            if not assessment:
                if payload.base_version != 0:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "reason": "version_mismatch",
                            "server_version": None,
                        },
                    )
                assessment = AssessmentModel(
                    id=uuid.uuid4(),
                    **{parent_id_field: item_id},
                    assessor_user_id=user.id,
                    created_at=now,
                    updated_at=now,
                    version=1,
                    is_deleted=False,
                )
                db.add(assessment)
            else:
                assessment = claim_base_version(
                    db,
                    AssessmentModel,
                    (
                        getattr(AssessmentModel, parent_id_field) == item_id,
                        AssessmentModel.assessor_user_id == user.id,
                    ),
                    payload.base_version,
                )

            assessment.probability = payload.probability
            assessment.impact = payload.impact
            assessment.notes = payload.notes
            assessment.is_deleted = False
            assessment.updated_at = now

            recalculate_item_scores(assessment)
            db.commit()
            db.refresh(assessment)
            return assessment

    return r
