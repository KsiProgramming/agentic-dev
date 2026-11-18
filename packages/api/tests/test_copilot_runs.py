"""Runs on a person's Copilot (8.2): `POST /runs` with `copilot_connection_id`, what is recorded,
what is refused, and that a rerun keeps it."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api import create_app
from agentic_api.settings import Settings
from agentic_github import FakeGithubUserAuth
from agentic_secrets import generate_key_file
from agentic_store import AuditEvent, Run, mark_github_user_needs_attention

pytestmark = pytest.mark.integration

Sessions = async_sessionmaker[AsyncSession]

SPEC: dict[str, Any] = {
    "spec_version": "0",
    "id": "one-agent",
    "name": "One agent",
    "root": {"type": "agent", "id": "main", "role": "R", "instructions": "Go."},
}


@pytest.fixture
def github_user() -> FakeGithubUserAuth:
    return FakeGithubUserAuth("http://test")


@pytest.fixture
async def client(
    postgres_url: str,
    redis_url: str,
    tmp_path: Path,
    github_user: FakeGithubUserAuth,
    sessions: Sessions,
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
    app.state.github_user = github_user
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c


async def new_workspace(client: AsyncClient) -> UUID:
    created = await client.post("/workspaces", json={"name": f"cp-{uuid4().hex[:8]}"})
    assert created.status_code == 201
    return UUID(created.json()["id"])


async def connect(client: AsyncClient, github_user: FakeGithubUserAuth, workspace: UUID) -> str:
    """Connects `github_user.login` in `workspace`; the connection's id."""
    started = await client.post(f"/workspaces/{workspace}/connections/github-user/authorize")
    url = started.json()["authorize_url"]
    callback = await client.get(url.removeprefix("http://test"))
    assert "github_user=connected" in callback.headers["location"]
    listed = (await client.get(f"/workspaces/{workspace}/github-user")).json()["connections"]
    return next(c["id"] for c in listed if c["login"] == github_user.login)


async def start(client: AsyncClient, workspace: UUID, **extra: Any) -> Any:
    return await client.post(
        "/runs",
        json={"workflow": SPEC, "workspace_id": str(workspace), "trigger": "manual", **extra},
    )


async def the_run(sessions: Sessions, run_id: str) -> Run:
    async with sessions() as session:
        run = await session.scalar(select(Run).where(Run.id == UUID(run_id)))
    assert run is not None
    return run


async def test_a_run_started_with_a_connection_records_whose_copilot_it_uses(
    client: AsyncClient, github_user: FakeGithubUserAuth, sessions: Sessions
) -> None:
    workspace = await new_workspace(client)
    connection = await connect(client, github_user, workspace)

    response = await start(client, workspace, copilot_connection_id=connection)

    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    run = await the_run(sessions, run_id)
    assert (str(run.copilot_connection_id), run.copilot_login) == (connection, "ada")
    detail = (await client.get(f"/runs/{run_id}")).json()
    assert detail["copilot_login"] == "ada"
    listed = (await client.get("/runs", params={"workspace_id": str(workspace)})).json()["items"]
    assert [r["copilot_login"] for r in listed] == ["ada"]
    async with sessions() as session:
        created = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.run_id == UUID(run_id), AuditEvent.action == "run.created"
            )
        )
    assert created is not None
    assert created.details["copilot_login"] == "ada"


async def test_a_run_without_a_connection_is_on_claude(
    client: AsyncClient, sessions: Sessions
) -> None:
    workspace = await new_workspace(client)

    response = await start(client, workspace)

    run = await the_run(sessions, response.json()["run_id"])
    assert (run.copilot_connection_id, run.copilot_login) == (None, None)
    assert (await client.get(f"/runs/{run.id}")).json()["copilot_login"] is None


async def test_another_workspaces_or_an_unknown_connection_is_refused(
    client: AsyncClient, github_user: FakeGithubUserAuth
) -> None:
    mine = await new_workspace(client)
    theirs = await new_workspace(client)
    theirs_connection = await connect(client, github_user, theirs)

    other = await start(client, mine, copilot_connection_id=theirs_connection)
    unknown = await start(client, mine, copilot_connection_id=str(uuid4()))

    for refused in (other, unknown):
        assert refused.status_code == 422
        assert "copilot_connection_not_found" in refused.json()["detail"]


async def test_a_connection_that_needs_attention_is_refused_and_says_to_connect_again(
    client: AsyncClient, github_user: FakeGithubUserAuth, sessions: Sessions
) -> None:
    workspace = await new_workspace(client)
    connection = await connect(client, github_user, workspace)
    await mark_github_user_needs_attention(sessions, workspace, UUID(connection), "invalid_grant")

    response = await start(client, workspace, copilot_connection_id=connection)

    assert response.status_code == 409
    assert "copilot_needs_attention" in response.json()["detail"]
    assert "ada" in response.json()["detail"]


async def test_removing_the_connection_keeps_the_login_the_run_recorded(
    client: AsyncClient, github_user: FakeGithubUserAuth, sessions: Sessions
) -> None:
    workspace = await new_workspace(client)
    connection = await connect(client, github_user, workspace)
    run_id = (await start(client, workspace, copilot_connection_id=connection)).json()["run_id"]

    removed = await client.delete(f"/workspaces/{workspace}/github-user/{connection}")

    assert removed.status_code == 204
    run = await the_run(sessions, run_id)
    assert (run.copilot_connection_id, run.copilot_login) == (None, "ada")


async def test_a_rerun_keeps_the_connection(
    client: AsyncClient, github_user: FakeGithubUserAuth, sessions: Sessions
) -> None:
    workspace = await new_workspace(client)
    connection = await connect(client, github_user, workspace)
    run_id = (await start(client, workspace, copilot_connection_id=connection)).json()["run_id"]
    async with sessions.begin() as session:
        run = await session.get_one(Run, UUID(run_id))
        run.status = "failed"

    rerun = await client.post(f"/runs/{run_id}/rerun")

    assert rerun.status_code == 202, rerun.text
    again = await the_run(sessions, rerun.json()["run_id"])
    assert (str(again.copilot_connection_id), again.copilot_login) == (connection, "ada")
