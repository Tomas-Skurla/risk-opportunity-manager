"""Configuration parsing and fail-closed validation boundaries."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# These tests intentionally inspect private environment-parsing helpers.
# pylint: disable=protected-access
# Keep imports local to use the configuration currently loaded by the tests.
# pylint: disable=import-outside-toplevel

ROOT = Path(__file__).resolve().parents[2]


def test_configuration_import_rejects_unknown_environment_mode() -> None:
    environment = os.environ.copy()
    environment["ENV"] = "prod"
    python_paths = [str(ROOT / "server"), str(ROOT / "client")]
    if inherited_path := environment.get("PYTHONPATH"):
        python_paths.append(inherited_path)
    environment["PYTHONPATH"] = os.pathsep.join(python_paths)

    result = subprocess.run(  # noqa: S603 - fixed interpreter and import statement
        [sys.executable, "-c", "import riskapp_server.core.config"],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "ENV must be one of: development, production, test" in result.stderr


def test_environment_helpers_reject_malformed_and_out_of_range_values(
    monkeypatch,
) -> None:
    import riskapp_server.core.config as config

    monkeypatch.setenv("BOOL_SETTING", "maybe")
    with pytest.raises(config.ConfigurationError, match="BOOL_SETTING"):
        config._env_bool("BOOL_SETTING")
    monkeypatch.setenv("BOOL_SETTING", " YES ")
    assert config._env_bool("BOOL_SETTING") is True
    monkeypatch.setenv("BOOL_SETTING", " off ")
    assert config._env_bool("BOOL_SETTING") is False
    monkeypatch.setenv("BOOL_SETTING", " ")
    assert config._env_bool("BOOL_SETTING", default=True) is True

    monkeypatch.setenv("INT_SETTING", "not-an-int")
    with pytest.raises(config.ConfigurationError, match="must be an integer"):
        config._env_int("INT_SETTING", 5)
    monkeypatch.setenv("INT_SETTING", "0")
    with pytest.raises(config.ConfigurationError, match="at least 1"):
        config._env_int("INT_SETTING", 5, minimum=1)
    monkeypatch.setenv("INT_SETTING", "11")
    with pytest.raises(config.ConfigurationError, match="at most 10"):
        config._env_int("INT_SETTING", 5, maximum=10)
    monkeypatch.setenv("INT_SETTING", "7")
    assert config._env_int("INT_SETTING", 5, minimum=1, maximum=10) == 7

    monkeypatch.setenv("CHOICE_SETTING", " JSON ")
    assert config._env_choice("CHOICE_SETTING", "plain", {"plain", "json"}) == "json"
    monkeypatch.setenv("CHOICE_SETTING", "xml")
    with pytest.raises(config.ConfigurationError, match="CHOICE_SETTING"):
        config._env_choice("CHOICE_SETTING", "plain", {"plain", "json"})

def test_integer_setting_deprecated_alias_and_canonical_precedence(
    monkeypatch,
) -> None:
    import riskapp_server.core.config as config

    monkeypatch.delenv("NEW_SETTING", raising=False)
    monkeypatch.setenv("OLD_SETTING", "17")
    with pytest.warns(DeprecationWarning, match="OLD_SETTING is deprecated"):
        assert (
            config._env_int_with_deprecated_alias(
                "NEW_SETTING", "OLD_SETTING", 5, minimum=1
            )
            == 17
        )

    monkeypatch.setenv("NEW_SETTING", "23")
    with pytest.warns(DeprecationWarning, match="OLD_SETTING is deprecated"):
        assert (
            config._env_int_with_deprecated_alias(
                "NEW_SETTING", "OLD_SETTING", 5, minimum=1
            )
            == 23
        )


def test_runtime_validation_reports_all_unsafe_settings(monkeypatch) -> None:
    import riskapp_server.core.config as config

    unsafe = {
        "ENV": "production",
        "ALGORITHM": "RS256",
        "SECRET_KEY": "short",
        "TOKEN_HASH_KEY": "short",
        "CORS_ORIGINS": ["*"],
        "INITIAL_SUPERUSER_EMAIL": "root@example.test",
        "INITIAL_SUPERUSER_PASSWORD": None,
        "PASSWORD_RESET_RETURN_TOKEN": True,
        "ALLOWED_HOSTS": [],
    }
    for name, value in unsafe.items():
        monkeypatch.setattr(config, name, value)

    with pytest.raises(config.ConfigurationError) as exc_info:
        config.validate_runtime_config()

    message = str(exc_info.value)
    assert "ALGORITHM" in message
    assert "CORS_ORIGINS" in message
    assert "must be set together" in message
    assert "forbidden in production" in message
    assert "at least 32 characters" in message
    assert "TOKEN_HASH_KEY" in message
    assert "explicit hostnames" in message


def test_valid_production_and_local_settings_pass(monkeypatch) -> None:
    import riskapp_server.core.config as config

    valid = {
        "ENV": "production",
        "ALGORITHM": "HS512",
        "SECRET_KEY": "s" * 32,
        "TOKEN_HASH_KEY": "t" * 32,
        "CORS_ORIGINS": ["https://app.example.test"],
        "INITIAL_SUPERUSER_EMAIL": None,
        "INITIAL_SUPERUSER_PASSWORD": None,
        "PASSWORD_RESET_RETURN_TOKEN": False,
        "ALLOWED_HOSTS": ["api.example.test"],
    }
    for name, value in valid.items():
        monkeypatch.setattr(config, name, value)
    config.validate_runtime_config()

    monkeypatch.setattr(config, "ENV", "development")
    monkeypatch.setattr(config, "ALLOWED_HOSTS", ["*"])
    config.validate_runtime_config()
    monkeypatch.setattr(config, "ENV", "test")
    config.validate_runtime_config()


@pytest.mark.parametrize("mode", ["development", "test", "production"])
@pytest.mark.parametrize("key_name", ["SECRET_KEY", "TOKEN_HASH_KEY"])
@pytest.mark.parametrize(
    "unsafe_value", [None, "", "   ", "change-me", "change-me-token-hash-key", "s" * 31]
)
def test_legacy_flag_cannot_bypass_key_validation(
    mode: str, key_name: str, unsafe_value: str | None
) -> None:
    """Real environment parsing must reject unsafe keys even with the old flag."""
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONPATH": str(ROOT / "server"),
            "ENV": mode,
            "SECRET_KEY": "s" * 32,
            "TOKEN_HASH_KEY": "t" * 32,
            "ALLOW_INSECURE_DEFAULT_SECRET": "1",
            "ALGORITHM": "HS256",
            "ALLOWED_HOSTS": "localhost",
            "CORS_ORIGINS": "",
            "PASSWORD_RESET_RETURN_TOKEN": "0",
            "INITIAL_SUPERUSER_EMAIL": "",
            "INITIAL_SUPERUSER_PASSWORD": "",
        }
    )
    if unsafe_value is None:
        environment.pop(key_name)
    else:
        environment[key_name] = unsafe_value

    result = subprocess.run(  # noqa: S603 - fixed interpreter and validation command
        [
            sys.executable,
            "-c",
            "from riskapp_server.core.config import validate_runtime_config; "
            "validate_runtime_config()",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode != 0
    assert f"{key_name} must contain at least 32 characters" in result.stderr
