"""Create verified server snapshots and restore them while the API is stopped."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import sys
import tempfile
import time
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

_SERVER_TABLES = {
    "users",
    "projects",
    "project_members",
    "items",
    "assessments",
    "actions",
    "helpdesk_tickets",
    "sync_project_state",
    "sync_receipts",
    "audit_log",
    "refresh_tokens",
    "password_reset_tokens",
    "score_snapshots",
}
_SCHEMA_GUARDS = {
    "sync_receipts": "payload_hash",
    "sync_project_state": "last_sequence",
    "items": "change_sequence",
    "assessments": "change_sequence",
    "actions": "change_sequence",
    "helpdesk_tickets": "change_sequence",
}
_SIDECARS = ("-wal", "-shm", "-journal")


class BackupError(RuntimeError):
    """A snapshot or recovery precondition was not satisfied."""


@dataclass(frozen=True)
class BackupInfo:
    path: str
    revision: str | None
    sha256: str


def _migration_head() -> str:
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[2] / "alembic")
    )
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        raise BackupError("The server migration history has no head")
    return head


def _read_only(path: Path, timeout: float) -> sqlite3.Connection:
    if not math.isfinite(timeout) or timeout <= 0:
        raise BackupError("Timeout must be finite and positive")
    if not path.is_file():
        raise BackupError("Source database must be an existing regular file")
    # A missing file must never become an empty database. URI escaping also
    # preserves spaces, Windows drive letters, and literal ?/# characters.
    return sqlite3.connect(
        path.resolve().as_uri() + "?mode=ro", uri=True, timeout=timeout
    )


def _no_sidecars(path: Path) -> None:
    if any(Path(str(path) + suffix).exists() for suffix in _SIDECARS):
        raise BackupError(
            "SQLite sidecars are present; stop every API worker and close its "
            "connections before recovery. Do not delete WAL/journal files."
        )


def _destination(source: Path, destination: Path, *, replace: bool) -> Path:
    if destination.is_symlink():
        raise BackupError("Destination must not be a symbolic link")
    destination = destination.absolute()
    if source.resolve() == destination.resolve() or (
        destination.exists() and source.samefile(destination)
    ):
        raise BackupError("Source and destination must be different files")
    if not destination.parent.is_dir():
        raise BackupError("Destination directory must already exist")
    if destination.exists() and (not replace or not destination.is_file()):
        raise BackupError("Destination exists; backups never overwrite existing files")
    return destination


def verify_backup(
    path: Path, *, timeout: float = 30, allow_unversioned: bool = False
) -> BackupInfo:
    """Check a standalone snapshot, including all foreign keys and its revision."""
    _no_sidecars(path)
    with closing(_read_only(path, timeout)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise BackupError("SQLite integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise BackupError("SQLite foreign-key check failed")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if not _SERVER_TABLES.issubset(tables):
            raise BackupError("Not a RiskApp server database")
        revision: str | None = None
        if "alembic_version" in tables:
            revisions = connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchall()
            revision = _migration_head()
            if revisions != [(revision,)]:
                raise BackupError(
                    "Snapshot revision does not match this server migration head"
                )
        elif not allow_unversioned:
            raise BackupError(
                "Unversioned database requires explicit --allow-unversioned"
            )
        else:
            for table, required_column in _SCHEMA_GUARDS.items():
                # Table names come only from the fixed guard list above.
                columns = {
                    row[1] for row in connection.execute(f"PRAGMA table_info({table})")
                }
                if required_column not in columns:
                    raise BackupError("Unversioned database lacks current sync columns")
    with path.open("rb") as snapshot:
        digest = hashlib.file_digest(snapshot, "sha256").hexdigest()
    return BackupInfo(str(path.absolute()), revision, digest)


def _copy_snapshot(
    source: Path, staged: Path, timeout: float, *, allow_unversioned: bool = False
) -> BackupInfo:
    if not math.isfinite(timeout) or timeout <= 0:
        raise BackupError("Timeout must be finite and positive")
    deadline = time.monotonic() + timeout

    def progress(_status: int, _remaining: int, _total: int) -> None:
        if time.monotonic() >= deadline:
            raise BackupError("Backup timed out; no snapshot was published")

    with (
        closing(_read_only(source, timeout)) as original,
        closing(sqlite3.connect(staged, timeout=timeout)) as snapshot,
    ):
        original.backup(snapshot, pages=256, progress=progress, sleep=0.05)
        # The published file must be self-contained even when the live source
        # uses WAL. Closing both handles before validation matters on Windows.
        snapshot.execute("PRAGMA journal_mode=DELETE")
    staged.chmod(0o600)
    info = verify_backup(staged, timeout=timeout, allow_unversioned=allow_unversioned)
    # Windows requires write access for fsync. r+b preserves the verified bytes.
    with staged.open("r+b") as snapshot_file:
        os.fsync(snapshot_file.fileno())
    return info


def backup_database(
    database: Path,
    output: Path,
    *,
    timeout: float = 30,
    allow_unversioned: bool = False,
) -> BackupInfo:
    """Take an online SQLite backup; publish only a fully verified new file."""
    output = _destination(database, output, replace=False)
    with tempfile.TemporaryDirectory(
        prefix=".riskapp-backup.", dir=output.parent
    ) as work:
        staged = Path(work) / "snapshot.sqlite3"
        info = _copy_snapshot(
            database, staged, timeout, allow_unversioned=allow_unversioned
        )
        # One atomic, no-clobber publication on the same filesystem. A racing
        # backup cannot overwrite another completed snapshot.
        os.link(staged, output)
    return BackupInfo(str(output), info.revision, info.sha256)


def restore_database(
    backup: Path,
    database: Path,
    *,
    offline: bool = False,
    replace: bool = False,
    timeout: float = 30,
    allow_unversioned: bool = False,
) -> BackupInfo:
    """Recover offline. Existing files require an explicit replacement request."""
    if not offline:
        raise BackupError("Restore requires --offline after stopping every API worker")
    database = _destination(backup, database, replace=replace)
    _no_sidecars(database)
    verify_backup(backup, timeout=timeout, allow_unversioned=allow_unversioned)
    with tempfile.TemporaryDirectory(
        prefix=".riskapp-restore.", dir=database.parent
    ) as work:
        staged = Path(work) / "restored.sqlite3"
        info = _copy_snapshot(
            backup, staged, timeout, allow_unversioned=allow_unversioned
        )
        _no_sidecars(database)
        if database.is_symlink():
            raise BackupError("Destination must not be a symbolic link")
        if replace:
            os.replace(staged, database)
        else:
            os.link(staged, database)
    return BackupInfo(str(database), info.revision, info.sha256)


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup", help="Create a new online snapshot")
    backup.add_argument("--database", type=Path, required=True)
    backup.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify", help="Validate a standalone snapshot")
    verify.add_argument("--backup", type=Path, required=True)
    restore = commands.add_parser("restore", help="Restore while the API is stopped")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--database", type=Path, required=True)
    restore.add_argument("--offline", action="store_true")
    restore.add_argument("--replace", action="store_true")
    for command in (backup, verify, restore):
        command.add_argument("--timeout", type=float, default=30)
        command.add_argument(
            "--allow-unversioned",
            action="store_true",
            help="Explicitly allow development databases made with AUTO_CREATE_SCHEMA",
        )
    args = parser.parse_args(arguments)
    try:
        if args.command == "backup":
            result = backup_database(
                args.database,
                args.output,
                timeout=args.timeout,
                allow_unversioned=args.allow_unversioned,
            )
        elif args.command == "verify":
            result = verify_backup(
                args.backup,
                timeout=args.timeout,
                allow_unversioned=args.allow_unversioned,
            )
        else:
            result = restore_database(
                args.backup,
                args.database,
                offline=args.offline,
                replace=args.replace,
                timeout=args.timeout,
                allow_unversioned=args.allow_unversioned,
            )
    except (BackupError, OSError, sqlite3.Error) as exc:
        print(f"Database operation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(asdict(result)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
