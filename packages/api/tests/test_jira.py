import logging
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api import create_app
from agentic_api.app import FakeInProductionError
from agentic_api.jira.routes import STATE_TTL_S
from agentic_api.settings import Settings
from agentic_jira import (
    FAKE_ACCOUNT,
    FAKE_CODE,
    SCOPES,
    AtlassianApp,
    FakeAtlassian,
    JiraConfigError,
)
from agentic_secrets import generate_key_file
from agentic_store import AuditEvent, Connection, jira_project_allowed

pytestmark = pytest.mark.integration

ACME = "fake-cloud-acme"
LABS = "fake-cloud-labs"
CLIENT_SECRET = "atlassian-client-secret-0001"

Sessions = async_sessionmaker[AsyncSession]


@pytest.fixture
def atlassian() -> FakeAtlassian:
    return FakeAtlassian("http://test")


@pytest.fixture
async def client(
    postgres_url: str, redis_url: str, tmp_path: Path, atlassian: FakeAtlassian, sessions: Sessions
) -> AsyncIterator[AsyncClient]:
    """`sessions` migrates the database first."""
    master_key = tmp_path / "master.key"
    generate_key_file(master_key)
    settings = Settings(
        database_url=postgres_url,
        redis_url=redis_url,
        master_key_file=master_key,
        web_base_url="http://web.test/",
    )
    app = create_app(settings)
    app.state.jira = atlassian
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c


@pytest.fixture
async def workspace(client: AsyncClient) -> str:
    """A workspace of its own for each test, as a path."""
    created = await client.post("/workspaces", json={"name": f"jira-{uuid4().hex[:8]}"})
    assert created.status_code == 201
    return f"/workspaces/{created.json()['id']}"


async def authorize_url(client: AsyncClient, workspace: str, **body: str) -> str:
    response = await client.post(f"{workspace}/connections/jira/authorize", json=body or None)
    assert response.status_code == 200
    return str(response.json()["authorize_url"])


async def follow(client: AsyncClient, url: str, **override: str) -> dict[str, str]:
    """Calls the callback as the browser would and returns the query of the redirect back to
    the web app."""
    target = urlsplit(url)
    params = {k: v[0] for k, v in parse_qs(target.query).items()} | override
    back = await client.get(target.path, params=params)
    assert back.status_code == 303
    location = urlsplit(back.headers["location"])
    assert f"{location.scheme}://{location.netloc}" == "http://web.test"
    return {"path": location.path} | {k: v[0] for k, v in parse_qs(location.query).items()}


async def connect(client: AsyncClient, workspace: str) -> None:
    result = await follow(client, await authorize_url(client, workspace))
    assert result == {"path": "/settings/integrations", "jira": "connected"}


async def test_the_fake_consent_comes_straight_back_with_a_state(
    client: AsyncClient, workspace: str
) -> None:
    url = urlsplit(await authorize_url(client, workspace))
    query = parse_qs(url.query)

    assert (url.netloc, url.path) == ("test", "/jira/callback")
    assert query["code"] == [FAKE_CODE]
    assert len(query["state"][0]) >= 32


async def test_connecting_stores_the_account_and_its_sites(
    client: AsyncClient, workspace: str
) -> None:
    before = (await client.get(f"{workspace}/jira")).json()

    await connect(client, workspace)
    jira = (await client.get(f"{workspace}/jira")).json()
    connections = (await client.get(f"{workspace}/connections")).json()

    assert (before["configured"], before["status"], before["sites"]) == (
        True,
        "not_connected",
        [],
    )
    assert jira["status"] == "connected"
    assert jira["reason"] is None
    assert jira["account"] == FAKE_ACCOUNT.name
    assert jira["scopes"] == list(SCOPES)
    assert jira["missing_scopes"] == []
    assert [(s["cloud_id"], s["name"], s["enabled"], s["projects"]) for s in jira["sites"]] == [
        (ACME, "Acme", True, []),
        (LABS, "Acme Labs", True, []),
    ]
    assert [(c["provider"], c["account_login"], c["key_hint"]) for c in connections] == [
        ("jira", FAKE_ACCOUNT.name, None)
    ]


async def test_the_consent_can_land_on_another_page(client: AsyncClient, workspace: str) -> None:
    url = await authorize_url(client, workspace, return_to="/templates?template=sdd")

    assert await follow(client, url) == {
        "path": "/templates",
        "template": "sdd",
        "jira": "connected",
    }
    refused = await client.post(
        f"{workspace}/connections/jira/authorize", json={"return_to": "//evil.test"}
    )
    assert refused.status_code == 422


async def test_a_state_is_single_use_and_must_be_known(
    client: AsyncClient, workspace: str, atlassian: FakeAtlassian
) -> None:
    url = await authorize_url(client, workspace)
    await follow(client, url)
    await client.delete(f"{workspace}/connections/jira")

    again = await follow(client, url)
    unknown = await follow(client, url, state="not-a-state")
    missing = await client.get("/jira/callback", params={"code": FAKE_CODE})

    assert again["jira"] == unknown["jira"] == "error"
    assert again["reason"] == unknown["reason"] == "state"
    assert parse_qs(urlsplit(missing.headers["location"]).query)["reason"] == ["state"]
    assert (await client.get(f"{workspace}/jira")).json()["status"] == "not_connected"
    assert len(atlassian.issued) == 1
    assert STATE_TTL_S == 600


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"error": "access_denied"}, "denied"),
        ({"code": "not-the-code"}, "exchange"),
        ({"code": ""}, "exchange"),
    ],
)
async def test_a_consent_that_fails_stores_nothing(
    client: AsyncClient, workspace: str, override: dict[str, str], reason: str
) -> None:
    result = await follow(client, await authorize_url(client, workspace), **override)

    assert (result["jira"], result["reason"]) == ("error", reason)
    assert (await client.get(f"{workspace}/jira")).json()["status"] == "not_connected"


async def test_an_account_with_no_jira_site_stores_nothing(
    client: AsyncClient, workspace: str, atlassian: FakeAtlassian
) -> None:
    atlassian.sites_reached = []

    result = await follow(client, await authorize_url(client, workspace))

    assert result["reason"] == "no_sites"
    assert (await client.get(f"{workspace}/jira")).json()["status"] == "not_connected"


async def test_an_unreachable_atlassian_stores_nothing(
    client: AsyncClient, workspace: str, atlassian: FakeAtlassian
) -> None:
    atlassian.unavailable = True

    result = await follow(client, await authorize_url(client, workspace))

    assert result["reason"] == "atlassian"


async def test_a_grant_missing_a_scope_needs_attention(
    client: AsyncClient, workspace: str, atlassian: FakeAtlassian
) -> None:
    atlassian.granted_scopes = tuple(s for s in SCOPES if s != "write:jira-work")

    result = await follow(client, await authorize_url(client, workspace))
    jira = (await client.get(f"{workspace}/jira")).json()

    assert (result["jira"], result["reason"]) == ("error", "scopes")
    assert (jira["status"], jira["reason"]) == ("needs_attention", "scopes")
    assert jira["missing_scopes"] == ["write:jira-work"]
    search = await client.get(f"{workspace}/jira/sites/{ACME}/projects")
    assert search.status_code == 409
    assert search.json()["detail"]["code"] == "needs_attention"

    atlassian.granted_scopes = SCOPES
    await connect(client, workspace)
    assert (await client.get(f"{workspace}/jira")).json()["status"] == "connected"


async def test_projects_are_searched_live_and_picked_per_site(
    client: AsyncClient, workspace: str, sessions: Sessions
) -> None:
    await connect(client, workspace)
    workspace_id = workspace.rsplit("/", 1)[1]
    projects = f"{workspace}/jira/sites/{ACME}/projects"

    everything = (await client.get(projects)).json()
    matching = (await client.get(projects, params={"q": "web"})).json()
    saved = await client.put(projects, json={"project_ids": ["10004", "10001", "10004"]})
    jira = (await client.get(f"{workspace}/jira")).json()

    assert [p["key"] for p in everything["projects"]] == ["DOCS", "OPS", "API", "WEB"]
    assert everything["next_cursor"] is None
    assert matching["projects"] == [{"id": "10004", "key": "WEB", "name": "Web shop"}]
    assert saved.status_code == 200
    assert [p["key"] for p in saved.json()["projects"]] == ["API", "WEB"]
    assert [len(s["projects"]) for s in jira["sites"]] == [2, 0]
    assert await jira_project_allowed(sessions, workspace_id, ACME, "WEB")  # pyright: ignore[reportArgumentType]
    assert not await jira_project_allowed(sessions, workspace_id, ACME, "OPS")  # pyright: ignore[reportArgumentType]
    assert not await jira_project_allowed(sessions, workspace_id, LABS, "WEB")  # pyright: ignore[reportArgumentType]

    cleared = await client.put(projects, json={"project_ids": []})
    assert cleared.json()["projects"] == []


async def test_an_unknown_project_or_site_is_refused(client: AsyncClient, workspace: str) -> None:
    await connect(client, workspace)
    projects = f"{workspace}/jira/sites/{ACME}/projects"
    await client.put(projects, json={"project_ids": ["10004"]})

    foreign = await client.put(projects, json={"project_ids": ["10001", "20001"]})
    malformed = await client.put(projects, json={"project_ids": ["WEB"]})
    other_site = await client.get(f"{workspace}/jira/sites/fake-cloud-nope/projects")
    patched = await client.patch(f"{workspace}/jira/sites/fake-cloud-nope", json={"enabled": False})

    assert foreign.status_code == 422
    assert foreign.json()["detail"]["code"] == "unknown_project"
    assert "20001" in foreign.json()["detail"]["message"]
    assert malformed.status_code == 422
    assert other_site.status_code == patched.status_code == 404
    [acme, _] = (await client.get(f"{workspace}/jira")).json()["sites"]
    assert [p["key"] for p in acme["projects"]] == ["WEB"]


async def test_a_site_switched_off_keeps_its_projects_but_allows_none(
    client: AsyncClient, workspace: str, sessions: Sessions
) -> None:
    await connect(client, workspace)
    workspace_id = workspace.rsplit("/", 1)[1]
    await client.put(f"{workspace}/jira/sites/{ACME}/projects", json={"project_ids": ["10004"]})

    off = await client.patch(f"{workspace}/jira/sites/{ACME}", json={"enabled": False})

    assert off.status_code == 200
    assert (off.json()["enabled"], [p["key"] for p in off.json()["projects"]]) == (False, ["WEB"])
    assert not await jira_project_allowed(sessions, workspace_id, ACME, "WEB")  # pyright: ignore[reportArgumentType]


async def test_an_expired_token_is_refreshed_and_a_refused_refresh_needs_attention(
    client: AsyncClient, workspace: str, atlassian: FakeAtlassian
) -> None:
    atlassian.expires_in_s = 10
    await connect(client, workspace)
    atlassian.expires_in_s = 3600
    projects = f"{workspace}/jira/sites/{ACME}/projects"

    assert (await client.get(projects)).status_code == 200
    assert (await client.get(projects)).status_code == 200
    assert atlassian.refreshes == 1

    atlassian.unauthorized = True
    atlassian.refuse_refresh = True
    refused = await client.get(projects)
    jira = (await client.get(f"{workspace}/jira")).json()
    [connection] = (await client.get(f"{workspace}/connections")).json()

    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "needs_attention"
    assert (jira["status"], jira["reason"]) == ("needs_attention", "invalid_grant")
    assert connection["needs_attention"] == "invalid_grant"

    atlassian.unauthorized = atlassian.refuse_refresh = False
    await client.put(projects, json={"project_ids": []})
    await connect(client, workspace)
    assert (await client.get(projects)).status_code == 200


async def test_an_atlassian_outage_is_a_502_and_marks_nothing(
    client: AsyncClient, workspace: str, atlassian: FakeAtlassian
) -> None:
    await connect(client, workspace)
    atlassian.unavailable = True

    response = await client.get(f"{workspace}/jira/sites/{ACME}/projects")

    assert response.status_code == 502
    assert (await client.get(f"{workspace}/jira")).json()["status"] == "connected"


async def test_disconnecting_removes_everything(client: AsyncClient, workspace: str) -> None:
    await connect(client, workspace)
    await client.put(f"{workspace}/jira/sites/{ACME}/projects", json={"project_ids": ["10004"]})

    deleted = await client.delete(f"{workspace}/connections/jira")
    again = await client.delete(f"{workspace}/connections/jira")
    search = await client.get(f"{workspace}/jira/sites/{ACME}/projects")

    assert (deleted.status_code, again.status_code) == (204, 404)
    assert (await client.get(f"{workspace}/jira")).json()["status"] == "not_connected"
    assert (await client.get(f"{workspace}/connections")).json() == []
    assert search.status_code == 409
    assert search.json()["detail"]["code"] == "no_connection"


async def test_every_step_is_in_the_audit_log(
    client: AsyncClient, workspace: str, atlassian: FakeAtlassian
) -> None:
    await connect(client, workspace)
    projects = f"{workspace}/jira/sites/{ACME}/projects"
    await client.put(projects, json={"project_ids": ["10004", "10001"]})
    await client.patch(f"{workspace}/jira/sites/{LABS}", json={"enabled": False})
    atlassian.unauthorized = True
    await client.get(projects)
    await client.delete(f"{workspace}/connections/jira")

    events = (await client.get(f"{workspace}/audit")).json()["items"]
    by_action = {e["action"]: e["details"] for e in events}

    assert [e["action"] for e in reversed(events)] == [
        "connection.added",
        "jira.projects_changed",
        "jira.site_updated",
        "connection.needs_attention",
        "connection.removed",
    ]
    assert by_action["connection.added"] == {
        "provider": "jira",
        "account_login": FAKE_ACCOUNT.name,
        "sites": 2,
        "replaced": False,
    }
    assert by_action["jira.projects_changed"] == {
        "site": "Acme",
        "cloud_id": ACME,
        "count": 2,
        "keys": ["API", "WEB"],
    }
    assert by_action["connection.needs_attention"] == {"provider": "jira", "reason": "unauthorized"}


async def test_jira_tokens_appear_nowhere(
    client: AsyncClient,
    workspace: str,
    atlassian: FakeAtlassian,
    sessions: Sessions,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The roadmap's "stored encrypted", checked: through connect, a forced refresh, a project
    save and a disconnect, no token is in a response, a redirect, a log line or an audit entry,
    and the database holds only ciphertext."""
    caplog.set_level(logging.DEBUG)
    workspace_id = workspace.rsplit("/", 1)[1]
    projects = f"{workspace}/jira/sites/{ACME}/projects"
    seen: list[str] = []

    async def record(response_text: str, *headers: str) -> None:
        seen.extend([response_text, *headers])

    atlassian.expires_in_s = 10
    url = await authorize_url(client, workspace)
    target = urlsplit(url)
    back = await client.get(
        target.path, params={k: v[0] for k, v in parse_qs(target.query).items()}
    )
    await record(back.text, back.headers["location"])
    atlassian.expires_in_s = 3600
    for response in (
        await client.get(projects),
        await client.put(projects, json={"project_ids": ["10004"]}),
        await client.get(f"{workspace}/jira"),
        await client.get(f"{workspace}/connections"),
        await client.get(f"{workspace}/audit"),
    ):
        assert response.status_code == 200
        await record(response.text, str(dict(response.headers)))

    async with sessions() as session:
        row = await session.scalar(
            select(Connection).where(Connection.workspace_id == workspace_id)  # pyright: ignore[reportArgumentType]
        )
        audit = list(
            await session.scalars(
                select(AuditEvent.details).where(AuditEvent.workspace_id == workspace_id)  # pyright: ignore[reportArgumentType]
            )
        )
    assert row is not None and row.secret_ciphertext is not None and row.key_hint is None
    await client.delete(f"{workspace}/connections/jira")

    assert len(atlassian.issued) == 2, "the first token expired, so the search refreshed it"
    tokens = [
        token.get_secret_value()
        for grant in atlassian.issued
        for token in (grant.access_token, grant.refresh_token)
    ]
    haystack = "\n".join(
        [*seen, caplog.text, repr(audit), repr(row.scopes), str(row.account_login)]
    )
    for token in tokens:
        assert token not in haystack
        assert token.encode() not in row.secret_ciphertext
    assert "fake-jira-" not in haystack


async def test_a_grant_another_master_key_stored_needs_a_reconnect(
    client: AsyncClient, workspace: str, sessions: Sessions
) -> None:
    await connect(client, workspace)
    workspace_id = workspace.rsplit("/", 1)[1]
    async with sessions.begin() as session:
        await session.execute(
            update(Connection)
            .where(Connection.workspace_id == workspace_id)  # pyright: ignore[reportArgumentType]
            .values(secret_ciphertext=b"not-a-ciphertext-at-all-0123456789")
        )

    response = await client.get(f"{workspace}/jira/sites/{ACME}/projects")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "needs_attention"


async def test_without_an_atlassian_app_nothing_connects(
    postgres_url: str, redis_url: str, sessions: Sessions
) -> None:
    settings = Settings(
        database_url=postgres_url, redis_url=redis_url, web_base_url="http://web.test"
    )
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        workspace = (
            f"/workspaces/{(await client.post('/workspaces', json={'name': 'none'})).json()['id']}"
        )
        jira = await client.get(f"{workspace}/jira")
        authorize = await client.post(f"{workspace}/connections/jira/authorize")
        search = await client.get(f"{workspace}/jira/sites/{ACME}/projects")
        back = await client.get("/jira/callback", params={"code": FAKE_CODE, "state": "x"})

    assert jira.json()["configured"] is False
    assert jira.json()["status"] == "not_connected"
    assert authorize.status_code == search.status_code == 503
    assert parse_qs(urlsplit(back.headers["location"]).query) == {
        "jira": ["error"],
        "reason": ["not_configured"],
    }


def test_the_settings_choose_the_atlassian_app(tmp_path: Path) -> None:
    secret = tmp_path / "atlassian.secret"
    secret.write_text(CLIENT_SECRET, encoding="ascii")
    base = {"database_url": "postgresql+asyncpg://x/y", "_env_file": None}

    configured = create_app(
        Settings(atlassian_client_id="client-1", atlassian_client_secret_file=secret, **base)  # pyright: ignore[reportArgumentType]
    )
    fake = create_app(Settings(jira="fake", **base))  # pyright: ignore[reportArgumentType]

    jira: AtlassianApp = configured.state.jira
    url = urlsplit(jira.authorize_url("s"))
    assert url.netloc == "auth.atlassian.com"
    assert parse_qs(url.query)["redirect_uri"] == ["http://localhost:8000/jira/callback"]
    assert isinstance(fake.state.jira, FakeAtlassian)
    with pytest.raises(JiraConfigError):
        create_app(Settings(atlassian_client_id="client-1", **base))  # pyright: ignore[reportArgumentType]
    with pytest.raises(FakeInProductionError):
        create_app(Settings(jira="fake", env="production", **base))  # pyright: ignore[reportArgumentType]
