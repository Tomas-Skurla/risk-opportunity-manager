"""Names and rules shared by the sync service, the outbox and the background worker."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class SyncState(StrEnum):
    """Outcome of one synchronization run, read by the UI and the scheduler."""

    COMPLETE = "complete"
    CANCELLED = "cancelled"
    RETRY_WAIT = "retry_wait"
    ATTENTION_REQUIRED = "attention_required"
    AUTHENTICATION_REQUIRED = "authentication_required"
    PERMISSION_DENIED = "permission_denied"


class FailureKind(StrEnum):
    """Why a change or request failed; decides between retrying and blocking."""

    TRANSIENT = "transient"
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    VALIDATION = "validation"
    CONFLICT = "conflict"
    ERROR = "error"


_STATE_FOR_FAILURE: dict[str, SyncState] = {
    FailureKind.TRANSIENT: SyncState.RETRY_WAIT,
    FailureKind.AUTHENTICATION: SyncState.AUTHENTICATION_REQUIRED,
    FailureKind.PERMISSION: SyncState.PERMISSION_DENIED,
}


def classify_http_status(status: int) -> tuple[FailureKind, bool]:
    """Return the failure kind and whether an HTTP failure can be retried."""
    if status == 401:
        return FailureKind.AUTHENTICATION, False
    if status == 403:
        return FailureKind.PERMISSION, False
    if status == 0 or status in {408, 425, 429} or status >= 500:
        return FailureKind.TRANSIENT, True
    return FailureKind.VALIDATION, False


def sync_state_for_failure(failure_kind: str) -> SyncState:
    """Use the same failure states in the coordinator and background worker."""
    return _STATE_FOR_FAILURE.get(failure_kind, SyncState.ATTENTION_REQUIRED)


def strict_int(value: object) -> int | None:
    """Return an integer field, treating JSON true/false as missing."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def acknowledged_version(result: dict[str, Any]) -> int | None:
    """Return the version an accepted change produced.

    A replayed receipt reports the version from its first acceptance, not the
    row's current version, which may include another device's later edit.
    """
    receipt_version = strict_int(result.get("receipt_server_version"))
    if result.get("replayed") and receipt_version is not None:
        return receipt_version
    return strict_int(result.get("server_version"))
