from __future__ import annotations

import inspect
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
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
from riskapp_server.core.config import (
    ALLOWED_HOSTS,
    CORS_ORIGINS,
    GZIP_ENABLED,
    GZIP_MINIMUM_SIZE,
    INITIAL_SUPERUSER_EMAIL,
    INITIAL_SUPERUSER_PASSWORD,
    MAX_REQUEST_BODY_BYTES,
    validate_runtime_config,
)
from riskapp_server.db.session import engine, get_db, init_db
from riskapp_server.main.http_middleware import (
    RequestBodyLimitMiddleware,
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


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        result = init_db()
        if inspect.isawaitable(result):
            await result

        if INITIAL_SUPERUSER_EMAIL and INITIAL_SUPERUSER_PASSWORD:
            from sqlalchemy import select

            from riskapp_server.auth.service import hash_pw
            from riskapp_server.core.password_policy import validate_password
            from riskapp_server.db.session import SessionLocal, User

            issues = validate_password(INITIAL_SUPERUSER_PASSWORD)
            if issues:
                raise RuntimeError(
                    "INITIAL_SUPERUSER_PASSWORD does not satisfy password policy: "
                    + "; ".join(issues)
                )

            with SessionLocal() as db:
                email = str(INITIAL_SUPERUSER_EMAIL).lower()
                u = (
                    db.execute(select(User).where(User.email == email))
                    .scalars()
                    .first()
                )
                if not u:
                    u = User(
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
        except Exception:
            logger.exception("DB engine dispose failed")


def create_app() -> FastAPI:
    validate_runtime_config()
    app = FastAPI(
        title="RiskApp API",
        summary="Offline-first risk and opportunity management API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=MAX_REQUEST_BODY_BYTES)
    app.add_middleware(HttpsOnlyMiddleware)
    if CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )
    if GZIP_ENABLED:
        app.add_middleware(GZipMiddleware, minimum_size=GZIP_MINIMUM_SIZE)
    if ALLOWED_HOSTS:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
    # Added last so rejected requests receive the same defensive headers.
    app.add_middleware(SecurityHeadersMiddleware)
    for r in ROUTERS:
        app.include_router(r)

    @app.get("/health", tags=["ops"])
    def health_check(db: Session = Depends(get_db)):  # noqa: B008
        try:
            db.execute(text("SELECT 1"))
            return {"status": "ok", "db": "ok"}
        except Exception:
            return JSONResponse(
                status_code=503,
                content={"status": "degraded", "db": "unreachable"},
            )

    return app


app = create_app()
