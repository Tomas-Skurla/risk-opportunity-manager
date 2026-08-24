"""Role helpers used by the client UI."""

from __future__ import annotations

from typing import Final

# Role names are also stored in tokens and local state.
ROLE_RANK: Final[dict[str, int]] = {"viewer": 1, "member": 2, "manager": 3, "admin": 4}

# Kept for older imports.
UNKNOWN_ROLE_RANK: Final[int] = 999


def normalize_role(role: str | None) -> str:
    """Normalize a role string for comparisons."""
    return (role or "").strip().lower()


def is_known_role(role: str | None) -> bool:
    """Return True if `role` is one of the known role keys."""
    return normalize_role(role) in ROLE_RANK


def role_at_least(role: str | None, min_role: str | None) -> bool:
    """Return True when role is at least min_role."""
    role_key = normalize_role(role)
    min_key = normalize_role(min_role)
    min_rank = ROLE_RANK.get(min_key)
    if min_rank is None:
        return False
    return ROLE_RANK.get(role_key, 0) >= min_rank
