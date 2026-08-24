"""Compose the Qt application and backend dependencies."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QDialog, QMessageBox

from riskapp_client.adapters.local_storage.sqlite_data_store import LocalStore
from riskapp_client.adapters.remote_api.rest_api_client import (
    ApiBackend,
    ApiError,
    register_account,
)
from riskapp_client.app.environment_config import AppConfig
from riskapp_client.services.offline_first_facade import OfflineFirstBackend
from riskapp_client.ui_v2.components.custom_gui_widgets import (
    LoginDialog,
    RegisterDialog,
    ServerDownDialog,
)
from riskapp_client.ui_v2.main_application_window import MainWindow
from riskapp_client.utils.urls import UrlPolicy

logger = logging.getLogger(__name__)


def _handle_registration(
    default_url: str, *, allow_http: bool
) -> tuple[str, str, str] | None:
    """Show the registration dialog and return credentials on success."""
    dlg = RegisterDialog(default_url=default_url)
    if dlg.exec() != QDialog.Accepted:
        return None
    base_url, email, password = dlg.values()
    try:
        register_account(
            base_url,
            email,
            password,
            url_policy=UrlPolicy(allow_http_anywhere=allow_http),
        )
        QMessageBox.information(
            None,
            "Registration successful",
            f"Account created for {email}.\n\nYou will now be logged in automatically.",
        )
        return base_url, email, password
    except ApiError as exc:
        detail = exc.detail
        if isinstance(detail, dict):
            parts = []
            for key, val in detail.items():
                (
                    parts.extend(val)
                    if isinstance(val, list)
                    else parts.append(f"{key}: {val}")
                )
            detail = "\n".join(parts)
        QMessageBox.warning(None, "Registration failed", f"{detail}")
        return None
    except (RuntimeError, OSError) as exc:
        QMessageBox.warning(None, "Registration failed", str(exc))
        return None


def _show_server_down(
    error: str, *, email: str, store: LocalStore
) -> MainWindow | None:
    """Show the server-down dialog."""
    has_creds = bool(email)
    dlg = ServerDownDialog(error, has_credentials=has_creds, email=email)
    if dlg.exec() != QDialog.Accepted:
        return None

    if dlg.choice == ServerDownDialog.OFFLINE_WITH_ACCOUNT and email:
        # Cache the email for later sync.
        store.set_meta("last_email", email)
        backend = OfflineFirstBackend(store, remote=None, anonymous_offline=False)
    else:
        # Stay local only.
        backend = OfflineFirstBackend(store, remote=None, anonymous_offline=True)
    return MainWindow(backend)


def build_main_window(config: AppConfig) -> MainWindow:
    try:
        Path(config.local_db_path).expanduser().parent.mkdir(
            parents=True, exist_ok=True
        )
    except OSError as exc:
        QMessageBox.critical(
            None,
            "Local storage error",
            f"Cannot create local DB directory for:\n{config.local_db_path}\n\n{exc}",
        )
        raise

    store = LocalStore(str(config.local_db_path))
    base_url = config.base_url
    email = config.email
    password = config.password
    cached_email = store.get_meta("last_email") or None

    # Get credentials from the dialog or environment.
    if not email or not password:
        dlg = LoginDialog(default_url=base_url, cached_email=cached_email)
        result = dlg.exec()

        if dlg.wants_register:
            reg = _handle_registration(
                dlg.ui.url.text().strip() or base_url,
                allow_http=config.allow_http_anywhere,
            )
            if reg is not None:
                base_url, email, password = reg
            else:
                sys.exit(0)
        elif dlg.wants_local:
            # Stay local only.
            backend = OfflineFirstBackend(store, remote=None, anonymous_offline=True)
            return MainWindow(backend)
        elif result != QDialog.Accepted:
            sys.exit(0)
        else:
            base_url, email, password = dlg.values()

    # Try to connect.
    try:
        remote = ApiBackend(
            base_url=base_url,
            email=email,
            password=password,
            url_policy=UrlPolicy(allow_http_anywhere=config.allow_http_anywhere),
        )
        store.set_meta("last_email", email)
        backend = OfflineFirstBackend(store, remote=remote)
        return MainWindow(backend)
    except (RuntimeError, OSError) as exc:
        logger.warning("Login/connection failed: %s", exc)
        # Offer offline options.
        window = _show_server_down(str(exc), email=email, store=store)
        if window is None:
            sys.exit(0)
        return window
