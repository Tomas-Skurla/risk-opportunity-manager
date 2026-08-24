"""Desktop application composition and offline fallback behavior."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import riskapp_client.app.application_bootstrap as bootstrap
from PySide6.QtWidgets import QDialog, QMessageBox
from riskapp_client.adapters.remote_api.rest_api_client import ApiError
from riskapp_client.app.environment_config import AppConfig
from riskapp_client.ui_v2.components.custom_gui_widgets import ServerDownDialog


class FakeStore:
    def __init__(self):
        self.meta: dict[str, str] = {}

    def get_meta(self, key: str):
        return self.meta.get(key)

    def set_meta(self, key: str, value: str) -> None:
        self.meta[key] = value


class FakeRegistrationDialog:
    result = QDialog.Accepted
    values_result = (
        "https://api.example.test",
        "new@example.test",
        "StrongPassword1!",
    )

    def __init__(self, *, default_url):
        self.default_url = default_url

    def exec(self):
        return self.result

    def values(self):
        return self.values_result


def test_registration_flow_handles_cancel_success_and_server_validation(
    monkeypatch,
) -> None:
    info: list[str] = []
    warnings: list[str] = []
    monkeypatch.setattr(bootstrap, "RegisterDialog", FakeRegistrationDialog)
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, _title, message, *_args: info.append(message),
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, message, *_args: warnings.append(message),
    )

    FakeRegistrationDialog.result = QDialog.Rejected
    assert (
        bootstrap._handle_registration("https://api.example.test", allow_http=False)
        is None
    )

    FakeRegistrationDialog.result = QDialog.Accepted
    register = Mock(return_value={"id": "user-1"})
    monkeypatch.setattr(bootstrap, "register_account", register)
    credentials = bootstrap._handle_registration(
        "https://api.example.test", allow_http=False
    )
    assert credentials == FakeRegistrationDialog.values_result
    assert "new@example.test" in info[-1]
    assert register.call_args.kwargs["url_policy"].allow_http_anywhere is False

    monkeypatch.setattr(
        bootstrap,
        "register_account",
        Mock(
            side_effect=ApiError(
                422,
                {"password": ["too short", "needs a symbol"], "email": "invalid"},
            )
        ),
    )
    assert bootstrap._handle_registration("http://localhost", allow_http=True) is None
    assert "too short" in warnings[-1]
    assert "email: invalid" in warnings[-1]

    monkeypatch.setattr(
        bootstrap, "register_account", Mock(side_effect=OSError("network down"))
    )
    assert bootstrap._handle_registration("http://localhost", allow_http=True) is None
    assert warnings[-1] == "network down"


@pytest.mark.parametrize(
    ("result", "choice", "email", "anonymous", "expected"),
    [
        (QDialog.Rejected, 0, "cached@example.test", None, None),
        (
            QDialog.Accepted,
            ServerDownDialog.OFFLINE_WITH_ACCOUNT,
            "cached@example.test",
            False,
            "window",
        ),
        (QDialog.Accepted, ServerDownDialog.FULLY_LOCAL, "", True, "window"),
    ],
)
def test_server_down_flow_selects_account_or_anonymous_offline_mode(
    monkeypatch, result, choice, email, anonymous, expected
) -> None:
    store = FakeStore()

    class Dialog:
        FULLY_LOCAL = ServerDownDialog.FULLY_LOCAL
        OFFLINE_WITH_ACCOUNT = ServerDownDialog.OFFLINE_WITH_ACCOUNT

        def __init__(self, *_args, **_kwargs):
            self.choice = choice

        def exec(self):
            return result

    backends: list[SimpleNamespace] = []

    def make_backend(_store, *, remote, anonymous_offline):
        backend = SimpleNamespace(remote=remote, anonymous_offline=anonymous_offline)
        backends.append(backend)
        return backend

    monkeypatch.setattr(bootstrap, "ServerDownDialog", Dialog)
    monkeypatch.setattr(bootstrap, "OfflineFirstBackend", make_backend)
    monkeypatch.setattr(bootstrap, "MainWindow", lambda _backend: "window")

    assert bootstrap._show_server_down("offline", email=email, store=store) == expected
    if expected is None:
        assert backends == []
    else:
        assert backends[0].anonymous_offline is anonymous
    if choice == ServerDownDialog.OFFLINE_WITH_ACCOUNT and result == QDialog.Accepted:
        assert store.meta["last_email"] == email


def _config(tmp_path, *, email="user@example.test", password="secret"):
    return AppConfig(
        base_url="https://api.example.test",
        email=email,
        password=password,
        local_db_path=tmp_path / "state" / "client.sqlite3",
        allow_http_anywhere=False,
    )


def test_build_main_window_composes_online_backend_and_caches_email(
    monkeypatch, tmp_path
) -> None:
    store = FakeStore()
    remote = object()
    offline = object()
    monkeypatch.setattr(bootstrap, "LocalStore", lambda _path: store)
    api_backend = Mock(return_value=remote)
    monkeypatch.setattr(bootstrap, "ApiBackend", api_backend)
    monkeypatch.setattr(bootstrap, "OfflineFirstBackend", Mock(return_value=offline))
    monkeypatch.setattr(bootstrap, "MainWindow", lambda backend: ("window", backend))

    result = bootstrap.build_main_window(_config(tmp_path))

    assert result == ("window", offline)
    assert store.meta["last_email"] == "user@example.test"
    assert api_backend.call_args.kwargs["base_url"] == "https://api.example.test"
    assert api_backend.call_args.kwargs["url_policy"].allow_http_anywhere is False


def test_build_main_window_supports_local_login_and_connection_fallback(
    monkeypatch, tmp_path
) -> None:
    store = FakeStore()
    monkeypatch.setattr(bootstrap, "LocalStore", lambda _path: store)
    monkeypatch.setattr(
        bootstrap,
        "OfflineFirstBackend",
        lambda _store, *, remote, anonymous_offline=True: SimpleNamespace(
            remote=remote, anonymous_offline=anonymous_offline
        ),
    )
    monkeypatch.setattr(bootstrap, "MainWindow", lambda backend: backend)

    class LocalDialog:
        wants_register = False
        wants_local = True

        def __init__(self, **_kwargs):
            pass

        def exec(self):
            return QDialog.Accepted + 2

    monkeypatch.setattr(bootstrap, "LoginDialog", LocalDialog)
    local = bootstrap.build_main_window(_config(tmp_path, email="", password=""))
    assert local.anonymous_offline is True

    class CredentialsDialog:
        wants_register = False
        wants_local = False

        def __init__(self, **_kwargs):
            pass

        def exec(self):
            return QDialog.Accepted

        def values(self):
            return "https://other.example.test", "other@example.test", "pw"

    monkeypatch.setattr(bootstrap, "LoginDialog", CredentialsDialog)
    monkeypatch.setattr(
        bootstrap, "ApiBackend", Mock(side_effect=RuntimeError("server unavailable"))
    )
    monkeypatch.setattr(bootstrap, "_show_server_down", Mock(return_value="fallback"))
    assert (
        bootstrap.build_main_window(_config(tmp_path, email="", password=""))
        == "fallback"
    )


def test_build_main_window_exits_when_registration_or_fallback_is_cancelled(
    monkeypatch, tmp_path
) -> None:
    store = FakeStore()
    monkeypatch.setattr(bootstrap, "LocalStore", lambda _path: store)

    class RegisterLogin:
        wants_register = True
        wants_local = False
        ui = SimpleNamespace(url=SimpleNamespace(text=lambda: ""))

        def __init__(self, **_kwargs):
            pass

        def exec(self):
            return QDialog.Accepted + 1

    monkeypatch.setattr(bootstrap, "LoginDialog", RegisterLogin)
    monkeypatch.setattr(bootstrap, "_handle_registration", Mock(return_value=None))
    with pytest.raises(SystemExit) as exc_info:
        bootstrap.build_main_window(_config(tmp_path, email="", password=""))
    assert exc_info.value.code == 0

    monkeypatch.setattr(
        bootstrap, "ApiBackend", Mock(side_effect=RuntimeError("server unavailable"))
    )
    monkeypatch.setattr(bootstrap, "_show_server_down", Mock(return_value=None))
    with pytest.raises(SystemExit):
        bootstrap.build_main_window(_config(tmp_path))
