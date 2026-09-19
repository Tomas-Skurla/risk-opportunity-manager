"""Authentication helpers."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Never, cast

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from riskapp_server.auth import passwords as password_hashing
from riskapp_server.core.config import (
    ACCESS_TOKEN_MINUTES,
    ALGORITHM,
    ALLOW_INSECURE_DEFAULT_SECRET,
    REFRESH_TOKEN_DAYS,
    REFRESH_TOKEN_REUSE_GRACE_SECONDS,
    SECRET_KEY,
    TOKEN_HASH_KEY,
    validate_runtime_config,
)
from riskapp_server.db.session import RefreshToken, User, get_db, utcnow

logger = logging.getLogger("riskapp_server.auth")

# Backward-compatible exports for existing callers of auth.service.
hash_pw = password_hashing.hash_pw
verify_pw = password_hashing.verify_pw
password_needs_rehash = password_hashing.password_needs_rehash

validate_runtime_config()
# "change-me" is a sentinel that is rejected outside local development.
if SECRET_KEY == "change-me" and ALLOW_INSECURE_DEFAULT_SECRET:  # noqa: S105
    logger.warning("Using the default SECRET_KEY; do not use this outside local dev.")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")


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
    """Hash a bearer token with a key independent from JWT signing."""
    key = TOKEN_HASH_KEY or SECRET_KEY
    return hmac.new(
        key.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _new_refresh_token(
    user_id: uuid.UUID, now: datetime
) -> tuple[str, RefreshToken]:
    """Build a refresh-token row whose id is available before it is flushed."""
    raw = secrets.token_urlsafe(48)
    return raw, RefreshToken(
        id=uuid.uuid4(),
        user_id=user_id,
        token_hash=hash_bearer_secret(raw),
        issued_at=now,
        expires_at=now + timedelta(days=int(REFRESH_TOKEN_DAYS)),
        revoked_at=None,
        replaced_by_id=None,
    )

def issue_refresh_token(db: Session, user_id: uuid.UUID, *, commit: bool = True) -> str:
    raw, rt = _new_refresh_token(user_id, utcnow())
    db.add(rt)
    if commit:
        db.commit()
    else:
        db.flush()
    return raw


def _begin_refresh_transaction(db: Session) -> None:
    """Reserve SQLite's writer before inspecting a token replacement chain."""
    bind = db.get_bind()
    if getattr(getattr(bind, "dialect", None), "name", None) != "sqlite":
        return
    if db.in_transaction():
        # Rotation owns its transaction and has always committed on success.
        db.rollback()
    db.connection().exec_driver_sql("BEGIN IMMEDIATE")


def _claim_refresh_token(
    db: Session,
    token_id: uuid.UUID,
    replacement_id: uuid.UUID,
    now: datetime,
) -> bool:
    """Revoke and link one still-active token with one conditional update."""
    result = cast(
        CursorResult[Any],
        db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.id == token_id,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.replaced_by_id.is_(None),
                RefreshToken.expires_at > now,
            )
            .values(revoked_at=now, replaced_by_id=replacement_id)
            .execution_options(synchronize_session=False)
        ),

    )
    return result.rowcount == 1


def _locked_user_refresh_tokens(
    db: Session, user_id: uuid.UUID
) -> list[RefreshToken]:
    """Load one user's token graph in deterministic lock order."""
    tokens = list(
        db.execute(
            select(RefreshToken)
            .where(RefreshToken.user_id == user_id)
            .order_by(RefreshToken.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalars()
    )
    by_id = {token.id: token for token in tokens}

    # Under PostgreSQL READ COMMITTED, a child inserted by a rotation while the
    # first locking SELECT waited may not be part of that statement's snapshot.
    # Its parent's replacement id is visible after the wait, so follow and lock
    # any such links until the current tail is reached. A locked tail cannot be
    # advanced concurrently. SQLite already holds a writer reservation here.
    missing_ids = {
        token.replaced_by_id
        for token in tokens
        if token.replaced_by_id is not None and token.replaced_by_id not in by_id
    }
    while missing_ids:
        linked_tokens = list(
            db.execute(
                select(RefreshToken)
                .where(
                    RefreshToken.user_id == user_id,
                    RefreshToken.id.in_(missing_ids),
                )
                .order_by(RefreshToken.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).scalars()
        )
        if not linked_tokens:
            break
        for linked_token in linked_tokens:
            by_id[linked_token.id] = linked_token
        missing_ids = {
            token.replaced_by_id
            for token in linked_tokens
            if token.replaced_by_id is not None
            and token.replaced_by_id not in by_id
        }
    return list(by_id.values())


def _refresh_family_ids(
    tokens: list[RefreshToken], token_id: uuid.UUID
) -> set[uuid.UUID]:
    """Return the connected replacement family containing ``token_id``."""
    by_id = {token.id: token for token in tokens}
    if token_id not in by_id:
        return set()
    neighbors: dict[uuid.UUID, set[uuid.UUID]] = {
        candidate_id: set() for candidate_id in by_id
    }
    for token in tokens:
        replacement_id = token.replaced_by_id
        if replacement_id is None or replacement_id not in by_id:
            continue
        neighbors[token.id].add(replacement_id)
        neighbors[replacement_id].add(token.id)

    family: set[uuid.UUID] = set()
    remaining = [token_id]
    while remaining:
        candidate_id = remaining.pop()
        if candidate_id in family:
            continue
        family.add(candidate_id)
        remaining.extend(neighbors[candidate_id] - family)
    return family


def _invalid_refresh_token(db: Session) -> Never:
    db.rollback()
    raise HTTPException(status_code=401, detail="Invalid refresh token")


def _recover_or_revoke_refresh_family(
    db: Session,
    token_id: uuid.UUID,
    user_id: uuid.UUID,
    now: datetime,
) -> tuple[str, uuid.UUID] | None:
    """Recover one lost rotation response or revoke a reused token family."""
    tokens = _locked_user_refresh_tokens(db, user_id)
    by_id = {token.id: token for token in tokens}
    token = by_id.get(token_id)
    if token is None or token.revoked_at is None:
        db.rollback()
        return None

    replacement_id = token.replaced_by_id
    replacement = (
        by_id.get(replacement_id) if replacement_id is not None else None
    )
    grace_age = (now - token.revoked_at).total_seconds()
    grace_eligible = (
        REFRESH_TOKEN_REUSE_GRACE_SECONDS > 0
        and 0 <= grace_age <= REFRESH_TOKEN_REUSE_GRACE_SECONDS
        and replacement is not None
        and replacement.revoked_at is None
        and replacement.replaced_by_id is None
        and replacement.expires_at > now
    )
    if grace_eligible and replacement is not None:
        new_raw, new_token = _new_refresh_token(user_id, now)
        if not _claim_refresh_token(db, replacement.id, new_token.id, now):
            db.rollback()
            return None
        db.add(new_token)
        db.commit()
        return new_raw, user_id

    family_ids = _refresh_family_ids(tokens, token_id)
    result = cast(
        CursorResult[Any],
        db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.id.in_(family_ids),
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
            .execution_options(synchronize_session=False)
        ),
    )
    revoked_count = max(int(result.rowcount or 0), 0)
    db.commit()

    logger.warning(
        "Refresh-token reuse detected; revoked %d active token(s) in one family",
        revoked_count,
        extra={"user_id": str(user_id)},
    )
    raise HTTPException(status_code=401, detail="Invalid refresh token")


def rotate_refresh_token(db: Session, raw_refresh_token: str) -> tuple[str, uuid.UUID]:
    token_hash = hash_bearer_secret(raw_refresh_token)
    for _attempt in range(3):
        _begin_refresh_transaction(db)
        now = utcnow()
        rt: RefreshToken | None = db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        ).scalar_one_or_none()
        if rt is None:
            _invalid_refresh_token(db)

        user = db.get(User, rt.user_id)
        if user is None or not user.is_active:
            _invalid_refresh_token(db)

        if rt.revoked_at is not None:
            recovered = _recover_or_revoke_refresh_family(
                db, rt.id, rt.user_id, now
            )
            if recovered is not None:
                return recovered
            continue
        if rt.expires_at <= now:
            _invalid_refresh_token(db)

        new_raw, new_token = _new_refresh_token(rt.user_id, now)
        if not _claim_refresh_token(db, rt.id, new_token.id, now):
            db.rollback()
            continue
        db.add(new_token)
        db.commit()
        return new_raw, rt.user_id

    _invalid_refresh_token(db)


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
