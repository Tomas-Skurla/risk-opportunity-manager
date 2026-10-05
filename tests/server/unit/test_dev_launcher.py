"""The native launcher loads private settings without shell execution or defaults."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from support import REPO_ROOT

ROOT = REPO_ROOT


# Pytest passes fixtures to tests and other fixtures by parameter name.
# pylint: disable=redefined-outer-name


@pytest.fixture
def launcher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy2(ROOT / "scripts/run_server_dev.sh", scripts / "run_server_dev.sh")
    (tmp_path / "server").mkdir()
    binaries = tmp_path / ".venv/bin"
    binaries.mkdir(parents=True)
    (binaries / "activate").write_text("# Test environment already configured.\n")
    stub = binaries / "uvicorn"
    stub.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "names = ['SECRET_KEY', 'TOKEN_HASH_KEY', "
        "'INITIAL_SUPERUSER_EMAIL', 'INITIAL_SUPERUSER_PASSWORD']\n"
        "Path(os.environ['RISKAPP_LAUNCH_CAPTURE']).write_text(json.dumps({"
        "'args': sys.argv[1:], 'env': {name: os.getenv(name) for name in names}}))\n"
    )
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", str(binaries) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("RISKAPP_LAUNCH_CAPTURE", str(tmp_path / "capture.json"))
    for name in (
        "SECRET_KEY",
        "TOKEN_HASH_KEY",
        "INITIAL_SUPERUSER_EMAIL",
        "INITIAL_SUPERUSER_PASSWORD",
        "RESET_SERVER_DB",
    ):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def run_launcher(directory: Path) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    assert bash is not None
    return subprocess.run(  # noqa: S603 - fixed repository launcher in an isolated copy
        [bash, str(directory / "scripts/run_server_dev.sh")],
        cwd=directory.parent,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_launcher_passes_dotenv_as_data_without_sourcing(launcher: Path) -> None:
    (launcher / ".env").write_text("UNSAFE=$(touch should-not-exist)\n")
    result = run_launcher(launcher)

    assert result.returncode == 0
    capture = json.loads((launcher / "capture.json").read_text())
    arguments = capture["args"]
    assert arguments[arguments.index("--env-file") + 1] == str(launcher / ".env")
    assert not (launcher / "should-not-exist").exists()
    assert all(value is None for value in capture["env"].values())


def test_launcher_accepts_exported_keys_without_creating_an_admin(
    launcher: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SECRET_KEY", "s" * 32)
    monkeypatch.setenv("TOKEN_HASH_KEY", "t" * 32)
    result = run_launcher(launcher)

    assert result.returncode == 0
    capture = json.loads((launcher / "capture.json").read_text())
    assert "--env-file" not in capture["args"]
    assert capture["env"]["SECRET_KEY"] == "s" * 32
    assert capture["env"]["TOKEN_HASH_KEY"] == "t" * 32
    assert capture["env"]["INITIAL_SUPERUSER_EMAIL"] is None
    assert capture["env"]["INITIAL_SUPERUSER_PASSWORD"] is None


def test_launcher_requires_setup_or_exported_keys(launcher: Path) -> None:
    result = run_launcher(launcher)

    assert result.returncode != 0
    assert "./scripts/dev-init.sh" in result.stderr
    assert not (launcher / "capture.json").exists()
