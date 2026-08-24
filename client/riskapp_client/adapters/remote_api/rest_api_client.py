from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request

from riskapp_client.adapters.mappers.action_assessment_mapper import (
    action_from_mapping,
    assessment_from_mapping,
)
from riskapp_client.adapters.mappers.scored_entity_mapper import (
    scored_entity_from_mapping,
)
from riskapp_client.domain.domain_models import (
    Action,
    Assessment,
    HelpDeskTicket,
    Member,
    Opportunity,
    Project,
    Risk,
)
from riskapp_client.domain.scored_entity_fields import SCORED_ENTITY_META_KEYS
from riskapp_client.utils.urls import UrlPolicy, validate_base_url

_MAX_RESPONSE_BYTES = 5_000_000

logger = logging.getLogger(__name__)


class _SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):

    def __init__(self, *, allowed_scheme: str, allowed_netloc: str) -> None:
        super().__init__()
        self._allowed_scheme = allowed_scheme
        self._allowed_netloc = allowed_netloc

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme and parsed.scheme != self._allowed_scheme:
            raise urllib.error.HTTPError(
                newurl, code, "Cross-scheme redirect not allowed", headers, fp
            )
        if parsed.netloc and parsed.netloc != self._allowed_netloc:
            raise urllib.error.HTTPError(
                newurl, code, "Cross-origin redirect not allowed", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _jwt_sub(token: str) -> str | None:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        data = json.loads(
            base64.urlsafe_b64decode(payload_b64.encode("ascii")).decode("utf-8")
        )
        if not isinstance(data, dict):
            return None
        return str(data.get("sub")) if data.get("sub") else None
    except (
        ValueError,
        TypeError,
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return None


class ApiError(RuntimeError):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


def _read_limited(response, *, status: int = 0) -> bytes:
    raw = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise ApiError(status, "Response too large")
    return raw


def _load_json(raw: bytes, *, status: int = 0) -> object:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApiError(status, "Server returned invalid JSON") from exc


def _http_error_detail(exc: urllib.error.HTTPError) -> str:
    raw = _read_limited(exc, status=exc.code).decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw) if raw else {}
        detail = payload.get("detail", raw) if isinstance(payload, dict) else raw
    except json.JSONDecodeError:
        detail = raw
    return str(detail or exc.reason)


def register_account(
    base_url: str,
    email: str,
    password: str,
    *,
    timeout_s: int = 10,
    url_policy: UrlPolicy | None = None,
) -> dict:
    if url_policy is None:
        url_policy = UrlPolicy(
            allow_http_anywhere=os.getenv("RISKAPP_ALLOW_HTTP", "").strip() == "1"
        )
    validated_url = validate_base_url(base_url, url_policy)
    parsed = urllib.parse.urlparse(validated_url)
    url = f"{validated_url}/register"
    data = json.dumps({"email": email, "password": password}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "RiskAppClient/1.0",
    }
    handlers: list[urllib.request.BaseHandler] = [
        _SameOriginRedirectHandler(
            allowed_scheme=parsed.scheme,
            allowed_netloc=parsed.netloc,
        )
    ]
    if parsed.scheme == "https":
        handlers.insert(
            0,
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with opener.open(req, timeout=timeout_s) as resp:
            payload = _load_json(_read_limited(resp))
            if not isinstance(payload, dict):
                raise ApiError(0, "Server returned an unexpected JSON payload")
            return payload
    except urllib.error.HTTPError as exc:
        raise ApiError(exc.code, _http_error_detail(exc)) from exc
    except urllib.error.URLError as exc:
        raise ApiError(0, f"Cannot reach server: {exc}") from exc


class ApiBackend:
    """Backend client."""

    def __init__(
        self,
        base_url: str,
        email: str,
        password: str,
        *,
        timeout_s: int = 6,
        url_policy: UrlPolicy | None = None,
    ) -> None:
        if url_policy is None:
            url_policy = UrlPolicy(
                allow_http_anywhere=os.getenv("RISKAPP_ALLOW_HTTP", "").strip() == "1"
            )
        self.base_url = validate_base_url(base_url, url_policy)
        parsed_base = urllib.parse.urlparse(self.base_url)
        handlers: list[urllib.request.BaseHandler] = [
            _SameOriginRedirectHandler(
                allowed_scheme=parsed_base.scheme,
                allowed_netloc=parsed_base.netloc,
            )
        ]
        if parsed_base.scheme == "https":
            ssl_context = ssl.create_default_context()
            handlers.insert(0, urllib.request.HTTPSHandler(context=ssl_context))
        self._opener = urllib.request.build_opener(*handlers)
        self.email = email
        self.timeout_s = timeout_s
        self.user_id: str | None = None
        self.token: str | None = None
        self.refresh_token: str | None = None
        self.is_superuser: bool = False
        self._login(password)
        self._fetch_me()

    def _req(
        self,
        method: str,
        path: str,
        *,
        json_body: object | None = None,
        form_body: dict[str, str] | None = None,
        auth: bool = True,
        _retry_on_401: bool = True,
    ) -> object | None:
        if not path.startswith("/"):
            raise ValueError("API path must start with '/'")
        method_up = (method or "").strip().upper()
        if method_up not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError(f"Unsupported HTTP method: {method_up}")
        url = f"{self.base_url}{path}"
        headers: dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": "RiskAppClient/1.0",
        }
        data: bytes | None = None
        if auth:
            if not self.token:
                raise ApiError(401, "Not logged in")
            headers["Authorization"] = f"Bearer {self.token}"
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif form_body is not None:
            data = urllib.parse.urlencode(form_body).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=data, headers=headers, method=method_up)
        try:
            with self._opener.open(req, timeout=self.timeout_s) as resp:
                content_type = (
                    (resp.headers.get("Content-Type") or "")
                    .split(";", 1)[0]
                    .strip()
                    .lower()
                )
                raw_bytes = _read_limited(resp)
                if not raw_bytes:
                    return None
                if content_type not in {"application/json", ""}:
                    raise ApiError(0, f"Unexpected Content-Type: {content_type}")
                return _load_json(raw_bytes)
        except urllib.error.HTTPError as exc:
            if exc.code == 401 and auth and _retry_on_401 and self.refresh_token:
                try:
                    self._refresh_access_token()
                    return self._req(
                        method,
                        path,
                        json_body=json_body,
                        form_body=form_body,
                        auth=auth,
                        _retry_on_401=False,
                    )
                except (ValueError, TypeError):
                    pass
            raise ApiError(exc.code, _http_error_detail(exc)) from exc
        except urllib.error.URLError as exc:
            raise ApiError(0, f"Cannot reach server: {exc}") from exc

    def _login(self, password: str) -> None:
        j = self._req(
            "POST",
            "/login",
            form_body={"username": self.email, "password": password},
            auth=False,
        )
        token = (j or {}).get("access_token")
        if not token:
            raise ApiError(401, f"Login failed: {j}")
        self.token = token
        self.refresh_token = (j or {}).get("refresh_token")
        self.user_id = _jwt_sub(token)

    def _refresh_access_token(self) -> None:
        if not self.refresh_token:
            raise ApiError(401, "Missing refresh token")
        j = self._req(
            "POST",
            "/refresh",
            json_body={"refresh_token": self.refresh_token},
            auth=False,
            _retry_on_401=False,
        )
        token = (j or {}).get("access_token")
        if not token:
            raise ApiError(401, f"Refresh failed: {j}")
        self.token = token
        if (j or {}).get("refresh_token"):
            self.refresh_token = (j or {}).get("refresh_token")
        self.user_id = _jwt_sub(token)

    def _fetch_me(self) -> None:
        try:
            j = self._req("GET", "/users/me")
            if j and isinstance(j, dict):
                self.is_superuser = bool(j.get("is_superuser", False))
        except (ValueError, TypeError):
            self.is_superuser = False

    def _to_project(self, j) -> Project:
        return Project(
            id=str(j["id"]),
            name=j.get("name", ""),
            description=j.get("description") or "",
            created_by=str(j.get("created_by") or ""),
        )

    def _to_risk(self, j) -> Risk:
        return scored_entity_from_mapping(j, model_cls=Risk)

    def _to_opportunity(self, j) -> Opportunity:
        return scored_entity_from_mapping(j, model_cls=Opportunity)

    def _to_action(self, j) -> Action:
        return action_from_mapping(j)

    def _to_ticket(self, j: dict) -> HelpDeskTicket:
        return HelpDeskTicket(
            id=str(j["id"]),
            project_id=str(j.get("project_id") or ""),
            title=str(j.get("title") or ""),
            description=str(j.get("description") or ""),
            category=str(j.get("category") or "other"),
            priority=str(j.get("priority") or "medium"),
            status=str(j.get("status") or "open"),
            reporter_email=str(j.get("reporter_email") or ""),
            created_at=str(j.get("created_at") or ""),
            updated_at=str(j.get("updated_at") or ""),
            version=int(j.get("version") or 0),
            is_deleted=bool(j.get("is_deleted", False)),
        )

    def _build_scored_payload(
        self, title: str, probability: int, impact: int, meta: dict
    ) -> dict:
        """Helper to build consistent JSON payload for Risks and Opportunities."""
        body = {"title": title, "probability": int(probability), "impact": int(impact)}
        for k in SCORED_ENTITY_META_KEYS:
            v = meta.get(k)
            if v is not None and str(v).strip() != "":
                body[k] = v
        return body

    def _build_list_qs(self, **kwargs) -> str:
        """Build URL query string while omitting None values."""
        params = {
            k: str(int(v)) if isinstance(v, bool) else str(v)
            for k, v in kwargs.items()
            if v is not None
        }
        return urllib.parse.urlencode(params)

    def list_projects(self) -> list[Project]:
        j = self._req("GET", "/projects")
        return [self._to_project(x) for x in (j or [])]

    def create_project(self, *, name: str, description: str = "") -> Project:
        """Create a project on the server.

        This is used by the offline-first sync when promoting a local-only project
        to a real server project.
        """
        body = {"name": str(name or "Project"), "description": str(description or "")}
        j = self._req("POST", "/projects", json_body=body)
        return self._to_project(j)

    def delete_project(self, project_id: str) -> None:
        """Permanently delete a project on the server (superadmin only)."""
        self._req("DELETE", f"/projects/{project_id}")

    def _to_assessment(self, j) -> Assessment:
        return assessment_from_mapping(j)

    # --- Opportunities ---

    def list_opportunities(
        self,
        project_id: str,
        *,
        search: str | None = None,
        min_score: int | None = None,
        max_score: int | None = None,
        status: str | None = None,
        category: str | None = None,
        owner_user_id: str | None = None,
        owner_unassigned: bool | None = None,
        from_date: str | None = None,  # "YYYY-MM-DD"
        to_date: str | None = None,  # "YYYY-MM-DD"
    ) -> list[Opportunity]:
        qs = self._build_list_qs(
            search=search,
            min_score=min_score,
            max_score=max_score,
            status=status,
            category=category,
            owner_user_id=owner_user_id,
            owner_unassigned=owner_unassigned,
            from_date=from_date,
            to_date=to_date,
        )

        path = f"/projects/{project_id}/opportunities" + (f"?{qs}" if qs else "")
        j = self._req("GET", path)
        return [self._to_opportunity(x) for x in (j or [])]

    def opportunities_report(
        self,
        project_id: str,
        *,
        search: str | None = None,
        min_score: int | None = None,
        max_score: int | None = None,
        status: str | None = None,
        category: str | None = None,
        owner_user_id: str | None = None,
        owner_unassigned: bool | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> dict:
        qs = self._build_list_qs(
            search=search,
            min_score=min_score,
            max_score=max_score,
            status=status,
            category=category,
            owner_user_id=owner_user_id,
            owner_unassigned=owner_unassigned,
            from_date=from_date,
            to_date=to_date,
        )
        path = f"/projects/{project_id}/opportunities/report" + (f"?{qs}" if qs else "")
        return dict(self._req("GET", path) or {})

    def create_opportunity(
        self, project_id: str, *, title: str, probability: int, impact: int, **meta
    ) -> Opportunity:
        body = self._build_scored_payload(title, probability, impact, meta)
        j = self._req("POST", f"/projects/{project_id}/opportunities", json_body=body)
        return self._to_opportunity(j)

    def update_opportunity(
        self,
        project_id: str,
        opportunity_id: str,
        *,
        title: str,
        probability: int,
        impact: int,
        base_version: int | None = None,
        **meta,
    ) -> Opportunity:
        """Update opportunity."""
        body = self._build_scored_payload(title, probability, impact, meta)

        if base_version is not None:
            body["base_version"] = int(base_version)

        j = self._req(
            "PATCH",
            f"/projects/{project_id}/opportunities/{opportunity_id}",
            json_body=body,
        )
        return self._to_opportunity(j)

    def delete_opportunity(self, project_id: str, opportunity_id: str) -> None:
        self._req(
            "DELETE",
            f"/projects/{project_id}/opportunities/{opportunity_id}",
        )

    def list_assessments(
        self, project_id: str, item_type: str, item_id: str
    ) -> list[Assessment]:
        prefix = "risks" if item_type == "risk" else "opportunities"
        j = self._req("GET", f"/projects/{project_id}/{prefix}/{item_id}/assessments")
        return [self._to_assessment(x) for x in (j or [])]

    def upsert_my_assessment(
        self,
        project_id: str,
        item_type: str,
        item_id: str,
        probability: int,
        impact: int,
        notes: str | None = None,
    ) -> Assessment:
        prefix = "risks" if item_type == "risk" else "opportunities"
        j = self._req(
            "PUT",
            f"/projects/{project_id}/{prefix}/{item_id}/assessment",
            json_body={
                "probability": int(probability),
                "impact": int(impact),
                "notes": (notes or ""),
            },
        )
        return self._to_assessment(j)

    def current_user_id(self) -> str | None:
        return self.user_id

    def list_risks(
        self,
        project_id: str,
        *,
        search: str | None = None,
        min_score: int | None = None,
        max_score: int | None = None,
        status: str | None = None,
        category: str | None = None,
        owner_user_id: str | None = None,
        owner_unassigned: bool | None = None,
        from_date: (
            str | None
        ) = None,  # "YYYY-MM-DD" (or pass a date and .isoformat() before calling)
        to_date: str | None = None,  # "YYYY-MM-DD"
    ) -> list[Risk]:
        qs = self._build_list_qs(
            search=search,
            min_score=min_score,
            max_score=max_score,
            status=status,
            category=category,
            owner_user_id=owner_user_id,
            owner_unassigned=owner_unassigned,
            from_date=from_date,
            to_date=to_date,
        )
        path = f"/projects/{project_id}/risks" + (f"?{qs}" if qs else "")
        j = self._req("GET", path)
        return [self._to_risk(x) for x in (j or [])]

    def risks_report(
        self,
        project_id: str,
        *,
        search: str | None = None,
        min_score: int | None = None,
        max_score: int | None = None,
        status: str | None = None,
        category: str | None = None,
        owner_user_id: str | None = None,
        owner_unassigned: bool | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> dict:
        qs = self._build_list_qs(
            search=search,
            min_score=min_score,
            max_score=max_score,
            status=status,
            category=category,
            owner_user_id=owner_user_id,
            owner_unassigned=owner_unassigned,
            from_date=from_date,
            to_date=to_date,
        )
        path = f"/projects/{project_id}/risks/report" + (f"?{qs}" if qs else "")
        return dict(self._req("GET", path) or {})

    def create_risk(
        self, project_id: str, *, title: str, probability: int, impact: int, **meta
    ) -> Risk:
        body = self._build_scored_payload(title, probability, impact, meta)
        j = self._req("POST", f"/projects/{project_id}/risks", json_body=body)
        return self._to_risk(j)

    def update_risk(
        self,
        project_id: str,
        risk_id: str,
        *,
        title: str,
        probability: int,
        impact: int,
        base_version: int | None = None,
        **meta,
    ) -> Risk:
        """Update risk."""
        body = self._build_scored_payload(title, probability, impact, meta)
        if base_version is not None:
            body["base_version"] = int(base_version)

        j = self._req(
            "PATCH", f"/projects/{project_id}/risks/{risk_id}", json_body=body
        )
        return self._to_risk(j)

    def delete_risk(self, project_id: str, risk_id: str) -> None:
        self._req("DELETE", f"/projects/{project_id}/risks/{risk_id}")

    def sync_pull(
        self,
        project_id: str,
        since_iso: str,
        *,
        limit_per_entity: int | None = None,
        cursors: dict[str, str] | None = None,
    ):
        body: dict[str, object] = {"project_id": project_id, "since": since_iso}
        if limit_per_entity is not None:
            body["limit_per_entity"] = int(limit_per_entity)
            if cursors:
                body["cursors"] = cursors
        return self._req("POST", f"/projects/{project_id}/sync/pull", json_body=body)

    def sync_push(self, project_id: str, changes):
        return self._req(
            "POST",
            f"/projects/{project_id}/sync/push",
            json_body={"project_id": project_id, "changes": changes},
        )

    def create_snapshot(self, project_id: str, *, kind: str | None = None):
        if kind:
            qs = urllib.parse.urlencode({"kind": kind})
            return self._req("POST", f"/projects/{project_id}/snapshots?{qs}")
        return self._req("POST", f"/projects/{project_id}/snapshots")

    def latest_snapshot(self, project_id: str, *, kind: str = "risks"):
        qs = urllib.parse.urlencode({"kind": kind})
        return self._req("GET", f"/projects/{project_id}/snapshots/latest?{qs}")

    def list_actions(self, project_id: str) -> list[Action]:
        j = self._req("GET", f"/projects/{project_id}/actions")
        return [self._to_action(x) for x in (j or [])]

    def create_action(
        self,
        project_id: str,
        *,
        target_type: str,
        target_id: str,
        kind: str,
        title: str,
        description: str,
        status: str,
        owner_user_id: str | None,
    ) -> Action:
        body = {
            "kind": kind,
            "title": title,
            "description": description or None,
            "owner_user_id": owner_user_id,
        }
        if status:
            body["status"] = status
        if target_type == "risk":
            body["risk_id"] = target_id
        else:
            body["opportunity_id"] = target_id

        j = self._req("POST", f"/projects/{project_id}/actions", json_body=body)
        return self._to_action(j)

    def update_action(
        self,
        project_id: str,
        action_id: str,
        *,
        target_type: str,
        target_id: str,
        kind: str,
        title: str,
        description: str,
        status: str,
        owner_user_id: str | None,
    ) -> Action:
        """Update action."""
        body = {
            "kind": kind,
            "title": title,
            "description": description or None,
            "status": status,
            "owner_user_id": owner_user_id,
        }
        if target_type == "risk":
            body["risk_id"] = target_id
            body["opportunity_id"] = None
        else:
            body["risk_id"] = None
            body["opportunity_id"] = target_id

        j = self._req(
            "PATCH", f"/projects/{project_id}/actions/{action_id}", json_body=body
        )
        return self._to_action(j)

    def top_history(
        self,
        project_id: str,
        *,
        kind: str = "risks",
        limit: int = 10,
        from_ts: str | None = None,
        to_ts: str | None = None,
    ):
        params = {"kind": kind, "limit": str(int(limit))}
        if from_ts:
            params["from_ts"] = from_ts
        if to_ts:
            params["to_ts"] = to_ts
        qs = urllib.parse.urlencode(params)
        return self._req("GET", f"/projects/{project_id}/top-history?{qs}")

    def list_members(self, project_id: str) -> list[Member]:
        j = self._req("GET", f"/projects/{project_id}/members")
        out: list[Member] = []
        for m in j or []:
            out.append(
                Member(
                    user_id=str(m.get("user_id") or ""),
                    email=str(m.get("email") or ""),
                    role=str(m.get("role") or ""),
                    is_superuser=bool(m.get("is_superuser", False)),
                    created_at=str(m.get("created_at") or "") or None,
                )
            )
        return out

    def add_member(self, project_id: str, *, user_email: str, role: str) -> None:
        self._req(
            "POST",
            f"/projects/{project_id}/members",
            json_body={"user_email": user_email, "role": role},
        )

    def remove_member(self, project_id: str, *, member_user_id: str) -> None:
        self._req("DELETE", f"/projects/{project_id}/members/{member_user_id}")

    # --- Help Desk ----------------------------------------------------------

    def list_helpdesk_tickets(self, project_id: str) -> list[HelpDeskTicket]:
        j = self._req("GET", f"/projects/{project_id}/helpdesk/tickets")
        return [self._to_ticket(x) for x in (j or [])]

    def create_helpdesk_ticket(
        self,
        project_id: str,
        *,
        title: str,
        description: str = "",
        category: str = "other",
        priority: str = "medium",
        reporter_email: str = "",
    ) -> HelpDeskTicket:
        body = {
            "title": title,
            "description": description,
            "category": category,
            "priority": priority,
            "reporter_email": reporter_email,
        }
        j = self._req(
            "POST", f"/projects/{project_id}/helpdesk/tickets", json_body=body
        )
        return self._to_ticket(j)

    def update_helpdesk_ticket(
        self,
        project_id: str,
        ticket_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        category: str | None = None,
        priority: str | None = None,
        status: str | None = None,
    ) -> HelpDeskTicket:
        body: dict = {}
        if title is not None:
            body["title"] = title
        if description is not None:
            body["description"] = description
        if category is not None:
            body["category"] = category
        if priority is not None:
            body["priority"] = priority
        if status is not None:
            body["status"] = status
        j = self._req(
            "PATCH",
            f"/projects/{project_id}/helpdesk/tickets/{ticket_id}",
            json_body=body,
        )
        return self._to_ticket(j)

    def delete_helpdesk_ticket(self, project_id: str, ticket_id: str) -> None:
        self._req("DELETE", f"/projects/{project_id}/helpdesk/tickets/{ticket_id}")
