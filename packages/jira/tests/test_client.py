import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from pydantic import SecretStr

from agentic_jira import (
    SCOPES,
    Account,
    AtlassianApp,
    AtlassianAppConfig,
    Grant,
    JiraApiError,
    JiraAuthError,
    JiraConfigError,
    JiraUnauthorizedError,
    Project,
    Site,
    missing_scopes,
)

CLIENT_SECRET = "client-secret-0001"
CONFIG = AtlassianAppConfig(
    client_id="client-1",
    client_secret=SecretStr(CLIENT_SECRET),
    redirect_uri="https://api.example.test/jira/callback",
)
TOKEN = SecretStr("access-token-0001")
REFRESH = SecretStr("refresh-token-0001")

Handler = Callable[[httpx2.Request], httpx2.Response]


def app(handler: Handler) -> AtlassianApp:
    return AtlassianApp(CONFIG, transport=httpx2.MockTransport(handler))


def answers(status: int, body: object) -> tuple[Handler, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(status, json=body)

    return handler, seen


def test_the_authorize_url_asks_for_every_scope_once() -> None:
    url = urlsplit(app(lambda _: httpx2.Response(500)).authorize_url("state-1"))
    query = {key: value[0] for key, value in parse_qs(url.query).items()}

    assert (url.scheme, url.netloc, url.path) == ("https", "auth.atlassian.com", "/authorize")
    assert query == {
        "audience": "api.atlassian.com",
        "client_id": "client-1",
        "scope": " ".join(SCOPES),
        "redirect_uri": CONFIG.redirect_uri,
        "state": "state-1",
        "response_type": "code",
        "prompt": "consent",
    }
    assert "offline_access" in SCOPES
    assert CLIENT_SECRET not in url.query


async def test_exchange_returns_the_grant() -> None:
    handler, seen = answers(
        200,
        {
            "access_token": "at-1",
            "refresh_token": "rt-1",
            "expires_in": 3600,
            "scope": "read:jira-work offline_access",
        },
    )

    grant = await app(handler).exchange("code-1")

    [request] = seen
    assert str(request.url) == "https://auth.atlassian.com/oauth/token"
    assert json.loads(request.content) == {
        "grant_type": "authorization_code",
        "code": "code-1",
        "redirect_uri": CONFIG.redirect_uri,
        "client_id": "client-1",
        "client_secret": CLIENT_SECRET,
    }
    assert grant.access_token == SecretStr("at-1")
    assert grant.refresh_token == SecretStr("rt-1")
    assert grant.scopes == ("read:jira-work", "offline_access")
    assert timedelta(minutes=59) < grant.expires_at - datetime.now(UTC) <= timedelta(hours=1)
    assert "at-1" not in repr(grant) and "rt-1" not in repr(grant)


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_a_refused_code_is_an_auth_error_without_the_code(status: int) -> None:
    handler, _ = answers(status, {"error": "invalid_grant", "error_description": "code-secret"})

    with pytest.raises(JiraAuthError) as refused:
        await app(handler).exchange("code-secret")

    assert refused.value.reason == "exchange"
    assert "code-secret" not in str(refused.value)


async def test_a_grant_without_a_refresh_token_is_refused() -> None:
    handler, _ = answers(200, {"access_token": "at-1", "expires_in": 3600, "scope": ""})

    with pytest.raises(JiraAuthError):
        await app(handler).exchange("code-1")


async def test_refresh_returns_the_rotated_pair() -> None:
    handler, seen = answers(
        200, {"access_token": "at-2", "refresh_token": "rt-2", "expires_in": 60, "scope": "a b"}
    )

    grant = await app(handler).refresh(REFRESH)

    assert json.loads(seen[0].content)["grant_type"] == "refresh_token"
    assert json.loads(seen[0].content)["refresh_token"] == REFRESH.get_secret_value()
    assert (grant.access_token, grant.refresh_token) == (SecretStr("at-2"), SecretStr("rt-2"))


async def test_refresh_keeps_the_token_when_none_comes_back() -> None:
    handler, _ = answers(200, {"access_token": "at-2", "expires_in": 60})

    grant = await app(handler).refresh(REFRESH)

    assert grant.refresh_token == REFRESH
    assert grant.scopes == ()


async def test_a_refused_refresh_is_invalid_grant() -> None:
    handler, _ = answers(
        403, {"error": "invalid_grant", "error_description": "Unknown or invalid refresh token."}
    )

    with pytest.raises(JiraAuthError) as refused:
        await app(handler).refresh(REFRESH)

    assert refused.value.reason == "invalid_grant"
    assert REFRESH.get_secret_value() not in str(refused.value)


async def test_the_account_is_read_with_the_token() -> None:
    handler, seen = answers(200, {"account_id": "acc-1", "name": "Ada", "email": "a@x.test"})

    account = await app(handler).account(TOKEN)

    assert account == Account(account_id="acc-1", name="Ada")
    assert str(seen[0].url) == "https://api.atlassian.com/me"
    assert seen[0].headers["authorization"] == f"Bearer {TOKEN.get_secret_value()}"


async def test_sites_are_the_jira_ones_once_each() -> None:
    handler, seen = answers(
        200,
        [
            {
                "id": "c2",
                "url": "https://zed.atlassian.net",
                "name": "Zed",
                "scopes": ["read:jira-work"],
            },
            {
                "id": "c1",
                "url": "https://acme.atlassian.net",
                "name": "acme",
                "scopes": ["read:jira-work"],
            },
            {
                "id": "c1",
                "url": "https://acme.atlassian.net",
                "name": "acme",
                "scopes": ["read:jira-user"],
            },
            {
                "id": "c3",
                "url": "https://wiki.atlassian.net",
                "name": "Wiki",
                "scopes": ["read:confluence-content.all"],
            },
        ],
    )

    sites = await app(handler).sites(TOKEN)

    assert sites == [
        Site("c1", "https://acme.atlassian.net", "acme"),
        Site("c2", "https://zed.atlassian.net", "Zed"),
    ]
    assert str(seen[0].url) == "https://api.atlassian.com/oauth/token/accessible-resources"


async def test_project_search_pages() -> None:
    handler, seen = answers(
        200,
        {
            "isLast": False,
            "values": [{"id": "10001", "key": "WEB", "name": "Web shop", "self": "x"}],
        },
    )

    page = await app(handler).search_projects(TOKEN, "cloud-1", query="web", start_at=50)

    assert page.projects == (Project("10001", "WEB", "Web shop"),)
    assert page.next_start_at == 51
    url = seen[0].url
    assert url.path == "/ex/jira/cloud-1/rest/api/3/project/search"
    assert dict(url.params) == {
        "startAt": "50",
        "maxResults": "50",
        "orderBy": "name",
        "query": "web",
    }


async def test_the_last_project_page_has_no_next() -> None:
    handler, _ = answers(200, {"isLast": True, "values": []})

    page = await app(handler).search_projects(TOKEN, "cloud-1")

    assert page.projects == () and page.next_start_at is None


async def test_projects_are_looked_up_by_id_in_chunks() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        ids = request.url.params.get_list("id")
        return httpx2.Response(
            200, json={"values": [{"id": i, "key": f"K{i}", "name": f"N{i}"} for i in ids]}
        )

    seen: list[int] = []

    def counting(request: httpx2.Request) -> httpx2.Response:
        seen.append(len(request.url.params.get_list("id")))
        return handler(request)

    ids = [str(n) for n in range(60)]
    found = await app(counting).get_projects(TOKEN, "cloud-1", ids)

    assert seen == [50, 10]
    assert [project.id for project in found] == ids


async def test_a_401_is_unauthorized_and_other_errors_carry_only_the_status() -> None:
    unauthorized, _ = answers(401, {"message": "Unauthorized"})
    broken, _ = answers(503, {"message": f"upstream said {TOKEN.get_secret_value()}"})

    with pytest.raises(JiraUnauthorizedError):
        await app(unauthorized).sites(TOKEN)
    with pytest.raises(JiraApiError) as failed:
        await app(broken).sites(TOKEN)

    assert str(failed.value) == "Atlassian answered 503"


async def test_a_network_error_names_only_its_kind() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectTimeout(f"timed out with {CLIENT_SECRET}")

    with pytest.raises(JiraApiError) as token_call:
        await app(handler).refresh(REFRESH)
    with pytest.raises(JiraApiError) as api_call:
        await app(handler).account(TOKEN)

    assert str(token_call.value) == "Atlassian could not be reached: ConnectTimeout"
    assert str(api_call.value) == "Atlassian could not be reached: ConnectTimeout"


def test_a_grant_round_trips_through_its_secret() -> None:
    grant = Grant(
        access_token=SecretStr("at-1"),
        refresh_token=SecretStr("rt-1"),
        expires_at=datetime(2026, 11, 16, 12, 0, tzinfo=UTC),
        scopes=("read:jira-work",),
    )

    assert Grant.from_secret(grant.to_secret()) == grant


def test_missing_scopes_are_listed_in_order() -> None:
    assert missing_scopes(SCOPES) == ()
    assert missing_scopes(["offline_access", "read:jira-work", "read:me"]) == (
        "write:jira-work",
        "manage:jira-webhook",
        "read:jira-user",
    )


def test_the_client_secret_comes_from_a_file(tmp_path: Path) -> None:
    secret_file = tmp_path / "secret"
    secret_file.write_text(f"{CLIENT_SECRET}\n", encoding="ascii")

    config = AtlassianAppConfig.from_file("client-1", secret_file, CONFIG.redirect_uri)

    assert config.client_secret == SecretStr(CLIENT_SECRET)
    assert CLIENT_SECRET not in repr(config)
    with pytest.raises(JiraConfigError):
        AtlassianAppConfig.from_file("client-1", tmp_path / "missing", CONFIG.redirect_uri)
    (tmp_path / "empty").write_text("", encoding="ascii")
    with pytest.raises(JiraConfigError):
        AtlassianAppConfig.from_file("client-1", tmp_path / "empty", CONFIG.redirect_uri)
