from __future__ import annotations

import pytest


def test_production_configuration_rejects_insecure_switches(monkeypatch) -> None:
    """Production cannot expose reset tokens or trust wildcard hosts."""
    import riskapp_server.core.config as config

    monkeypatch.setattr(config, "ENV", "production")
    monkeypatch.setattr(config, "SECRET_KEY", "x" * 32)
    monkeypatch.setattr(config, "ALLOW_INSECURE_DEFAULT_SECRET", False)
    monkeypatch.setattr(config, "PASSWORD_RESET_RETURN_TOKEN", True)
    monkeypatch.setattr(config, "ALLOWED_HOSTS", ["*"])

    with pytest.raises(config.ConfigurationError, match="PASSWORD_RESET_RETURN_TOKEN"):
        config.validate_runtime_config()
