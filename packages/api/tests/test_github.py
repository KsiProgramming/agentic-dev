from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import SplitResult, parse_qs, urlsplit

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api import create_app
from agentic_api.settings import Settings
from agentic_github import (
    GithubApiError,
    InstallationInfo,
    InstallationNotFoundError,
    RepoInfo,
)
from agentic_github.testing import private_key_pem
from agentic_store import DEFAULT_WORKSPACE_ID

pytestmark = pytest.mark.integration

WORKSPACE = f"/workspaces/{DEFAULT_WORKSPACE_ID}"
INSTALL = f"{WORKSPACE}/connections/github/install"
REPOS = f"{WORKSPACE}/repos"
TOKEN = "ghs_installationtoken0002"


def repo(full_name: str, *, private: bool = False) -> RepoInfo:
    owner, name = full_name.split("/")
    return RepoInfo(
        id=hash(full_name) % 10_000,
        full_name=full_name,
        name=name,
        owner=owner,
        private=private,
        default_branch="main",
        html_url=f"https://github.com/{full_name}",
    )


class FakeGithub:
    """Stands in for `GithubApp`: a set of known installations and their repos."""

    def __init__(self) -> None:
        self.installations = {42: "acme"}
        self.repos = {42: [repo("acme/web"), repo("Acme/api", private=True)]}
        self.error: Exception | None = None
        self.closed = False

    def install_url(self, state: str) -> str:
        return f"https://github.com/apps/agentic-dev/installations/new?state={state}"

    async def get_installation(self, installation_id: int) -> InstallationInfo:
        if self.error:
            raise self.error
        if installation_id not in self.installations:
            raise InstallationNotFoundError(installation_id)
        return InstallationInfo(installation_id, self.installations[installation_id], "User")

    async def list_repos(self, installation_id: int) -> list[RepoInfo]:
        if self.error:
            raise self.error
        if installation_id not in self.installations:
            raise InstallationNotFoundError(installation_id)
        return self.repos[installation_id]

    def close(self) -> None:
        self.closed = True


def install_url(response: Response) -> SplitResult:
    assert response.status_code == 200
    return urlsplit(str(response.json()["install_url"]))


def state_of(response: Response) -> str:
    [state] = parse_qs(install_url(response).query)["state"]
    return state


@pytest.fixture
def github() -> FakeGithub:
    return FakeGithub()


@pytest.fixture
async def migrated(postgres_url: str, sessions: async_sessionmaker[AsyncSession]) -> str:
    """`postgres_url`, migrated to head."""
    return postgres_url


@pytest.fixture
async def client(migrated: str, redis_url: str, github: FakeGithub) -> AsyncIterator[AsyncClient]:
    settings = Settings(database_url=migrated, redis_url=redis_url, web_base_url="http://web.test/")
    app = create_app(settings)
    app.state.github = github
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c
        # Leave the default workspace with no connection for the next test.
        await c.delete(f"{WORKSPACE}/connections/github")
    assert github.closed


async def install(client: AsyncClient, installation_id: int = 42, **extra: str) -> dict[str, str]:
    """Runs the install flow and returns the query of the redirect back to the web app."""
    state = state_of(await client.post(INSTALL))
    params: dict[str, str] = {
        "installation_id": str(installation_id),
        "setup_action": "install",
        "state": state,
    }
    back = await client.get("/github/setup", params=params | extra)
    assert back.status_code == 303
    location = urlsplit(back.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == "http://web.test/settings"
    return {k: v[0] for k, v in parse_qs(location.query).items()}


async def test_the_install_url_names_the_app_and_carries_a_state(client: AsyncClient) -> None:
    url = install_url(await client.post(INSTALL))
    assert (url.netloc, url.path) == ("github.com", "/apps/agentic-dev/installations/new")
    assert len(parse_qs(url.query)["state"][0]) >= 32


async def test_installing_links_the_workspace_and_lists_its_repos(client: AsyncClient) -> None:
    assert await install(client) == {"github": "connected"}

    connections = (await client.get(f"{WORKSPACE}/connections")).json()
    repos = await client.get(REPOS)

    assert [(c["provider"], c["account_login"]) for c in connections] == [("github", "acme")]
    assert repos.status_code == 200
    assert [(r["full_name"], r["private"]) for r in repos.json()] == [
        ("Acme/api", True),
        ("acme/web", False),
    ]
    assert set(repos.json()[0]) == {
        "id",
        "full_name",
        "name",
        "owner",
        "private",
        "default_branch",
        "html_url",
    }


async def test_a_state_is_single_use(client: AsyncClient) -> None:
    state = state_of(await client.post(INSTALL))
    params: dict[str, str] = {"installation_id": "42", "setup_action": "install", "state": state}

    first = await client.get("/github/setup", params=params)
    replay = await client.get("/github/setup", params=params)

    assert first.headers["location"].endswith("github=connected")
    assert replay.headers["location"].endswith("github=error&reason=state")


@pytest.mark.parametrize(
    ("params", "reason"),
    [
        ({"installation_id": "42", "setup_action": "install", "state": "forged"}, "state"),
        ({"installation_id": "42", "setup_action": "install"}, "state"),
    ],
)
async def test_a_setup_without_a_valid_state_links_nothing(
    client: AsyncClient, params: dict[str, str], reason: str
) -> None:
    back = await client.get("/github/setup", params=params)

    assert back.status_code == 303
    assert back.headers["location"] == f"http://web.test/settings?github=error&reason={reason}"
    assert (await client.get(f"{WORKSPACE}/connections")).json() == []


async def test_an_installation_of_another_app_is_refused(client: AsyncClient) -> None:
    assert await install(client, installation_id=99) == {
        "github": "error",
        "reason": "installation",
    }
    assert (await client.get(f"{WORKSPACE}/connections")).json() == []


async def test_a_requested_install_is_pending(client: AsyncClient) -> None:
    assert await install(client, setup_action="request") == {
        "github": "error",
        "reason": "pending",
    }


async def test_a_github_failure_during_setup_is_reported(
    client: AsyncClient, github: FakeGithub
) -> None:
    github.error = GithubApiError("GitHub returned 500")

    assert await install(client) == {"github": "error", "reason": "github"}


async def test_repos_without_a_connection_is_a_conflict(client: AsyncClient) -> None:
    response = await client.get(REPOS)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "no_connection"


async def test_repos_of_a_removed_installation_is_gone(
    client: AsyncClient, github: FakeGithub
) -> None:
    await install(client)
    del github.installations[42]

    response = await client.get(REPOS)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "installation_gone"


async def test_a_github_error_is_a_bad_gateway_without_a_token(
    client: AsyncClient, github: FakeGithub
) -> None:
    await install(client)
    github.error = GithubApiError("GitHub returned 500")

    response = await client.get(REPOS)

    assert response.status_code == 502
    assert response.json() == {"detail": "GitHub returned 500"}
    assert TOKEN not in response.text


async def test_an_unknown_workspace_is_404(client: AsyncClient) -> None:
    missing = "/workspaces/00000000-0000-0000-0000-00000000dead"

    assert (await client.post(f"{missing}/connections/github/install")).status_code == 404
    assert (await client.get(f"{missing}/repos")).status_code == 404
    assert (await client.delete(f"{missing}/connections/github")).status_code == 404


async def test_disconnect_unlinks_the_installation(client: AsyncClient) -> None:
    await install(client)

    assert (await client.delete(f"{WORKSPACE}/connections/github")).status_code == 204
    assert (await client.delete(f"{WORKSPACE}/connections/github")).status_code == 404
    assert (await client.get(REPOS)).json()["detail"]["code"] == "no_connection"


async def test_without_the_app_github_is_unavailable_and_the_rest_works(
    migrated: str, redis_url: str
) -> None:
    app = create_app(Settings(database_url=migrated, redis_url=redis_url))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        install_url = await client.post(INSTALL)
        repos = await client.get(REPOS)
        setup = await client.get("/github/setup", params={"installation_id": "42"})
        workspaces = await client.get("/workspaces")

    assert install_url.status_code == repos.status_code == 503
    assert "GITHUB_APP_ID" in repos.json()["detail"]
    assert setup.headers["location"].endswith("github=error&reason=not_configured")
    assert workspaces.status_code == 200


def test_the_app_is_built_from_settings_with_its_key_file(
    postgres_url: str, redis_url: str, tmp_path: Path
) -> None:
    pem = tmp_path / "app.pem"
    pem.write_text(private_key_pem(), encoding="ascii")

    app = create_app(
        Settings(
            database_url=postgres_url,
            redis_url=redis_url,
            github_app_id=1234,
            github_app_slug="agentic-dev",
            github_app_private_key_file=pem,
        )
    )

    assert app.state.github.config.slug == "agentic-dev"
    app.state.github.close()


def test_a_configured_app_without_its_key_fails_at_startup(
    postgres_url: str, redis_url: str, tmp_path: Path
) -> None:
    settings = Settings(
        database_url=postgres_url,
        redis_url=redis_url,
        github_app_id=1234,
        github_app_slug="agentic-dev",
        github_app_private_key_file=tmp_path / "missing.pem",
    )

    with pytest.raises(RuntimeError, match="private key"):
        create_app(settings)
