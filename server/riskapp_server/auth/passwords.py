"""Password hashing with Argon2id."""

from __future__ import annotations

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

# OWASP's minimum Argon2id profile: 19 MiB memory, two iterations, one lane.
# Parameters are encoded into every stored hash, so they can be raised later and
# ``password_needs_rehash`` will upgrade users at their next successful login.
_PASSWORD_HASHER = PasswordHasher(
    time_cost=2,
    memory_cost=19 * 1024,
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)


def hash_pw(password: str) -> str:
    """Hash a new password with Argon2id."""
    return _PASSWORD_HASHER.hash(password)


def verify_pw(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored Argon2 hash."""
    try:
        return _PASSWORD_HASHER.verify(stored_hash, password)
    except InvalidHashError, VerificationError:
        return False


def password_needs_rehash(stored_hash: str) -> bool:
    """Return whether a successfully verified hash uses outdated parameters."""
    try:
        return _PASSWORD_HASHER.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return False
