from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api import create_app
from agentic_api.settings import Settings
from agentic_github import FAKE_CODE_PREFIX, FakeGithubUserAuth, GithubConfigError
from agentic_secrets import generate_key_file
from agentic_store import AuditEvent, GithubUserConnection

pytestmark = pytest.mark.integration

Sessions = async_sessionmaker[AsyncSession]


@pytest.fixture
def github_user() -> FakeGithubUserAuth:
    return FakeGithubUserAuth("http://test")


async def make_client(
    postgres_url: str, redis_url: str, tmp_path: Path, auth: FakeGithubUserAuth | None
) -> AsyncIterator[AsyncClient]:
    master_key = tmp_path / "master.key"
    generate_key_file(master_key)
    settings = Settings(
        database_url=postgres_url,
        redis_url=redis_url,
        master_key_file=master_key,
        web_base_url="http://web.test/",
    )
    app = create_app(settings)
    app.state.github_user = auth
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c


@pytest.fixture
async def client(
    postgres_url: str,
    redis_url: str,
    tmp_path: Path,
    github_user: FakeGithubUserAuth,
    sessions: Sessions,
) -> AsyncIterator[AsyncClient]:
    """`sessions` migrates the database first."""
    async for c in make_client(postgres_url, redis_url, tmp_path, github_user):
        yield c


@pytest.fixture
async def unconfigured(
    postgres_url: str, redis_url: str, tmp_path: Path, sessions: Sessions
) -> AsyncIterator[AsyncClient]:
    async for c in make_client(postgres_url, redis_url, tmp_path, None):
        yield c


@pytest.fixture
async def workspace(client: AsyncClient) -> str:
    created = await client.post("/workspaces", json={"name": f"gh-user-{uuid4().hex[:8]}"})
    assert created.status_code == 201
    return f"/workspaces/{created.json()['id']}"


async def authorize_url(client: AsyncClient, workspace: str, **body: str) -> str:
    response = await client.post(
        f"{workspace}/connections/github-user/authorize", json=body or None
    )
    assert response.status_code == 200
    return str(response.json()["authorize_url"])


async def follow(client: AsyncClient, url: str, **override: str) -> dict[str, str]:
    """Calls the callback as the browser would and returns the query of the redirect back."""
    target = urlsplit(url)
    params = {k: v[0] for k, v in parse_qs(target.query).items()} | override
    back = await client.get(target.path, params=params)
    assert back.status_code == 303
    location = urlsplit(back.headers["location"])
    assert f"{location.scheme}://{location.netloc}" == "http://web.test"
    return {"path": location.path} | {k: v[0] for k, v in parse_qs(location.query).items()}


async def connect(client: AsyncClient, workspace: str) -> None:
    result = await follow(client, await authorize_url(client, workspace))
    assert result == {"path": "/settings/integrations", "github_user": "connected"}


async def test_the_fake_consent_comes_straight_back_with_a_state(
    client: AsyncClient, workspace: str
) -> None:
    url = urlsplit(await authorize_url(client, workspace))
    query = parse_qs(url.query)

    assert (url.netloc, url.path) == ("test", "/github-user/callback")
    assert query["code"] == [f"{FAKE_CODE_PREFIX}ada"]
    assert len(query["state"][0]) >= 32


async def test_connecting_lists_the_person_and_never_a_token(
    client: AsyncClient, workspace: str, github_user: FakeGithubUserAuth
) -> None:
    before = (await client.get(f"{workspace}/github-user")).json()
    assert before == {"configured": True, "connections": []}

    await connect(client, workspace)

    listed = (await client.get(f"{workspace}/github-user")).json()
    (only,) = listed["connections"]
    assert (only["login"], only["status"], only["reason"]) == ("ada", "connected", None)
    token = github_user.issued[0].access_token.get_secret_value()
    assert token not in str((await client.get(f"{workspace}/github-user")).text)


async def test_each_person_connects_apart_and_the_same_person_replaces_their_own(
    client: AsyncClient, workspace: str, github_user: FakeGithubUserAuth
) -> None:
    await connect(client, workspace)
    github_user.login = "grace"
    await connect(client, workspace)
    github_user.login = "ada"
    await connect(client, workspace)

    logins = [
        c["login"] for c in (await client.get(f"{workspace}/github-user")).json()["connections"]
    ]

    assert logins == ["ada", "grace"]


async def test_the_state_is_single_use_and_an_unknown_one_is_refused(
    client: AsyncClient, workspace: str
) -> None:
    url = await authorize_url(client, workspace)

    assert (await follow(client, url))["github_user"] == "connected"
    again = await follow(client, url)
    unknown = await follow(client, url, state="never-issued")

    assert (again["github_user"], again["reason"]) == ("error", "state")
    assert (unknown["github_user"], unknown["reason"]) == ("error", "state")
    assert len((await client.get(f"{workspace}/github-user")).json()["connections"]) == 1


async def test_a_refusal_a_missing_code_and_a_bad_code_come_back_as_reasons(
    client: AsyncClient, workspace: str
) -> None:
    denied = await follow(client, await authorize_url(client, workspace), error="access_denied")
    no_code = await follow(client, await authorize_url(client, workspace), code="")
    bad_code = await follow(client, await authorize_url(client, workspace), code="nope")

    assert denied["reason"] == "denied"
    assert no_code["reason"] == "exchange"
    assert bad_code["reason"] == "exchange"
    assert (await client.get(f"{workspace}/github-user")).json()["connections"] == []


async def test_github_being_down_comes_back_as_a_reason(
    client: AsyncClient, workspace: str, github_user: FakeGithubUserAuth
) -> None:
    url = await authorize_url(client, workspace)
    github_user.unavailable = True

    assert (await follow(client, url))["reason"] == "github"


async def test_return_to_is_a_path_of_the_web_app_only(client: AsyncClient, workspace: str) -> None:
    url = await authorize_url(client, workspace, return_to="/runs/new?provider=copilot")
    result = await follow(client, url)

    assert result["path"] == "/runs/new"
    assert result["provider"] == "copilot"
    assert result["github_user"] == "connected"
    refused = await client.post(
        f"{workspace}/connections/github-user/authorize", json={"return_to": "//evil.test"}
    )
    assert refused.status_code == 422


async def test_an_unknown_workspace_is_a_404(client: AsyncClient) -> None:
    missing = f"/workspaces/{uuid4()}"

    assert (await client.get(f"{missing}/github-user")).status_code == 404
    assert (await client.post(f"{missing}/connections/github-user/authorize")).status_code == 404
    assert (await client.delete(f"{missing}/github-user/{uuid4()}")).status_code == 404


async def test_without_an_oauth_app_or_a_key_nothing_can_connect(
    unconfigured: AsyncClient,
) -> None:
    created = await unconfigured.post("/workspaces", json={"name": f"none-{uuid4().hex[:8]}"})
    workspace = f"/workspaces/{created.json()['id']}"

    listed = await unconfigured.get(f"{workspace}/github-user")
    started = await unconfigured.post(f"{workspace}/connections/github-user/authorize")
    callback = await unconfigured.get("/github-user/callback", params={"code": "x", "state": "y"})

    assert listed.json() == {"configured": False, "connections": []}
    assert started.status_code == 503
    assert "reason=not_configured" in callback.headers["location"]


async def test_removing_a_connection_deletes_it_and_only_in_its_own_workspace(
    client: AsyncClient, workspace: str
) -> None:
    await connect(client, workspace)
    other = await client.post("/workspaces", json={"name": f"other-{uuid4().hex[:8]}"})
    other_ws = f"/workspaces/{other.json()['id']}"
    (mine,) = (await client.get(f"{workspace}/github-user")).json()["connections"]

    wrong_workspace = await client.delete(f"{other_ws}/github-user/{mine['id']}")
    removed = await client.delete(f"{workspace}/github-user/{mine['id']}")
    again = await client.delete(f"{workspace}/github-user/{mine['id']}")

    assert (wrong_workspace.status_code, removed.status_code, again.status_code) == (404, 204, 404)
    assert (await client.get(f"{workspace}/github-user")).json()["connections"] == []


async def test_the_grant_is_encrypted_at_rest_and_audited_without_it(
    client: AsyncClient,
    workspace: str,
    github_user: FakeGithubUserAuth,
    sessions: Sessions,
) -> None:
    await connect(client, workspace)
    token = github_user.issued[0].access_token.get_secret_value()
    workspace_id = workspace.rsplit("/", 1)[1]

    async with sessions() as session:
        (row,) = (
            await session.scalars(
                select(GithubUserConnection).where(
                    GithubUserConnection.workspace_id == UUID(workspace_id)
                )
            )
        ).all()
        audit = list(
            await session.scalars(
                select(AuditEvent).where(AuditEvent.workspace_id == UUID(workspace_id))
            )
        )

    assert token.encode() not in row.secret_ciphertext
    added = [a for a in audit if a.action == "connection.added"]
    assert [a.details for a in added] == [
        {"provider": "github_user", "account_login": "ada", "replaced": False}
    ]
    assert token not in repr([a.details for a in audit])


def test_a_client_id_without_a_secret_file_fails_at_startup(tmp_path: Path) -> None:
    master_key = tmp_path / "master.key"
    generate_key_file(master_key)

    with pytest.raises(GithubConfigError, match="GITHUB_USER_CLIENT_SECRET_FILE"):
        create_app(
            Settings(master_key_file=master_key, github_user_client_id="Iv1.abc")  # pyright: ignore[reportCallIssue]
        )
