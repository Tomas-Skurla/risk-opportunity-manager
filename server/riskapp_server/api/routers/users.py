from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from riskapp_server.auth.passwords import verify_pw
from riskapp_server.auth.service import (
    get_current_user,
    hash_bearer_secret,
    set_user_password,
)
from riskapp_server.core.config import (
    PASSWORD_RESET_RATE_LIMIT_PER_HOUR,
    PASSWORD_RESET_RETURN_TOKEN,
    PASSWORD_RESET_TOKEN_MINUTES,
    RATE_LIMIT_MAX_KEYS,
)
from riskapp_server.core.rate_limit import InMemorySlidingWindowLimiter
from riskapp_server.db.session import PasswordResetToken, User, get_db, utcnow
from riskapp_server.schemas.models import (
    ChangePasswordIn,
    PasswordResetConfirmIn,
    PasswordResetRequestIn,
    UserOut,
)

router = APIRouter(tags=["users"])

_reset_limiter = InMemorySlidingWindowLimiter(
    limit=PASSWORD_RESET_RATE_LIMIT_PER_HOUR,
    window_s=60 * 60,
    max_keys=RATE_LIMIT_MAX_KEYS,
)


@router.get("/users/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/users/me/change-password", status_code=204)
def change_password(
    payload: ChangePasswordIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    if not verify_pw(payload.old_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid current password")
    set_user_password(db, user, payload.new_password)
    return None


@router.post("/password-reset/request")
def request_password_reset(
    payload: PasswordResetRequestIn,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    # Return the same response whether the account exists or not.
    email = str(payload.email).lower()
    client_ip = (request.client.host if request.client else "") or "unknown"
    allowed, retry_after = _reset_limiter.check(f"{client_ip}:{email}")
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many password reset attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    user = db.execute(select(User).where(User.email == email)).scalars().first()

    token_raw: str | None = None
    if user and user.is_active:
        now = utcnow()
        # Keep at most one usable reset token per account.
        for existing in (
            db.query(PasswordResetToken)
            .filter(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
            .all()
        ):
            existing.used_at = now
        token_raw = secrets.token_urlsafe(48)
        pr = PasswordResetToken(
            user_id=user.id,
            token_hash=hash_bearer_secret(token_raw),
            created_at=now,
            expires_at=now + timedelta(minutes=int(PASSWORD_RESET_TOKEN_MINUTES)),
            used_at=None,
            request_ip=client_ip,
        )
        db.add(pr)
        db.commit()

    # Local development can return the token directly.
    if token_raw and PASSWORD_RESET_RETURN_TOKEN:
        return {"detail": "Password reset token created", "token": token_raw}
    return {"detail": "If the account exists, reset instructions were issued."}


@router.post("/password-reset/confirm", status_code=204)
def confirm_password_reset(
    payload: PasswordResetConfirmIn, db: Session = Depends(get_db)
) -> None:
    now = utcnow()
    token_hash = hash_bearer_secret(payload.token)
    pr: PasswordResetToken | None = (
        db.execute(
            select(PasswordResetToken)
            .where(PasswordResetToken.token_hash == token_hash)
            .with_for_update()
        )
        .scalars()
        .one_or_none()
    )
    if not pr or pr.used_at is not None or pr.expires_at <= now:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user = db.get(User, pr.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=400, detail="Account is inactive")

    set_user_password(db, user, payload.new_password, commit=False)
    pr.used_at = now
    db.add(pr)
    db.commit()
    return None
