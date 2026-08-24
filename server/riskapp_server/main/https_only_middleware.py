from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from riskapp_server.core.config import ENFORCE_HTTPS, TRUST_X_FORWARDED_PROTO


class HttpsOnlyMiddleware(BaseHTTPMiddleware):
    """Reject plain HTTP when HTTPS is required."""

    async def dispatch(self, request, call_next):
        if not ENFORCE_HTTPS:
            return await call_next(request)

        scheme = request.url.scheme
        if TRUST_X_FORWARDED_PROTO:
            xf = request.headers.get("x-forwarded-proto")
            if xf:
                scheme = xf.split(",", 1)[0].strip().lower()

        if scheme != "https":
            return JSONResponse(status_code=400, content={"detail": "HTTPS required"})
        return await call_next(request)
