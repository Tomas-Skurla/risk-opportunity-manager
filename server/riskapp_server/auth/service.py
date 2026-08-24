"""Authentication helpers."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import UTC, timedelta

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from riskapp_server.core.config import (
    ACCESS_TOKEN_MINUTES,
    ALGORITHM,
    ALLOW_INSECURE_DEFAULT_SECRET,
    PBKDF2_ITERS,
    REFRESH_TOKEN_DAYS,
    SECRET_KEY,
    validate_runtime_config,
)
from riskapp_server.db.session import RefreshToken, User, get_db, utcnow

logger = logging.getLogger("riskapp_server.auth")

validate_runtime_config()
if SECRET_KEY == "change-me" and ALLOW_INSECURE_DEFAULT_SECRET:
    logger.warning("Using the default SECRET_KEY; do not use this outside local dev.")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")


def hash_pw(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERS)
    return f"pbkdf2_sha256${PBKDF2_ITERS}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_pw(password: str, stored_hash: str) -> bool:
    try:
        algo, iters_s, salt_b64, hash_b64 = stored_hash.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iters = int(iters_s)
        # A corrupted or attacker-controlled hash must not turn login into an
        # unbounded CPU operation.
        if not 100_000 <= iters <= 2_000_000:
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iters)
        return hmac.compare_digest(dk, expected)
    except (ValueError, TypeError, binascii.Error):
        return False


def create_access_token(user_id: str) -> str:
    now_dt = utcnow().replace(tzinfo=UTC)
    exp_dt = now_dt + timedelta(minutes=ACCESS_TOKEN_MINUTES)
    exp = int(exp_dt.timestamp())
    iat = int(now_dt.timestamp())
    return jwt.encode(
        {
            "sub": user_id,
            "exp": exp,
            "iat": iat,
            "jti": uuid.uuid4().hex,
            "iss": "riskapp",
            "aud": "riskapp",
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


create_token = create_access_token


def hash_bearer_secret(raw: str) -> str:
    """Hash a bearer token before storing it."""
    return hmac.new(
        SECRET_KEY.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def issue_refresh_token(db: Session, user_id: uuid.UUID, *, commit: bool = True) -> str:
    raw = secrets.token_urlsafe(48)
    token_hash = hash_bearer_secret(raw)
    expires_at = utcnow() + timedelta(days=int(REFRESH_TOKEN_DAYS))
    rt = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        issued_at=utcnow(),
        expires_at=expires_at,
        revoked_at=None,
        replaced_by_id=None,
    )
    db.add(rt)
    if commit:
        db.commit()
    else:
        db.flush()
    return raw


def rotate_refresh_token(db: Session, raw_refresh_token: str) -> tuple[str, uuid.UUID]:
    now = utcnow()
    token_hash = hash_bearer_secret(raw_refresh_token)
    rt: RefreshToken | None = db.execute(
        select(RefreshToken)
        .where(RefreshToken.token_hash == token_hash)
        .with_for_update()
    ).scalar_one_or_none()
    if not rt or rt.revoked_at is not None or rt.expires_at <= now:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user = db.get(User, rt.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    rt.revoked_at = now
    new_raw = secrets.token_urlsafe(48)
    new_hash = hash_bearer_secret(new_raw)
    new_rt = RefreshToken(
        user_id=rt.user_id,
        token_hash=new_hash,
        issued_at=now,
        expires_at=now + timedelta(days=int(REFRESH_TOKEN_DAYS)),
        revoked_at=None,
        replaced_by_id=None,
    )
    db.add(new_rt)
    db.flush()
    rt.replaced_by_id = new_rt.id
    db.commit()
    return new_raw, rt.user_id


def revoke_user_refresh_tokens(db: Session, user_id: uuid.UUID) -> int:
    now = utcnow()
    q = (
        db.query(RefreshToken)
        .filter(RefreshToken.user_id == user_id)
        .filter(RefreshToken.revoked_at.is_(None))
    )
    count = 0
    for tok in q.all():
        tok.revoked_at = now
        count += 1
    db.flush()
    return count


def get_current_user(
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
) -> User:
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            audience="riskapp",
            issuer="riskapp",
        )
        sub = payload.get("sub")
        if not sub:
            raise ValueError
        user_id = uuid.UUID(sub)
    except (JWTError, ValueError) as exc:
        raise HTTPException(
            status_code=401,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=401,
            detail="Inactive user",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
