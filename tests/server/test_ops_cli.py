"""Tests for operational command-line helpers and server entry points."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from riskapp_server import __main__ as server_main
from riskapp_server.main import https_only_middleware
from riskapp_server.ops import apply_sql, prune_job
from sqlalchemy import create_engine, text


def test_sql_splitter_handles_quotes_comments_and_dollar_blocks() -> None:
    sql = """
    -- comment with a semicolon;
    CREATE TABLE "odd;name" (value TEXT);
    INSERT INTO "odd;name" VALUES ('semi;colon'), ('quote'';still');
    /* block; comment */
    DO $body$ BEGIN PERFORM 1; PERFORM 2; END $body$;
    SELECT 3
    """
    statements = list(apply_sql._split_sql(sql))
    assert len(statements) == 4
    assert statements[0].startswith("-- comment")
    assert "semi;colon" in statements[1]
    assert statements[2].endswith("$body$")
    assert statements[3] == "SELECT 3"
    assert list(apply_sql._split_sql(" ; ; ")) == []


def test_sql_file_resolution_deduplicates_and_validates(tmp_path: Path) -> None:
    first = tmp_path / "01.sql"
    second = tmp_path / "02.sql"
    ignored = tmp_path / "readme.txt"
    first.write_text("SELECT 1", encoding="utf-8")
    second.write_text("SELECT 2", encoding="utf-8")
    ignored.write_text("not sql", encoding="utf-8")

    resolved = apply_sql._iter_sql_files([tmp_path, first])
    assert resolved == [first, second]
    with pytest.raises(SystemExit, match="SQL path not found"):
        apply_sql._iter_sql_files([tmp_path / "missing.sql"])


def test_database_url_resolution_prefers_config_then_environment(
    monkeypatch,
) -> None:
    import riskapp_server.core.config as config

    monkeypatch.setattr(config, "DATABASE_URL", " sqlite:///config.db ")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///environment.db")
    assert apply_sql._resolve_database_url() == "sqlite:///config.db"

    monkeypatch.setattr(config, "DATABASE_URL", "")
    assert apply_sql._resolve_database_url() == "sqlite:///environment.db"
    monkeypatch.delenv("DATABASE_URL")
    with pytest.raises(SystemExit, match="DATABASE_URL is not set"):
        apply_sql._resolve_database_url()


def test_apply_sql_main_transaction_autocommit_and_empty_directory(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    database = tmp_path / "ops.db"
    monkeypatch.setattr(
        apply_sql,
        "_resolve_database_url",
        lambda: f"sqlite:///{database}",
    )
    split_file = tmp_path / "split.sql"
    split_file.write_text(
        "CREATE TABLE sample (id INTEGER); INSERT INTO sample VALUES (1);",
        encoding="utf-8",
    )
    assert apply_sql.main(["apply_sql", str(split_file)]) == 0

    raw_file = tmp_path / "raw.sql"
    raw_file.write_text("INSERT INTO sample VALUES (2)", encoding="utf-8")
    assert (
        apply_sql.main(["apply_sql", "--autocommit", "--no-split", str(raw_file)]) == 0
    )

    engine = create_engine(f"sqlite:///{database}")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM sample")).scalar() == 2
    engine.dispose()
    assert "Done. Applied 1 file(s)." in capsys.readouterr().out

    empty = tmp_path / "empty"
    empty.mkdir()
    assert apply_sql.main(["apply_sql", str(empty)]) == 2
    assert "No .sql files found" in capsys.readouterr().err


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.body


def test_prune_request_json_success_and_errors(monkeypatch) -> None:
    request = prune_job.urllib.request.Request("https://api.example.test")
    monkeypatch.setattr(
        prune_job.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(b'{"ok": true}'),
    )
    assert prune_job._request_json(request, 5) == {"ok": True}

    monkeypatch.setattr(
        prune_job.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(b"not json"),
    )
    with pytest.raises(SystemExit, match="Non-JSON response"):
        prune_job._request_json(request, 5)

    http_error = urllib.error.HTTPError(
        request.full_url,
        403,
        "Forbidden",
        None,
        io.BytesIO(b"denied"),
    )
    monkeypatch.setattr(
        prune_job.urllib.request,
        "urlopen",
        Mock(side_effect=http_error),
    )
    with pytest.raises(SystemExit, match="HTTP 403 Forbidden: denied"):
        prune_job._request_json(request, 5)

    monkeypatch.setattr(
        prune_job.urllib.request,
        "urlopen",
        Mock(side_effect=urllib.error.URLError("offline")),
    )
    with pytest.raises(SystemExit, match="Network error"):
        prune_job._request_json(request, 5)


def test_login_supports_form_json_paths_and_requires_token(monkeypatch) -> None:
    requests = []

    def request_json(request, timeout):
        requests.append((request, timeout))
        return {"access_token": "access-1"}

    monkeypatch.setattr(prune_job, "_request_json", request_json)
    assert (
        prune_job.login("https://api.example.test/", "a@example.test", "secret")
        == "access-1"
    )
    request, timeout = requests[-1]
    assert request.full_url == "https://api.example.test/login"
    assert request.get_header("Content-type") == "application/x-www-form-urlencoded"
    assert b"username=a%40example.test" in request.data
    assert timeout == 20

    monkeypatch.setenv("RISKAPP_LOGIN_MODE", "json")
    monkeypatch.setenv("RISKAPP_LOGIN_PATH", "auth/login")
    monkeypatch.setattr(
        prune_job,
        "_request_json",
        lambda request, timeout: (
            requests.append((request, 20)) or {"token": "fallback-token"}
        ),
    )
    assert prune_job.login("https://api.example.test", "a@b.test", "pw") == (
        "fallback-token"
    )
    assert json.loads(requests[-1][0].data) == {
        "email": "a@b.test",
        "password": "pw",
    }

    monkeypatch.setattr(
        prune_job,
        "_request_json",
        lambda *_args, **_kwargs: {"detail": "ok"},
    )
    with pytest.raises(SystemExit, match="no token found"):
        prune_job.login("https://api.example.test", "a@b.test", "pw")


def test_prune_request_and_cli_main(monkeypatch, capsys) -> None:
    captured = []
    monkeypatch.setenv("RISKAPP_PRUNE_PATH", "maintenance/{project_id}/prune")
    monkeypatch.setattr(
        prune_job,
        "_request_json",
        lambda request, timeout: captured.append((request, timeout)) or {"deleted": 3},
    )
    assert prune_job.prune("https://api.example.test/", "token", "p-1", 30) == {
        "deleted": 3
    }
    request, timeout = captured[-1]
    assert request.full_url.endswith("/maintenance/p-1/prune?days=30")
    assert request.get_header("Authorization") == "Bearer token"
    assert timeout == 60

    monkeypatch.delenv("RISKAPP_PRUNE_PATH")
    monkeypatch.setenv("RISKAPP_ADMIN_EMAIL", "admin@example.test")
    monkeypatch.setenv("RISKAPP_ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("RISKAPP_BASE_URL", "https://api.example.test")
    monkeypatch.setattr(prune_job, "login", Mock(return_value="token-2"))
    monkeypatch.setattr(prune_job, "prune", Mock(return_value={"deleted": 9}))
    assert prune_job.main(["prune_job", "project-1", "45"]) == 0
    assert '"deleted": 9' in capsys.readouterr().out

    monkeypatch.delenv("RISKAPP_ADMIN_EMAIL")
    with pytest.raises(SystemExit, match="Missing env var"):
        prune_job._env("RISKAPP_ADMIN_EMAIL")


def test_server_entrypoint_environment_flags(monkeypatch) -> None:
    run = Mock()
    monkeypatch.setattr("uvicorn.run", run)
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("RISKAPP_HOST", "0.0.0.0")
    monkeypatch.setenv("RISKAPP_PORT", "9000")
    monkeypatch.setenv("RISKAPP_RELOAD", "yes")
    assert server_main.main() == 0
    run.assert_called_once_with(
        "riskapp_server.main.app:app",
        host="0.0.0.0",
        port=9000,
        reload=True,
    )
    monkeypatch.delenv("RISKAPP_RELOAD")
    assert server_main._env_flag("RISKAPP_RELOAD", False) is False


@pytest.mark.asyncio
async def test_https_middleware_allows_rejects_and_honors_forwarded_proto(
    monkeypatch,
) -> None:
    middleware = object.__new__(https_only_middleware.HttpsOnlyMiddleware)

    async def call_next(_request):
        return "next"

    request = SimpleNamespace(
        url=SimpleNamespace(scheme="http"),
        headers={},
    )

    monkeypatch.setattr(https_only_middleware, "ENFORCE_HTTPS", False)
    assert await middleware.dispatch(request, call_next) == "next"

    monkeypatch.setattr(https_only_middleware, "ENFORCE_HTTPS", True)
    monkeypatch.setattr(https_only_middleware, "TRUST_X_FORWARDED_PROTO", False)
    response = await middleware.dispatch(request, call_next)
    assert response.status_code == 400

    monkeypatch.setattr(https_only_middleware, "TRUST_X_FORWARDED_PROTO", True)
    request.headers = {"x-forwarded-proto": "HTTPS, http"}
    assert await middleware.dispatch(request, call_next) == "next"
