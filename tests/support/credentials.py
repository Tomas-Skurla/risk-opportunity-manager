"""Generated test credentials, so no test depends on a hardcoded password."""

from __future__ import annotations

import itertools
import secrets
import string

_ALPHABET = string.ascii_letters + string.digits + "!@#%^*-_=+"
_email_numbers = itertools.count(1)


def new_email(prefix: str = "user") -> str:
    """Return a unique, readable address such as ``user-3@example.com``."""
    return f"{prefix}-{next(_email_numbers)}@example.com"


def new_password(length: int = 20) -> str:
    """Return a random password that satisfies the server's real password policy."""
    # Imported here so it follows isolated_app_factory's module reloads.
    # pylint: disable-next=import-outside-toplevel
    from riskapp_server.core.password_policy import validate_password

    while True:
        candidate = "".join(secrets.choice(_ALPHABET) for _ in range(length))
        if not validate_password(candidate):
            return candidate
