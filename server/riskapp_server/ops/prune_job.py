"""Call the project retention endpoint from cron or CI."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def _env(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise SystemExit(f"Missing env var: {name}")
    return v


def _request_json(req: urllib.request.Request, timeout: int) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {e.code} {e.reason}: {raw[:2000]}") from e
    except urllib.error.URLError as e:
        raise SystemExit(f"Network error: {e}") from e

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise SystemExit(f"Non-JSON response: {raw[:2000]}") from None


def login(base_url: str, email: str, password: str) -> str:
    login_path = os.getenv("RISKAPP_LOGIN_PATH", "/login").strip() or "/login"
    login_mode = os.getenv("RISKAPP_LOGIN_MODE", "form").strip().lower() or "form"

    url = base_url.rstrip("/") + (
        login_path if login_path.startswith("/") else "/" + login_path
    )

    if login_mode == "json":
        body = json.dumps({"email": email, "password": password}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
    else:
        # Default to the OAuth2PasswordRequestForm payload.
        body = urllib.parse.urlencode({"username": email, "password": password}).encode(
            "utf-8"
        )
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    payload = _request_json(req, timeout=20)

    token = payload.get("access_token") or payload.get("token")
    if not token:
        raise SystemExit(
            f"Login succeeded but no token found in response keys: {list(payload.keys())}"
        )
    return str(token)


def prune(base_url: str, token: str, project_id: str, days: int) -> dict[str, Any]:
    tpl = os.getenv(
        "RISKAPP_PRUNE_PATH", "/projects/{project_id}/maintenance/prune"
    ).strip()
    if not tpl:
        tpl = "/projects/{project_id}/maintenance/prune"
    path = tpl.format(project_id=project_id)
    if not path.startswith("/"):
        path = "/" + path

    url = base_url.rstrip("/") + f"{path}?days={int(days)}"
    req = urllib.request.Request(
        url,
        data=b"{}",
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    return _request_json(req, timeout=60)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m riskapp_server.ops.prune_job",
        description="Call the admin-only retention prune endpoint.",
    )
    parser.add_argument("project_id")
    parser.add_argument(
        "days",
        nargs="?",
        type=int,
        default=int(os.getenv("RETENTION_DAYS", "180")),
        help="Retention window in days (default: env RETENTION_DAYS or 180).",
    )
    args = parser.parse_args(argv[1:])

    base_url = os.getenv("RISKAPP_BASE_URL", "http://127.0.0.1:8000")
    email = _env("RISKAPP_ADMIN_EMAIL")
    password = _env("RISKAPP_ADMIN_PASSWORD")

    token = login(base_url, email, password)
    res = prune(base_url, token, args.project_id, args.days)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
