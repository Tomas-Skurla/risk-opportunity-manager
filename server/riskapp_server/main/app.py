from __future__ import annotations

import inspect
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import cast

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from riskapp_server.api.routers.actions import router as actions_router
from riskapp_server.api.routers.auth_routes import router as auth_router
from riskapp_server.api.routers.helpdesk import router as helpdesk_router
from riskapp_server.api.routers.items import router as items_router
from riskapp_server.api.routers.matrix import router as matrix_router
from riskapp_server.api.routers.projects import router as projects_router
from riskapp_server.api.routers.snapshots import router as snapshots_router
from riskapp_server.api.routers.sync_routes import router as sync_router
from riskapp_server.api.routers.users import router as users_router
from riskapp_server.auth.service import hash_pw
from riskapp_server.core.config import (
    ALLOWED_HOSTS,
    CORS_ORIGINS,
    GZIP_ENABLED,
    GZIP_MINIMUM_SIZE,
    INITIAL_SUPERUSER_EMAIL,
    INITIAL_SUPERUSER_PASSWORD,
    MAX_REQUEST_BODY_BYTES,
    RISKAPP_LOG_FORMAT,
    RISKAPP_LOG_LEVEL,
    validate_runtime_config,
)
from riskapp_server.core.logging_config import configure_server_logging
from riskapp_server.core.password_policy import validate_password
from riskapp_server.db import session as db_session
from riskapp_server.db.session import engine, get_db, init_db
from riskapp_server.main.http_middleware import (
    RequestBodyLimitMiddleware,
    RequestCorrelationMiddleware,
    SecurityHeadersMiddleware,
)
from riskapp_server.main.https_only_middleware import HttpsOnlyMiddleware

logger = logging.getLogger(__name__)

ROUTERS = (
    auth_router,
    users_router,
    projects_router,
    items_router,
    actions_router,
    matrix_router,
    snapshots_router,
    helpdesk_router,
    sync_router,
)


async def _run_initializer(initializer: Callable[[], object]) -> None:
    """Run a synchronous initializer or await an asynchronous one."""
    result = initializer()
    if inspect.isawaitable(result):
        await result


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        await _run_initializer(cast(Callable[[], object], init_db))

        if INITIAL_SUPERUSER_EMAIL and INITIAL_SUPERUSER_PASSWORD:
            issues = validate_password(INITIAL_SUPERUSER_PASSWORD)
            if issues:
                raise RuntimeError(
                    "INITIAL_SUPERUSER_PASSWORD does not satisfy password policy: "
                    + "; ".join(issues)
                )

            with db_session.SessionLocal() as db:
                email = str(INITIAL_SUPERUSER_EMAIL).lower()
                u = (
                    db.execute(
                        select(db_session.User).where(db_session.User.email == email)
                    )
                    .scalars()
                    .first()
                )
                if not u:
                    u = db_session.User(
                        email=email,
                        password_hash=hash_pw(INITIAL_SUPERUSER_PASSWORD),
                        is_active=True,
                        is_superuser=True,
                    )
                    db.add(u)
                else:
                    u.is_superuser = True
                    if not u.is_active:
                        u.is_active = True
                db.commit()

        yield
    except Exception:
        logger.exception("Application startup failed")
        raise
    finally:
        try:
            engine.dispose()
        # Shutdown cleanup must never hide the original startup/runtime failure.
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("DB engine dispose failed")


def create_app() -> FastAPI:
    validate_runtime_config()
    configure_server_logging(
        level=RISKAPP_LOG_LEVEL,
        output_format=RISKAPP_LOG_FORMAT,
    )
    application = FastAPI(
        title="RiskApp API",
        summary="Offline-first risk and opportunity management API",
        version="0.1.0",
        lifespan=lifespan,
    )

    @application.exception_handler(Exception)
    async def unhandled_error(request: Request, _exc: Exception) -> JSONResponse:
        """Return a safe error body while preserving the request correlation ID."""
        correlation_id = getattr(request.state, "request_id", "")
        headers = {"X-Request-ID": correlation_id} if correlation_id else None
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
            headers=headers,
        )

    application.add_middleware(
        RequestBodyLimitMiddleware, max_bytes=MAX_REQUEST_BODY_BYTES
    )
    application.add_middleware(HttpsOnlyMiddleware)
    if CORS_ORIGINS:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
            expose_headers=["X-Request-ID"],
        )
    if GZIP_ENABLED:
        application.add_middleware(GZipMiddleware, minimum_size=GZIP_MINIMUM_SIZE)
    if ALLOWED_HOSTS:
        application.add_middleware(
            TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS
        )
    # Added last so rejected requests receive the same defensive headers.
    application.add_middleware(SecurityHeadersMiddleware)
    # Outermost application middleware: early rejections are correlated too.
    application.add_middleware(RequestCorrelationMiddleware)
    for r in ROUTERS:
        application.include_router(r)

    @application.get("/health", tags=["ops"], response_model=None)
    def health_check(
        db: Session = Depends(get_db),  # noqa: B008
    ) -> dict[str, str] | JSONResponse:
        try:
            db.execute(text("SELECT 1"))
            return {"status": "ok", "db": "ok"}
        # Any database/driver failure makes the health result degraded.
        except Exception:  # pylint: disable=broad-exception-caught
            return JSONResponse(
                status_code=503,
                content={"status": "degraded", "db": "unreachable"},
            )

    return application


app = create_app()
