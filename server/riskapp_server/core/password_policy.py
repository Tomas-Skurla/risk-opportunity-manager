"""Password policy validation for registration and reset flows."""

from __future__ import annotations

import re

from riskapp_server.core.config import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    PASSWORD_REQUIRE_DIGIT,
    PASSWORD_REQUIRE_LOWER,
    PASSWORD_REQUIRE_SYMBOL,
    PASSWORD_REQUIRE_UPPER,
)

_RE_UPPER = re.compile(r"[A-Z]")
_RE_LOWER = re.compile(r"[a-z]")
_RE_DIGIT = re.compile(r"[0-9]")
# Treat anything non-alnum as symbol.
_RE_SYMBOL = re.compile(r"[^A-Za-z0-9]")


def validate_password(password: str) -> list[str]:
    """Return a list of policy violations (empty list => valid)."""

    p = password or ""
    issues: list[str] = []

    if len(p) < int(PASSWORD_MIN_LENGTH):
        issues.append(f"Password must be at least {PASSWORD_MIN_LENGTH} characters")
    if len(p) > int(PASSWORD_MAX_LENGTH):
        issues.append(f"Password must be at most {PASSWORD_MAX_LENGTH} characters")

    if PASSWORD_REQUIRE_UPPER and not _RE_UPPER.search(p):
        issues.append("Password must include an uppercase letter")
    if PASSWORD_REQUIRE_LOWER and not _RE_LOWER.search(p):
        issues.append("Password must include a lowercase letter")
    if PASSWORD_REQUIRE_DIGIT and not _RE_DIGIT.search(p):
        issues.append("Password must include a digit")
    if PASSWORD_REQUIRE_SYMBOL and not _RE_SYMBOL.search(p):
        issues.append("Password must include a symbol")

    return issues
