"""Configuration parsing and fail-closed validation boundaries."""

from __future__ import annotations

import pytest


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


def test_runtime_validation_reports_all_unsafe_settings(monkeypatch) -> None:
    import riskapp_server.core.config as config

    unsafe = {
        "ENV": "production",
        "ALGORITHM": "RS256",
        "SECRET_KEY": "short",
        "ALLOW_INSECURE_DEFAULT_SECRET": True,
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
    assert "explicit hostnames" in message


def test_valid_production_and_local_settings_pass(monkeypatch) -> None:
    import riskapp_server.core.config as config

    valid = {
        "ENV": "production",
        "ALGORITHM": "HS512",
        "SECRET_KEY": "s" * 32,
        "ALLOW_INSECURE_DEFAULT_SECRET": False,
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
    monkeypatch.setattr(config, "SECRET_KEY", "change-me")
    with pytest.raises(config.ConfigurationError, match="set SECRET_KEY"):
        config.validate_runtime_config()

    monkeypatch.setattr(config, "ALLOW_INSECURE_DEFAULT_SECRET", True)
    monkeypatch.setattr(config, "ALLOWED_HOSTS", ["*"])
    config.validate_runtime_config()
