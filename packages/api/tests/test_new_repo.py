"""Runs on a repo they create (phase 1.12): `new_repo` on `POST /runs`, the options endpoint, and
rerun."""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api import create_app
from agentic_api.settings import Settings
from agentic_github import GithubApiError, InstallationInfo, InstallationNotFoundError, RepoInfo
from agentic_store import (
    DEFAULT_WORKSPACE_ID,
    RUN_QUEUE,
    delete_connection,
    get_run,
    put_github_connection,
)

pytestmark = pytest.mark.integration

WORKSPACE = f"/workspaces/{DEFAULT_WORKSPACE_ID}"
OPTIONS = f"{WORKSPACE}/repos/new-repo-options"
ORG_INSTALLATION, USER_INSTALLATION = 42, 43
DOCS: dict[str, Any] = {"id": "generate-docs", "parameters": {}}


class FakeGithub:
    """Stands in for `GithubApp`: an installation on the `acme` organisation, one on the personal
    account `ada`, and the repos that exist."""

    def __init__(self) -> None:
        self.accounts = {
            ORG_INSTALLATION: ("acme", "Organization"),
            USER_INSTALLATION: ("ada", "User"),
        }
        self.existing = {"acme/taken"}
        self.error: Exception | None = None
        self.looked_up: list[str] = []

    async def get_installation(self, installation_id: int) -> InstallationInfo:
        if self.error:
            raise self.error
        if installation_id not in self.accounts:
            raise InstallationNotFoundError(installation_id)
        login, kind = self.accounts[installation_id]
        return InstallationInfo(installation_id, login, kind)

    async def get_repo(self, installation_id: int, full_name: str) -> RepoInfo | None:
        self.looked_up.append(full_name)
        if full_name not in self.existing:
            return None
        owner, name = full_name.split("/")
        return RepoInfo(1, full_name, name, owner, True, "main", f"https://github.com/{full_name}")

    def close(self) -> None:
        pass


@pytest.fixture
def github() -> FakeGithub:
    return FakeGithub()


@pytest.fixture
async def client(
    postgres_url: str,
    redis_url: str,
    sessions: async_sessionmaker[AsyncSession],
    github: FakeGithub,
) -> AsyncIterator[AsyncClient]:
    app = create_app(Settings(database_url=postgres_url, redis_url=redis_url))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        app.state.github = github
        yield c
    await delete_connection(sessions, DEFAULT_WORKSPACE_ID, "github")
    # Off the queue again: no later test's worker may try to clone from GitHub.
    redis = Redis.from_url(redis_url)  # pyright: ignore[reportUnknownMemberType]
    try:
        await redis.delete(RUN_QUEUE)  # pyright: ignore[reportUnknownMemberType]
    finally:
        await redis.aclose()


async def connect(sessions: async_sessionmaker[AsyncSession], installation: int) -> None:
    await put_github_connection(sessions, DEFAULT_WORKSPACE_ID, installation, "x")


async def test_a_run_on_a_new_repo_starts_with_the_gate_and_the_create_step(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await connect(sessions, ORG_INSTALLATION)

    response = await client.post(
        "/runs",
        json={"template": DOCS, "new_repo": {"name": "docs-new", "gitignore": "Python"}},
    )

    assert response.status_code == 202, response.text
    run = await get_run(sessions, UUID(response.json()["run_id"]))
    assert run is not None
    assert run.repo is not None and run.repo.url == "https://github.com/acme/docs-new"
    steps: list[Any] = run.spec.model_dump(mode="json")["root"]["steps"]
    assert [s["id"] for s in steps[:3]] == ["approve_repo", "create_repo", "list_modules"]
    assert steps[0]["title"] == "Create the repo acme/docs-new?"
    assert steps[1]["args"] == {"name": "docs-new", "private": True, "gitignore": "Python"}


async def test_a_taken_name_is_refused_before_any_approval(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await connect(sessions, ORG_INSTALLATION)

    response = await client.post("/runs", json={"template": DOCS, "new_repo": {"name": "taken"}})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "repo_exists"
    assert "acme/taken already exists" in response.json()["detail"]["message"]


@pytest.mark.parametrize(
    ("installation", "code"),
    [(None, "no_connection"), (USER_INSTALLATION, "personal_account"), (99, "installation_gone")],
)
async def test_a_workspace_that_cannot_create_a_repo_is_refused(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    installation: int | None,
    code: str,
) -> None:
    if installation is not None:
        await connect(sessions, installation)

    response = await client.post("/runs", json={"template": DOCS, "new_repo": {"name": "x"}})
    options = await client.get(OPTIONS)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == code
    assert options.status_code == 200
    assert options.json()["can_create"] is False
    assert options.json()["reason"] == code


@pytest.mark.parametrize(
    "body",
    [
        {"template": DOCS, "new_repo": {"name": "x"}, "repo": {"url": "https://github.com/a/b"}},
        {"template": DOCS, "new_repo": {"name": "a/b"}},
        {"template": DOCS, "new_repo": {"name": ".."}},
        {"template": DOCS, "new_repo": {"name": "x", "license": "gpl-3.0"}},
        {"template": DOCS, "new_repo": {"name": "x", "owner": "evil"}},
    ],
)
async def test_bad_new_repo_requests_are_refused(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], body: dict[str, Any]
) -> None:
    await connect(sessions, ORG_INSTALLATION)

    response = await client.post("/runs", json=body)

    assert response.status_code == 422, response.text


async def test_a_github_error_is_a_bad_gateway(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], github: FakeGithub
) -> None:
    await connect(sessions, ORG_INSTALLATION)
    github.error = GithubApiError("GitHub returned 500")

    response = await client.post("/runs", json={"template": DOCS, "new_repo": {"name": "x"}})

    assert response.status_code == 502


async def test_the_options_name_the_organisation_and_the_templates(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await connect(sessions, ORG_INSTALLATION)

    response = await client.get(OPTIONS)

    assert response.status_code == 200
    assert response.json() == {
        "owner": "acme",
        "can_create": True,
        "reason": None,
        "message": None,
        "gitignore_templates": ["Python", "Node", "Go", "Rust", "Java", "VisualStudio"],
        "licenses": ["mit", "apache-2.0"],
    }


async def test_the_options_of_an_unknown_workspace_are_404(client: AsyncClient) -> None:
    response = await client.get(
        "/workspaces/00000000-0000-0000-0000-00000000dead/repos/new-repo-options"
    )

    assert response.status_code == 404


async def test_a_run_that_created_its_repo_is_not_rerun(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await connect(sessions, ORG_INSTALLATION)
    created = await client.post("/runs", json={"template": DOCS, "new_repo": {"name": "once"}})
    run_id = created.json()["run_id"]

    response = await client.post(f"/runs/{run_id}/rerun")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "repo_exists"
    assert "https://github.com/acme/once" in response.json()["detail"]["message"]
