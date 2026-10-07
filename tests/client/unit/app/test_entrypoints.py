"""Tests for the lightweight client entry point and logging setup."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from riskapp_client.app import main_entrypoint
from riskapp_client.utils import logging_config


def test_configure_logging_uses_known_and_fallback_levels(monkeypatch) -> None:
    basic_config = Mock()
    monkeypatch.setattr(logging_config.logging, "basicConfig", basic_config)
    monkeypatch.setenv("RISKAPP_LOG_LEVEL", " debug ")
    logging_config.configure_logging()
    assert basic_config.call_args.kwargs["level"] == logging_config.logging.DEBUG

    monkeypatch.setenv("RISKAPP_LOG_LEVEL", "not-a-level")
    logging_config.configure_logging()
    assert basic_config.call_args.kwargs["level"] == logging_config.logging.INFO


def test_client_main_configures_builds_shows_and_returns_event_code(
    monkeypatch,
) -> None:
    app = SimpleNamespace(exec=Mock(return_value=17))
    application = Mock(return_value=app)
    window = SimpleNamespace(show=Mock())
    config = object()
    configure = Mock()
    build = Mock(return_value=window)
    monkeypatch.setattr(main_entrypoint, "QApplication", application)
    monkeypatch.setattr(main_entrypoint, "configure_logging", configure)
    monkeypatch.setattr(main_entrypoint.AppConfig, "from_env", lambda: config)
    monkeypatch.setattr(main_entrypoint, "build_main_window", build)

    assert main_entrypoint.main() == 17
    configure.assert_called_once_with()
    build.assert_called_once_with(config)
    window.show.assert_called_once_with()
