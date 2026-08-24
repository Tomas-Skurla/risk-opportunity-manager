"""Validate that Alembic builds the current server schema from an empty DB."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _temporary_parent() -> Path:
    for variable in ("RUNNER_TEMP", "TMPDIR"):
        value = os.environ.get(variable)
        if value and Path(value).is_dir():
            return Path(value)
    git_dir = ROOT / ".git"
    return git_dir if git_dir.is_dir() else ROOT


def _run_alembic(arguments: list[str], environment: dict[str, str]) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=ROOT,
        env=environment,
        check=True,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(
        prefix="riskapp-migration-check.", dir=_temporary_parent()
    ) as temporary_directory:
        database_path = Path(temporary_directory) / "fresh.sqlite3"
        environment = os.environ.copy()
        environment.update(
            {
                "ENV": "test",
                "SECRET_KEY": "riskapp-migration-check-secret-key",
                "ALLOW_INSECURE_DEFAULT_SECRET": "0",
                "AUTO_CREATE_SCHEMA": "0",
                "DATABASE_URL": f"sqlite+pysqlite:///{database_path.as_posix()}",
            }
        )
        environment.pop("INITIAL_SUPERUSER_EMAIL", None)
        environment.pop("INITIAL_SUPERUSER_PASSWORD", None)

        _run_alembic(["upgrade", "head"], environment)
        _run_alembic(["upgrade", "head"], environment)
        _run_alembic(["current", "--check-heads"], environment)
        _run_alembic(["check"], environment)

        with sqlite3.connect(database_path) as connection:
            version = connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()
        if not version or not version[0]:
            raise RuntimeError("Alembic did not record a schema revision")

    print("Migration check passed: empty database upgraded to head with no drift.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
