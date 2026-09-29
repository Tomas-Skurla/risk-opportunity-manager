"""Validated, environment-backed application settings.
The project intentionally keeps configuration dependency-free. Invalid values fail at import time with the setting name in the error instead of silently selecting an unsafe fallback.
"""

from __future__ import annotations

import os

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


class ConfigurationError(RuntimeError):
    """Raised when an environment setting is invalid or unsafe."""


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise ConfigurationError(
        f"{name} must be one of: {', '.join(sorted(_TRUE_VALUES | _FALSE_VALUES))}"
    )


def _env_int(
    name: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if minimum is not None and value < minimum:
        raise ConfigurationError(f"{name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigurationError(f"{name} must be at most {maximum}")
    return value


def _env_list(name: str, default: str = "") -> list[str]:
    return [
        part.strip() for part in os.getenv(name, default).split(",") if part.strip()
    ]


def _env_choice(name: str, default: str, choices: set[str]) -> str:
    """Read a case-insensitive setting constrained to explicit values."""
    value = os.getenv(name, default).strip().lower()
    if value not in choices:
        raise ConfigurationError(
            f"{name} must be one of: {', '.join(sorted(choices))}"
        )
    return value


def _optional_env(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None

RISKAPP_LOG_LEVEL: str = _env_choice(
    "RISKAPP_LOG_LEVEL",
    "info",
    {"critical", "error", "warning", "info", "debug"},
).upper()
RISKAPP_LOG_FORMAT: str = _env_choice(
    "RISKAPP_LOG_FORMAT", "plain", {"plain", "json"}
)

ENV: str = _env_choice(
    "ENV",
    "development",
    {"development", "production", "test"},
)

SECRET_KEY: str = os.getenv("SECRET_KEY", "").strip()
# Refresh/password-reset tokens are HMACed with this explicitly supplied key.
# Both keys are required in every environment.
TOKEN_HASH_KEY: str = os.getenv("TOKEN_HASH_KEY", "").strip()
ALGORITHM: str = os.getenv("ALGORITHM", "HS256").strip().upper()

ACCESS_TOKEN_MINUTES: int = _env_int(
    "ACCESS_TOKEN_MINUTES", 15, minimum=1, maximum=1440
)
REFRESH_TOKEN_DAYS: int = _env_int("REFRESH_TOKEN_DAYS", 30, minimum=1, maximum=365)
REFRESH_TOKEN_REUSE_GRACE_SECONDS: int = _env_int(
    "REFRESH_TOKEN_REUSE_GRACE_SECONDS", 30, minimum=0, maximum=300
)

LOGIN_RATE_LIMIT_PER_MINUTE: int = _env_int(
    "LOGIN_RATE_LIMIT_PER_MINUTE", 10, minimum=1
)
LOGIN_IP_RATE_LIMIT_PER_MINUTE: int = _env_int(
    "LOGIN_IP_RATE_LIMIT_PER_MINUTE", 50, minimum=1
)
LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = _env_int(
    "LOGIN_RATE_LIMIT_WINDOW_SECONDS", 60, minimum=1
)
PASSWORD_RESET_RATE_LIMIT_PER_HOUR: int = _env_int(
    "PASSWORD_RESET_RATE_LIMIT_PER_HOUR", 5, minimum=1
)
RATE_LIMIT_MAX_KEYS: int = _env_int("RATE_LIMIT_MAX_KEYS", 10_000, minimum=100)

PASSWORD_MIN_LENGTH: int = _env_int("PASSWORD_MIN_LENGTH", 12, minimum=8, maximum=128)
PASSWORD_MAX_LENGTH: int = _env_int(
    "PASSWORD_MAX_LENGTH", 128, minimum=PASSWORD_MIN_LENGTH, maximum=1024
)
PASSWORD_REQUIRE_UPPER: bool = _env_bool("PASSWORD_REQUIRE_UPPER", True)
PASSWORD_REQUIRE_LOWER: bool = _env_bool("PASSWORD_REQUIRE_LOWER", True)
PASSWORD_REQUIRE_DIGIT: bool = _env_bool("PASSWORD_REQUIRE_DIGIT", True)
PASSWORD_REQUIRE_SYMBOL: bool = _env_bool("PASSWORD_REQUIRE_SYMBOL", True)
PASSWORD_RESET_TOKEN_MINUTES: int = _env_int(
    "PASSWORD_RESET_TOKEN_MINUTES", 15, minimum=1, maximum=1440
)
PASSWORD_RESET_RETURN_TOKEN: bool = _env_bool("PASSWORD_RESET_RETURN_TOKEN", False)

ENFORCE_HTTPS: bool = _env_bool("ENFORCE_HTTPS", ENV == "production")
# Only enable this when the app is behind a proxy that strips client-supplied
# forwarding headers and is configured as a trusted proxy in the ASGI server.
TRUST_X_FORWARDED_PROTO: bool = _env_bool("TRUST_X_FORWARDED_PROTO", False)

INITIAL_SUPERUSER_EMAIL: str | None = _optional_env("INITIAL_SUPERUSER_EMAIL")
INITIAL_SUPERUSER_PASSWORD: str | None = _optional_env("INITIAL_SUPERUSER_PASSWORD")


DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+pysqlite:///./riskapp.db").strip()
DB_POOL_RECYCLE: int = _env_int("DB_POOL_RECYCLE", 1800, minimum=0)
DB_POOL_SIZE: int = _env_int("DB_POOL_SIZE", 5, minimum=1)
DB_MAX_OVERFLOW: int = _env_int("DB_MAX_OVERFLOW", 10, minimum=0)
DB_STATEMENT_TIMEOUT_MS: int = _env_int("DB_STATEMENT_TIMEOUT_MS", 30_000, minimum=0)

GZIP_ENABLED: bool = _env_bool("GZIP_ENABLED", True)
GZIP_MINIMUM_SIZE: int = _env_int("GZIP_MINIMUM_SIZE", 1024, minimum=0)
MAX_REQUEST_BODY_BYTES: int = _env_int(
    "MAX_REQUEST_BODY_BYTES", 2 * 1024 * 1024, minimum=1024
)

# Schema auto-creation is convenient locally; production should run migrations.
AUTO_CREATE_SCHEMA: bool = _env_bool("AUTO_CREATE_SCHEMA", ENV != "production")
MAX_SYNC_PULL_PER_ENTITY: int = _env_int(
    "MAX_SYNC_PULL_PER_ENTITY", 5000, minimum=1, maximum=50_000
)
SYNC_PUSH_EXPUNGE_EVERY: int = _env_int("SYNC_PUSH_EXPUNGE_EVERY", 200, minimum=1)
SNAPSHOT_INSERT_CHUNK: int = _env_int("SNAPSHOT_INSERT_CHUNK", 1000, minimum=100)
RETENTION_DAYS: int = _env_int("RETENTION_DAYS", 180, minimum=1)
SYNC_RECEIPT_RETENTION_DAYS: int = _env_int(
    "SYNC_RECEIPT_RETENTION_DAYS", 365, minimum=1
)

CORS_ORIGINS: list[str] = _env_list("CORS_ORIGINS")
ALLOWED_HOSTS: list[str] = _env_list(
    "ALLOWED_HOSTS", "" if ENV == "production" else "*"
)


def validate_runtime_config() -> None:
    """Fail closed for settings that affect authentication or request trust."""
    errors: list[str] = []

    if ALGORITHM not in {"HS256", "HS384", "HS512"}:
        errors.append("ALGORITHM must be HS256, HS384, or HS512")
    if len(SECRET_KEY) < 32:
        errors.append("SECRET_KEY must contain at least 32 characters")
    if len(TOKEN_HASH_KEY) < 32:
        errors.append("TOKEN_HASH_KEY must contain at least 32 characters")
    if "*" in CORS_ORIGINS:
        errors.append("CORS_ORIGINS cannot contain '*' when credentials are enabled")
    if bool(INITIAL_SUPERUSER_EMAIL) != bool(INITIAL_SUPERUSER_PASSWORD):
        errors.append(
            "INITIAL_SUPERUSER_EMAIL and INITIAL_SUPERUSER_PASSWORD must be set together"
        )

    if ENV == "production":
        if PASSWORD_RESET_RETURN_TOKEN:
            errors.append("PASSWORD_RESET_RETURN_TOKEN is forbidden in production")
        if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
            errors.append("production ALLOWED_HOSTS must list explicit hostnames")

    if errors:
        raise ConfigurationError("Invalid RiskApp configuration: " + "; ".join(errors))
