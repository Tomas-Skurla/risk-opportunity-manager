from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from riskapp_server.auth.service import (
    create_access_token,
    hash_pw,
    issue_refresh_token,
    rotate_refresh_token,
    verify_pw,
)
from riskapp_server.core.config import (
    ACCESS_TOKEN_MINUTES,
    LOGIN_RATE_LIMIT_PER_MINUTE,
    LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    RATE_LIMIT_MAX_KEYS,
)
from riskapp_server.core.password_policy import validate_password
from riskapp_server.core.rate_limit import InMemorySlidingWindowLimiter
from riskapp_server.db.session import User, get_db
from riskapp_server.schemas.models import RefreshIn, RegisterIn, TokenOut

router = APIRouter(tags=["auth"])


_login_limiter = InMemorySlidingWindowLimiter(
    limit=LOGIN_RATE_LIMIT_PER_MINUTE,
    window_s=LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    max_keys=RATE_LIMIT_MAX_KEYS,
)
_register_limiter = InMemorySlidingWindowLimiter(
    limit=5,
    window_s=LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    max_keys=RATE_LIMIT_MAX_KEYS,
)
_refresh_limiter = InMemorySlidingWindowLimiter(
    limit=30,
    window_s=LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    max_keys=RATE_LIMIT_MAX_KEYS,
)

# Used to keep password verification work roughly the same when the user is
# missing.
_DUMMY_HASH = hash_pw("dummy-timing-pad-value")


@router.post("/register", status_code=201, response_model=TokenOut)
def register(
    payload: RegisterIn,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    client_ip = (request.client.host if request.client else "") or "unknown"
    allowed, retry_after = _register_limiter.check(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many registration attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    email = str(payload.email).lower()
    if db.execute(select(User.id).where(User.email == email)).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    issues = validate_password(payload.password)
    if issues:
        raise HTTPException(status_code=400, detail={"password": issues})

    user = User(email=email, password_hash=hash_pw(payload.password), is_active=True)
    db.add(user)
    try:
        # Flush first so the user id exists, then persist the account and its
        # initial refresh token in one transaction. The IntegrityError handler
        # also closes the duplicate-email race between the pre-check and insert.
        db.flush()
        access = create_access_token(str(user.id))
        refresh = issue_refresh_token(db, user.id, commit=False)
        db.commit()
        db.refresh(user)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered") from exc
    return {
        "user_id": str(user.id),
        "access_token": access,
        "refresh_token": refresh,
        "expires_in": int(ACCESS_TOKEN_MINUTES) * 60,
        "token_type": "bearer",
    }


@router.post("/login", response_model=TokenOut)
def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    client_ip = (request.client.host if request.client else "") or "unknown"
    email = form.username.lower()

    allowed, retry_after = _login_limiter.check(f"{client_ip}:{email}")
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    user = db.execute(select(User).where(User.email == email)).scalars().first()
    if not user or not user.is_active:
        # Keep the code path similar when the email is unknown.
        verify_pw(form.password, _DUMMY_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    if not verify_pw(form.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

    access = create_access_token(str(user.id))
    refresh = issue_refresh_token(db, user.id)
    return {
        "user_id": str(user.id),
        "access_token": access,
        "refresh_token": refresh,
        "expires_in": int(ACCESS_TOKEN_MINUTES) * 60,
        "token_type": "bearer",
    }


@router.post("/refresh", response_model=TokenOut)
def refresh(
    payload: RefreshIn,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    client_ip = (request.client.host if request.client else "") or "unknown"
    allowed, retry_after = _refresh_limiter.check(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many refresh attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )
    new_refresh, user_id = rotate_refresh_token(db, payload.refresh_token)
    access = create_access_token(str(user_id))
    return {
        "user_id": str(user_id),
        "access_token": access,
        "refresh_token": new_refresh,
        "expires_in": int(ACCESS_TOKEN_MINUTES) * 60,
        "token_type": "bearer",
    }
