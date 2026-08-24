"""Desktop-client environment configuration."""

from __future__ import annotations

from pathlib import Path

from riskapp_client.app.environment_config import AppConfig


def test_app_config_reads_and_normalizes_environment(monkeypatch, tmp_path) -> None:
    local_db = tmp_path / "state" / "client.sqlite3"
    monkeypatch.setenv("RISKAPP_URL", "  https://api.example.test/  ")
    monkeypatch.setenv("RISKAPP_EMAIL", "  user@example.test  ")
    monkeypatch.setenv("RISKAPP_PASSWORD", "  keep password whitespace  ")
    monkeypatch.setenv("RISKAPP_LOCAL_DB", str(local_db))
    monkeypatch.setenv("RISKAPP_ALLOW_HTTP", "1")

    config = AppConfig.from_env()

    assert config.base_url == "https://api.example.test/"
    assert config.email == "user@example.test"
    assert config.password == "keep password whitespace"
    assert config.local_db_path == local_db
    assert config.allow_http_anywhere is True


def test_app_config_uses_safe_defaults(monkeypatch, tmp_path) -> None:
    for name in (
        "RISKAPP_URL",
        "RISKAPP_EMAIL",
        "RISKAPP_PASSWORD",
        "RISKAPP_LOCAL_DB",
        "RISKAPP_ALLOW_HTTP",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    config = AppConfig.from_env()

    assert config.base_url == "http://localhost:8000"
    assert config.email == ""
    assert config.password == ""
    assert config.local_db_path == tmp_path / ".riskapp" / "client.sqlite3"
    assert config.allow_http_anywhere is False
