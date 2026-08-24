"""HTTP boundary tests for the desktop API client."""

from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import Mock

import pytest
import riskapp_client.adapters.remote_api.rest_api_client as api
from riskapp_client.adapters.remote_api.rest_api_client import ApiBackend, ApiError
from riskapp_client.domain.domain_models import Opportunity, Risk
from riskapp_client.utils.urls import UrlPolicy


class FakeResponse:
    def __init__(self, payload: bytes | str, content_type: str = "application/json"):
        self.payload = payload.encode() if isinstance(payload, str) else payload
        self.headers = {"Content-Type": content_type}

    def read(self, size: int = -1) -> bytes:
        return self.payload if size < 0 else self.payload[:size]

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


class FakeOpener:
    def __init__(self, effects):
        self.effects = list(effects)
        self.calls: list[tuple[urllib.request.Request, int]] = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        effect = self.effects.pop(0)
        if isinstance(effect, BaseException):
            raise effect
        return effect


def _http_error(status: int, body: bytes = b'{"detail":"failed"}'):
    return urllib.error.HTTPError(
        "https://api.example.test/resource",
        status,
        "failure",
        {},
        io.BytesIO(body),
    )


def _token(subject: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"sub": subject}).encode()).rstrip(
        b"="
    )
    return f"header.{payload.decode()}.signature"


def _bare_backend(opener=None) -> ApiBackend:
    backend = ApiBackend.__new__(ApiBackend)
    backend.base_url = "https://api.example.test"
    backend.email = "user@example.test"
    backend.timeout_s = 7
    backend.user_id = "user-1"
    backend.token = "access-old"
    backend.refresh_token = "refresh-old"
    backend.is_superuser = False
    backend._opener = opener or FakeOpener([])
    return backend


SCORED = {
    "id": "entity-1",
    "project_id": "project-1",
    "title": "Scored item",
    "probability": 3,
    "impact": 4,
    "version": 2,
}
ACTION = {
    "id": "action-1",
    "project_id": "project-1",
    "risk_id": "risk-1",
    "opportunity_id": None,
    "kind": "mitigation",
    "title": "Act",
}
ASSESSMENT = {
    "id": "assessment-1",
    "item_id": "entity-1",
    "assessor_user_id": "user-1",
    "probability": 2,
    "impact": 5,
}
TICKET = {
    "id": "ticket-1",
    "project_id": "project-1",
    "title": "Problem",
}


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        (_token("user-123"), "user-123"),
        ("not-a-jwt", None),
        ("a.invalid-json.c", None),
        ("a.W10.c", None),
    ],
)
def test_jwt_subject_parsing_is_defensive(token, expected) -> None:
    assert api._jwt_sub(token) == expected


def test_response_helpers_bound_and_validate_server_data(monkeypatch) -> None:
    monkeypatch.setattr(api, "_MAX_RESPONSE_BYTES", 4)
    assert api._read_limited(io.BytesIO(b"1234"), status=200) == b"1234"
    with pytest.raises(ApiError, match="Response too large") as exc_info:
        api._read_limited(io.BytesIO(b"12345"), status=200)
    assert exc_info.value.status == 200

    assert api._load_json(b'{"ok":true}') == {"ok": True}
    with pytest.raises(ApiError, match="invalid JSON"):
        api._load_json(b"not json", status=502)
    with pytest.raises(ApiError, match="invalid JSON"):
        api._load_json(b"\xff", status=502)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b'{"detail":"invalid credentials"}', "invalid credentials"),
        (b"plain failure", "plain failure"),
        (b"", "failure"),
        (b"[]", "[]"),
    ],
)
def test_http_error_detail_handles_json_text_and_empty_bodies(body, expected) -> None:
    assert api._http_error_detail(_http_error(400, body)) == expected


def test_redirect_handler_allows_only_same_origin() -> None:
    handler = api._SameOriginRedirectHandler(
        allowed_scheme="https", allowed_netloc="api.example.test"
    )
    request = urllib.request.Request("https://api.example.test/start")

    redirected = handler.redirect_request(
        request,
        io.BytesIO(),
        302,
        "Found",
        {},
        "https://api.example.test/next",
    )
    assert redirected.full_url == "https://api.example.test/next"

    with pytest.raises(urllib.error.HTTPError, match="Cross-origin"):
        handler.redirect_request(
            request, io.BytesIO(), 302, "Found", {}, "https://evil.example/next"
        )
    with pytest.raises(urllib.error.HTTPError, match="Cross-scheme"):
        handler.redirect_request(
            request, io.BytesIO(), 302, "Found", {}, "http://api.example.test/next"
        )


def test_register_account_sends_json_and_returns_mapping(monkeypatch) -> None:
    opener = FakeOpener([FakeResponse('{"id":"user-1"}')])
    monkeypatch.setattr(api.urllib.request, "build_opener", lambda *_: opener)

    result = api.register_account(
        "https://api.example.test/",
        "new@example.test",
        "StrongPassword1!",
        timeout_s=9,
        url_policy=UrlPolicy(),
    )

    assert result == {"id": "user-1"}
    request, timeout = opener.calls[0]
    assert request.full_url == "https://api.example.test/register"
    assert request.get_method() == "POST"
    assert timeout == 9
    assert json.loads(request.data) == {
        "email": "new@example.test",
        "password": "StrongPassword1!",
    }


@pytest.mark.parametrize(
    ("effect", "status", "detail"),
    [
        (FakeResponse("[]"), 0, "unexpected JSON payload"),
        (_http_error(409, b'{"detail":"already exists"}'), 409, "already exists"),
        (urllib.error.URLError("offline"), 0, "Cannot reach server"),
    ],
)
def test_register_account_translates_protocol_failures(
    monkeypatch, effect, status, detail
) -> None:
    monkeypatch.setattr(
        api.urllib.request, "build_opener", lambda *_: FakeOpener([effect])
    )
    with pytest.raises(ApiError, match=detail) as exc_info:
        api.register_account(
            "http://localhost:8000",
            "new@example.test",
            "StrongPassword1!",
            url_policy=UrlPolicy(),
        )
    assert exc_info.value.status == status


def test_backend_initialization_logs_in_and_fetches_current_user(monkeypatch) -> None:
    token = _token("user-42")
    opener = FakeOpener(
        [
            FakeResponse(json.dumps({"access_token": token, "refresh_token": "r1"})),
            FakeResponse('{"is_superuser":true}'),
        ]
    )
    monkeypatch.setattr(api.urllib.request, "build_opener", lambda *_: opener)

    backend = ApiBackend(
        "http://localhost:8000",
        "user@example.test",
        "secret",
        url_policy=UrlPolicy(),
    )

    assert backend.user_id == "user-42"
    assert backend.refresh_token == "r1"
    assert backend.is_superuser is True
    assert [call[0].full_url for call in opener.calls] == [
        "http://localhost:8000/login",
        "http://localhost:8000/users/me",
    ]


def test_request_validates_method_path_auth_and_response_type() -> None:
    backend = _bare_backend(FakeOpener([]))
    with pytest.raises(ValueError, match="start with"):
        backend._req("GET", "projects")
    with pytest.raises(ValueError, match="Unsupported"):
        backend._req("TRACE", "/projects")
    backend.token = None
    with pytest.raises(ApiError, match="Not logged in"):
        backend._req("GET", "/projects")

    backend.token = "token"
    backend._opener = FakeOpener([FakeResponse(b"", "")])
    assert backend._req("DELETE", "/projects/project-1") is None

    backend._opener = FakeOpener([FakeResponse("plain", "text/plain")])
    with pytest.raises(ApiError, match="Unexpected Content-Type"):
        backend._req("GET", "/projects")


def test_request_encodes_json_form_and_network_errors() -> None:
    backend = _bare_backend(FakeOpener([FakeResponse('{"ok":true}', "")]))
    assert backend._req("POST", "/items", json_body={"name": "A"}) == {"ok": True}
    request = backend._opener.calls[0][0]
    assert json.loads(request.data) == {"name": "A"}
    assert request.get_header("Authorization") == "Bearer access-old"
    assert request.get_header("Content-type") == "application/json"

    backend._opener = FakeOpener([FakeResponse('{"ok":true}')])
    backend._req(
        "POST", "/login", form_body={"username": "a+b@example.test"}, auth=False
    )
    request = backend._opener.calls[0][0]
    assert urllib.parse.parse_qs(request.data.decode()) == {
        "username": ["a+b@example.test"]
    }

    backend._opener = FakeOpener([urllib.error.URLError("offline")])
    with pytest.raises(ApiError, match="Cannot reach server"):
        backend._req("GET", "/projects")


def test_request_refreshes_once_after_unauthorized_response() -> None:
    backend = _bare_backend(
        FakeOpener(
            [
                _http_error(401, b'{"detail":"expired"}'),
                FakeResponse(
                    json.dumps(
                        {
                            "access_token": _token("user-2"),
                            "refresh_token": "refresh-new",
                        }
                    )
                ),
                FakeResponse('{"ok":true}'),
            ]
        )
    )

    assert backend._req("GET", "/projects") == {"ok": True}
    assert backend.user_id == "user-2"
    assert backend.refresh_token == "refresh-new"
    assert len(backend._opener.calls) == 3


def test_request_preserves_original_http_error_if_refresh_is_invalid() -> None:
    backend = _bare_backend(FakeOpener([_http_error(401, b'{"detail":"expired"}')]))
    backend._refresh_access_token = Mock(side_effect=ValueError("bad refresh"))

    with pytest.raises(ApiError, match="expired") as exc_info:
        backend._req("GET", "/projects")
    assert exc_info.value.status == 401


def test_login_refresh_and_me_helpers_validate_payloads() -> None:
    backend = _bare_backend()
    backend._req = Mock(return_value={})
    with pytest.raises(ApiError, match="Login failed"):
        backend._login("bad")

    backend._req = Mock(
        return_value={"access_token": _token("login-user"), "refresh_token": "r2"}
    )
    backend._login("good")
    assert backend.user_id == "login-user"

    backend.refresh_token = None
    with pytest.raises(ApiError, match="Missing refresh token"):
        backend._refresh_access_token()
    backend.refresh_token = "r2"
    backend._req = Mock(return_value={})
    with pytest.raises(ApiError, match="Refresh failed"):
        backend._refresh_access_token()

    backend._req = Mock(return_value={"is_superuser": True})
    backend._fetch_me()
    assert backend.is_superuser is True
    backend._req = Mock(side_effect=ValueError("bad payload"))
    backend._fetch_me()
    assert backend.is_superuser is False


def test_project_helpers_and_common_payload_builders() -> None:
    backend = _bare_backend()
    project = {
        "id": "project-1",
        "name": "Project",
        "description": None,
        "created_by": "user-1",
    }
    backend._req = Mock(return_value=[project])
    assert backend.list_projects()[0].description == ""

    backend._req = Mock(return_value=project)
    assert backend.create_project(name="", description=None).name == "Project"
    assert backend._req.call_args.kwargs["json_body"] == {
        "name": "Project",
        "description": "",
    }
    backend.delete_project("project-1")
    assert backend._req.call_args.args == ("DELETE", "/projects/project-1")

    payload = backend._build_scored_payload(
        "Item", 2, 3, {"code": " R-1 ", "category": "", "status": None}
    )
    assert payload == {
        "title": "Item",
        "probability": 2,
        "impact": 3,
        "code": " R-1 ",
    }
    assert urllib.parse.parse_qs(
        backend._build_list_qs(search="a b", owner_unassigned=True, ignored=None)
    ) == {"search": ["a b"], "owner_unassigned": ["1"]}


def test_risk_routes_map_models_filters_reports_and_mutations() -> None:
    backend = _bare_backend()
    backend._req = Mock(return_value=[SCORED])
    risks = backend.list_risks(
        "project-1", search="needle", min_score=2, owner_unassigned=True
    )
    assert isinstance(risks[0], Risk)
    path = backend._req.call_args.args[1]
    query = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
    assert query == {
        "search": ["needle"],
        "min_score": ["2"],
        "owner_unassigned": ["1"],
    }

    backend._req = Mock(return_value={"total": 1})
    assert backend.risks_report("project-1") == {"total": 1}

    backend._req = Mock(return_value=SCORED)
    created = backend.create_risk(
        "project-1", title="Risk", probability=2, impact=4, category="ops"
    )
    assert created.score == 12
    assert backend._req.call_args.args[:2] == (
        "POST",
        "/projects/project-1/risks",
    )

    backend._req = Mock(return_value=SCORED)
    backend.update_risk(
        "project-1",
        "risk-1",
        title="Risk",
        probability=2,
        impact=4,
        base_version=3,
    )
    assert backend._req.call_args.kwargs["json_body"]["base_version"] == 3
    backend.delete_risk("project-1", "risk-1")
    assert backend._req.call_args.args == (
        "DELETE",
        "/projects/project-1/risks/risk-1",
    )


def test_opportunity_and_assessment_routes_map_models_and_targets() -> None:
    backend = _bare_backend()
    backend._req = Mock(return_value=[SCORED])
    opportunities = backend.list_opportunities("project-1", max_score=20)
    assert isinstance(opportunities[0], Opportunity)

    backend._req = Mock(return_value={"total": 1})
    assert backend.opportunities_report("project-1") == {"total": 1}

    backend._req = Mock(return_value=SCORED)
    backend.create_opportunity("project-1", title="Upside", probability=3, impact=5)
    backend.update_opportunity(
        "project-1",
        "opp-1",
        title="Upside",
        probability=3,
        impact=5,
        base_version=None,
    )
    assert "base_version" not in backend._req.call_args.kwargs["json_body"]
    backend.delete_opportunity("project-1", "opp-1")

    backend._req = Mock(return_value=[ASSESSMENT])
    assert backend.list_assessments("project-1", "risk", "risk-1")[0].score == 10
    assert "/risks/risk-1/assessments" in backend._req.call_args.args[1]
    backend._req = Mock(return_value=ASSESSMENT)
    backend.upsert_my_assessment("project-1", "opportunity", "opp-1", 4, 2, None)
    assert "/opportunities/opp-1/assessment" in backend._req.call_args.args[1]
    assert backend._req.call_args.kwargs["json_body"]["notes"] == ""
    assert backend.current_user_id() == "user-1"


def test_sync_snapshot_and_history_routes_shape_requests() -> None:
    backend = _bare_backend()
    backend._req = Mock(return_value={"ok": True})

    backend.sync_pull("project-1", "2026-01-01", cursors={"risks": "x"})
    assert backend._req.call_args.kwargs["json_body"] == {
        "project_id": "project-1",
        "since": "2026-01-01",
    }
    backend.sync_pull(
        "project-1", "2026-01-01", limit_per_entity=25, cursors={"risks": "x"}
    )
    assert backend._req.call_args.kwargs["json_body"]["cursors"] == {"risks": "x"}
    backend.sync_push("project-1", [{"op": "create"}])
    assert backend._req.call_args.kwargs["json_body"]["changes"] == [{"op": "create"}]

    backend.create_snapshot("project-1")
    assert backend._req.call_args.args[1].endswith("/snapshots")
    backend.create_snapshot("project-1", kind="opportunities")
    assert "kind=opportunities" in backend._req.call_args.args[1]
    backend.latest_snapshot("project-1", kind="risks")
    assert "snapshots/latest?kind=risks" in backend._req.call_args.args[1]
    backend.top_history("project-1", kind="risks", limit=5, from_ts="from", to_ts="to")
    query = urllib.parse.parse_qs(
        urllib.parse.urlparse(backend._req.call_args.args[1]).query
    )
    assert query == {
        "kind": ["risks"],
        "limit": ["5"],
        "from_ts": ["from"],
        "to_ts": ["to"],
    }


def test_action_routes_cover_risk_and_opportunity_targets() -> None:
    backend = _bare_backend()
    backend._req = Mock(return_value=[ACTION])
    assert backend.list_actions("project-1")[0].id == "action-1"

    backend._req = Mock(return_value=ACTION)
    backend.create_action(
        "project-1",
        target_type="risk",
        target_id="risk-1",
        kind="mitigation",
        title="Act",
        description="",
        status="",
        owner_user_id=None,
    )
    body = backend._req.call_args.kwargs["json_body"]
    assert body["risk_id"] == "risk-1"
    assert "status" not in body

    opportunity_action = {**ACTION, "risk_id": None, "opportunity_id": "opp-1"}
    backend._req = Mock(return_value=opportunity_action)
    backend.create_action(
        "project-1",
        target_type="opportunity",
        target_id="opp-1",
        kind="exploit",
        title="Act",
        description="Details",
        status="doing",
        owner_user_id="user-2",
    )
    assert backend._req.call_args.kwargs["json_body"]["opportunity_id"] == "opp-1"

    backend.update_action(
        "project-1",
        "action-1",
        target_type="risk",
        target_id="risk-2",
        kind="mitigation",
        title="Act",
        description="",
        status="done",
        owner_user_id=None,
    )
    assert backend._req.call_args.kwargs["json_body"]["opportunity_id"] is None
    backend.update_action(
        "project-1",
        "action-1",
        target_type="opportunity",
        target_id="opp-2",
        kind="exploit",
        title="Act",
        description="",
        status="done",
        owner_user_id=None,
    )
    assert backend._req.call_args.kwargs["json_body"]["risk_id"] is None


def test_member_and_helpdesk_routes_map_defaults_and_partial_updates() -> None:
    backend = _bare_backend()
    backend._req = Mock(
        return_value=[
            {
                "user_id": "user-2",
                "email": "member@example.test",
                "role": "manager",
                "is_superuser": True,
            }
        ]
    )
    member = backend.list_members("project-1")[0]
    assert member.is_superuser is True
    assert member.created_at is None
    backend.add_member("project-1", user_email="new@example.test", role="member")
    backend.remove_member("project-1", member_user_id="user-2")
    assert backend._req.call_args.args[0] == "DELETE"

    backend._req = Mock(return_value=[TICKET])
    ticket = backend.list_helpdesk_tickets("project-1")[0]
    assert ticket.priority == "medium"
    assert ticket.status == "open"

    backend._req = Mock(return_value=TICKET)
    backend.create_helpdesk_ticket("project-1", title="Problem")
    create_body = backend._req.call_args.kwargs["json_body"]
    assert create_body["category"] == "other"
    assert create_body["priority"] == "medium"

    backend.update_helpdesk_ticket(
        "project-1",
        "ticket-1",
        title="Updated",
        priority=None,
        status="resolved",
    )
    assert backend._req.call_args.kwargs["json_body"] == {
        "title": "Updated",
        "status": "resolved",
    }
    backend.update_helpdesk_ticket(
        "project-1",
        "ticket-1",
        description="D",
        category="bug",
        priority="high",
    )
    assert backend._req.call_args.kwargs["json_body"] == {
        "description": "D",
        "category": "bug",
        "priority": "high",
    }
    backend.delete_helpdesk_ticket("project-1", "ticket-1")
    assert backend._req.call_args.args == (
        "DELETE",
        "/projects/project-1/helpdesk/tickets/ticket-1",
    )
