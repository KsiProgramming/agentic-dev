"""Provider selection (8.3): the run's own choice, the workspace's default and settings, the refusal
when Copilot has no connection, what a run records and the filter on it."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from agentic_api import create_app
from agentic_api.settings import Settings
from agentic_github import FakeGithubUserAuth
from agentic_secrets import generate_key_file
from agentic_store import AuditEvent, Run

pytestmark = pytest.mark.integration

Sessions = async_sessionmaker[AsyncSession]
ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def workflow(*agents: dict[str, Any], **extra: Any) -> dict[str, Any]:
    root = {"type": "sequence", "id": "seq", "steps": list(agents)}
    return {"spec_version": "0", "id": "w", "name": "W", "root": root, **extra}


def agent(node_id: str, **extra: Any) -> dict[str, Any]:
    return {"type": "agent", "id": node_id, "role": "R", "instructions": "Go.", **extra}


TWO = workflow(agent("builder"), agent("reviewer"))


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
    created = await client.post("/workspaces", json={"name": f"ps-{uuid4().hex[:8]}"})
    assert created.status_code == 201
    return UUID(created.json()["id"])


async def connect(client: AsyncClient, github_user: FakeGithubUserAuth, workspace: UUID) -> str:
    started = await client.post(f"/workspaces/{workspace}/connections/github-user/authorize")
    url = started.json()["authorize_url"]
    await client.get(url.removeprefix("http://test"))
    listed = (await client.get(f"/workspaces/{workspace}/github-user")).json()["connections"]
    return next(c["id"] for c in listed if c["login"] == github_user.login)


async def set_default(client: AsyncClient, workspace: UUID, provider: str) -> None:
    saved = await client.put(
        f"/workspaces/{workspace}/provider-settings", json={"default_provider": provider}
    )
    assert saved.status_code == 200, saved.text


async def start(client: AsyncClient, workspace: UUID, spec: dict[str, Any], **extra: Any) -> Any:
    return await client.post(
        "/runs",
        json={"workflow": spec, "workspace_id": str(workspace), "trigger": "manual", **extra},
    )


async def detail(client: AsyncClient, response: Any) -> dict[str, Any]:
    assert response.status_code == 202, response.text
    found = await client.get(f"/runs/{response.json()['run_id']}")
    return found.json()


async def test_a_run_with_nothing_set_is_on_claude(client: AsyncClient) -> None:
    workspace = await new_workspace(client)

    run = await detail(client, await start(client, workspace, TWO))

    assert (run["provider"], run["providers"]) == ("claude", ["claude"])


async def test_the_workspace_default_applies_and_needs_a_connection(
    client: AsyncClient, github_user: FakeGithubUserAuth
) -> None:
    workspace = await new_workspace(client)
    await set_default(client, workspace, "copilot")

    refused = await start(client, workspace, TWO)

    assert refused.status_code == 422
    message = refused.json()["detail"]
    assert message.startswith("copilot_connection_required")
    assert "'builder'" in message
    assert "'reviewer'" in message
    connection = await connect(client, github_user, workspace)

    run = await detail(
        client, await start(client, workspace, TWO, copilot_connection_id=connection)
    )

    assert (run["provider"], run["providers"]) == ("copilot", ["copilot"])
    assert run["copilot_login"] == "ada"


async def test_the_run_override_beats_the_workspace_default(
    client: AsyncClient, github_user: FakeGithubUserAuth
) -> None:
    workspace = await new_workspace(client)
    await set_default(client, workspace, "copilot")
    connection = await connect(client, github_user, workspace)

    on_claude = await detail(
        client,
        await start(client, workspace, TWO, provider="claude", copilot_connection_id=connection),
    )
    no_connection_needed = await detail(
        client, await start(client, workspace, TWO, provider="claude")
    )

    assert on_claude["providers"] == ["claude"]
    assert no_connection_needed["providers"] == ["claude"]


async def test_the_run_override_never_moves_a_node_that_names_its_own_provider(
    client: AsyncClient, github_user: FakeGithubUserAuth
) -> None:
    workspace = await new_workspace(client)
    pinned = workflow(agent("builder"), agent("reviewer", provider="copilot"))

    refused = await start(client, workspace, pinned, provider="claude")
    connection = await connect(client, github_user, workspace)
    run = await detail(
        client,
        await start(client, workspace, pinned, provider="claude", copilot_connection_id=connection),
    )

    assert refused.status_code == 422
    assert "'reviewer'" in refused.json()["detail"]
    assert "'builder'" not in refused.json()["detail"]
    assert (run["provider"], run["providers"]) == ("claude", ["claude", "copilot"])


async def test_the_workflows_provider_beats_the_workspace_default(client: AsyncClient) -> None:
    workspace = await new_workspace(client)
    await set_default(client, workspace, "copilot")

    run = await detail(
        client, await start(client, workspace, workflow(agent("a"), provider="claude"))
    )

    assert run["providers"] == ["claude"]


async def test_a_connection_alone_still_means_copilot(
    client: AsyncClient, github_user: FakeGithubUserAuth
) -> None:
    workspace = await new_workspace(client)
    connection = await connect(client, github_user, workspace)

    run = await detail(
        client, await start(client, workspace, TWO, copilot_connection_id=connection)
    )

    assert (run["provider"], run["providers"]) == ("copilot", ["copilot"])


async def test_a_rerun_goes_on_with_the_providers_it_had(
    client: AsyncClient, github_user: FakeGithubUserAuth, sessions: Sessions
) -> None:
    workspace = await new_workspace(client)
    connection = await connect(client, github_user, workspace)
    first = await start(client, workspace, TWO, copilot_connection_id=connection)
    run_id = first.json()["run_id"]
    async with sessions.begin() as session:
        (await session.get_one(Run, UUID(run_id))).status = "failed"
    await set_default(client, workspace, "claude")

    rerun = await client.post(f"/runs/{run_id}/rerun")

    assert rerun.status_code == 202, rerun.text
    again = (await client.get(f"/runs/{rerun.json()['run_id']}")).json()
    assert again["providers"] == ["copilot"]  # the person's choice goes on


async def test_a_rerun_whose_connection_is_gone_is_refused_naming_the_agents(
    client: AsyncClient, github_user: FakeGithubUserAuth, sessions: Sessions
) -> None:
    workspace = await new_workspace(client)
    connection = await connect(client, github_user, workspace)
    run_id = (await start(client, workspace, TWO, copilot_connection_id=connection)).json()[
        "run_id"
    ]
    async with sessions.begin() as session:
        (await session.get_one(Run, UUID(run_id))).status = "failed"
    await client.delete(f"/workspaces/{workspace}/github-user/{connection}")

    rerun = await client.post(f"/runs/{run_id}/rerun")

    assert rerun.status_code == 422
    assert rerun.json()["detail"].startswith("copilot_connection_required")


async def test_the_list_filters_by_provider_and_counts_follow(
    client: AsyncClient, github_user: FakeGithubUserAuth
) -> None:
    workspace = await new_workspace(client)
    connection = await connect(client, github_user, workspace)
    mixed = workflow(agent("a"), agent("b", provider="copilot"))
    claude_run = (await start(client, workspace, TWO)).json()["run_id"]
    mixed_run = (
        await start(client, workspace, mixed, copilot_connection_id=connection, provider="claude")
    ).json()["run_id"]
    copilot_run = (await start(client, workspace, TWO, copilot_connection_id=connection)).json()[
        "run_id"
    ]

    async def ids(provider: str | None) -> set[str]:
        params: dict[str, str] = {"workspace_id": str(workspace)}
        if provider is not None:
            params["provider"] = provider
        found = (await client.get("/runs", params=params)).json()["items"]
        return {r["id"] for r in found}

    assert await ids("copilot") == {mixed_run, copilot_run}  # a run matches when it used it
    assert await ids("claude") == {claude_run, mixed_run}
    assert await ids(None) == {claude_run, mixed_run, copilot_run}
    counts = (
        await client.get(
            "/runs/counts", params={"workspace_id": str(workspace), "provider": "copilot"}
        )
    ).json()
    assert counts["all"] == 2
    bad = await client.get("/runs", params={"workspace_id": str(workspace), "provider": "gemini"})
    assert bad.status_code == 422


async def test_the_settings_default_to_claude_and_the_list_price(client: AsyncClient) -> None:
    workspace = await new_workspace(client)

    settings = (await client.get(f"/workspaces/{workspace}/provider-settings")).json()

    assert settings == {
        "default_provider": "claude",
        "copilot_model": None,
        "copilot_credit_usd": 0.01,
        "default_copilot_credit_usd": 0.01,
    }


async def test_the_settings_round_trip_and_are_audited(
    client: AsyncClient, sessions: Sessions
) -> None:
    workspace = await new_workspace(client)
    body = {"default_provider": "copilot", "copilot_model": "gpt-5", "copilot_credit_usd": 0.02}

    saved = await client.put(f"/workspaces/{workspace}/provider-settings", json=body)

    assert saved.status_code == 200, saved.text
    assert saved.json() == {**body, "default_copilot_credit_usd": 0.01}
    assert (await client.get(f"/workspaces/{workspace}/provider-settings")).json() == saved.json()
    async with sessions() as session:
        entries = list(
            await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.workspace_id == workspace,
                    AuditEvent.action == "workspace.settings_changed",
                )
            )
        )
    assert [e.details["changed"] for e in entries] == [
        ["default_provider", "copilot_model", "copilot_credit_usd"]
    ]
    audit = (await client.get(f"/workspaces/{workspace}/audit")).json()["items"]
    assert "workspace.settings_changed" in [e["action"] for e in audit]
    reset = await client.put(f"/workspaces/{workspace}/provider-settings", json={})
    assert reset.json()["default_provider"] == "claude"
    assert reset.json()["copilot_credit_usd"] == 0.01


@pytest.mark.parametrize(
    "body",
    [
        {"default_provider": "gemini"},
        {"copilot_credit_usd": 0},
        {"copilot_credit_usd": -1},
        {"copilot_model": "not a model!"},
        {"surprise": 1},
    ],
)
async def test_bad_settings_are_refused(client: AsyncClient, body: dict[str, Any]) -> None:
    workspace = await new_workspace(client)

    response = await client.put(f"/workspaces/{workspace}/provider-settings", json=body)

    assert response.status_code == 422


async def test_the_settings_of_an_unknown_workspace_are_404(client: AsyncClient) -> None:
    assert (await client.get(f"/workspaces/{uuid4()}/provider-settings")).status_code == 404
    put = await client.put(f"/workspaces/{uuid4()}/provider-settings", json={})
    assert put.status_code == 404


async def test_validation_names_the_agents_that_need_a_connection(
    client: AsyncClient, github_user: FakeGithubUserAuth
) -> None:
    workspace = await new_workspace(client)
    await set_default(client, workspace, "copilot")
    document = workflow(agent("a"), agent("b", provider="claude"), id="w")

    async def issues() -> list[tuple[str, str | None]]:
        checked = await client.post(
            "/workflows/w/validate", json={"workflow": document, "workspace_id": str(workspace)}
        )
        assert checked.status_code == 200, checked.text
        return [(i["code"], i["node_id"]) for i in checked.json()["issues"]]

    assert await issues() == [("copilot_connection_required", "a")]
    await connect(client, github_user, workspace)
    assert await issues() == []


async def test_a_budget_on_a_copilot_run_needs_no_claude_price_for_its_model(
    client: AsyncClient, github_user: FakeGithubUserAuth
) -> None:
    workspace = await new_workspace(client)
    connection = await connect(client, github_user, workspace)
    spec = workflow(agent("a", provider="copilot", model="gpt-5"))

    run = await start(client, workspace, spec, copilot_connection_id=connection, budget_usd=1)

    assert run.status_code == 202, run.text
    on_claude = await start(client, workspace, workflow(agent("a", model="gpt-5")), budget_usd=1)
    assert on_claude.status_code == 422  # Claude has no price for it: the budget cannot hold


async def test_the_migration_backfills_the_provider_of_runs_that_used_copilot(
    postgres_url: str,
) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")
    await asyncio.to_thread(command.downgrade, config, "0039_github_user_connections")
    engine = create_async_engine(postgres_url)
    insert = (
        "INSERT INTO runs (id, workspace_id, status, spec, policy, copilot_login) VALUES "
        "(gen_random_uuid(), '00000000-0000-0000-0000-000000000001', 'completed', '{}', '{}', "
        ":login) "
        "RETURNING id"
    )
    async with engine.begin() as conn:
        on_copilot = (await conn.execute(text(insert), {"login": "ada"})).scalar_one()
        on_claude = (await conn.execute(text(insert), {"login": None})).scalar_one()

    await asyncio.to_thread(command.upgrade, config, "head")

    async with engine.connect() as conn:
        rows = {
            row.id: (row.provider, row.providers, row.provider_map)
            for row in await conn.execute(
                text("SELECT id, provider, providers, provider_map FROM runs WHERE id = ANY(:ids)"),
                {"ids": [on_copilot, on_claude]},
            )
        }
    await engine.dispose()
    assert rows[on_copilot] == ("copilot", ["copilot"], None)
    assert rows[on_claude] == ("claude", ["claude"], None)
