"""Password hashing and legacy-hash migration helpers."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac

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

_PBKDF2_MIN_ITERS = 100_000
_PBKDF2_MAX_ITERS = 2_000_000


def hash_pw(password: str) -> str:
    """Hash a new password with Argon2id."""
    return _PASSWORD_HASHER.hash(password)


def _verify_legacy_pbkdf2(password: str, stored_hash: str) -> bool:
    """Verify the PBKDF2 format used before the Argon2id migration."""
    try:
        algo, iters_s, salt_b64, hash_b64 = stored_hash.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iters = int(iters_s)
        # A corrupted or attacker-controlled hash must not turn login into an
        # unbounded CPU operation.
        if not _PBKDF2_MIN_ITERS <= iters <= _PBKDF2_MAX_ITERS:
            return False
        salt = base64.b64decode(salt_b64, validate=True)
        expected = base64.b64decode(hash_b64, validate=True)
        calculated = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt, iters
        )
        return hmac.compare_digest(calculated, expected)
    except (ValueError, TypeError, binascii.Error):
        return False


def verify_pw(password: str, stored_hash: str) -> bool:
    """Verify either a current Argon2 hash or a legacy PBKDF2 hash."""
    if stored_hash.startswith("$argon2"):
        try:
            return _PASSWORD_HASHER.verify(stored_hash, password)
        except (InvalidHashError, VerificationError):
            return False
    return _verify_legacy_pbkdf2(password, stored_hash)


def password_needs_rehash(stored_hash: str) -> bool:
    """Return whether a successfully verified hash should be replaced."""
    if stored_hash.startswith("pbkdf2_sha256$"):
        return True
    if not stored_hash.startswith("$argon2"):
        return False
    try:
        return _PASSWORD_HASHER.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return False
