"""`GET /workspaces/{id}/audit`: the workspace's audit log, newest first (3.7)."""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api import create_app
from agentic_api.settings import Settings
from agentic_store import Workspace

pytestmark = pytest.mark.integration

SPEC = (
    Path(__file__).resolve().parents[2]
    / "engine"
    / "tests"
    / "fixtures"
    / "specs"
    / "valid"
    / "two-step-sequence.json"
)


@pytest.fixture
async def client(
    postgres_url: str, redis_url: str, sessions: async_sessionmaker[AsyncSession]
) -> AsyncIterator[AsyncClient]:
    """`sessions` migrates the database first."""
    app = create_app(Settings(database_url=postgres_url, redis_url=redis_url))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


@pytest.fixture
async def workspace(sessions: async_sessionmaker[AsyncSession]) -> UUID:
    """A workspace of its own, so its log holds only this test's entries."""
    workspace_id = uuid4()
    async with sessions.begin() as session:
        session.add(Workspace(id=workspace_id, name=f"audit-{workspace_id.hex[:6]}"))
    return workspace_id


async def start_run(client: AsyncClient, workspace: UUID) -> str:
    workflow = json.loads(SPEC.read_text(encoding="utf-8"))
    response = await client.post(
        "/runs", json={"workflow": workflow, "input": "go", "workspace_id": str(workspace)}
    )
    assert response.status_code == 202, response.text
    run_id: str = response.json()["run_id"]
    return run_id


async def test_the_log_lists_runs_and_settings_changes_newest_first(
    client: AsyncClient, workspace: UUID
) -> None:
    run_id = await start_run(client, workspace)
    assert (await client.post(f"/runs/{run_id}/cancel")).status_code == 202
    put = await client.put(f"/workspaces/{workspace}/policy", json={"agents_alive": 4})
    assert put.status_code == 200

    response = await client.get(f"/workspaces/{workspace}/audit")

    assert response.status_code == 200
    page = response.json()
    assert page["next_cursor"] is None
    assert [(i["action"], i["run_id"]) for i in page["items"]] == [
        ("policy.updated", None),
        ("run.cancel_requested", run_id),
        ("run.created", run_id),
    ]
    created = page["items"][2]
    assert created["actor"] == {"type": "user", "id": None}
    assert created["run"] == {"template_id": None, "repo_url": None, "status": "queued"}
    assert created["details"] == {"template_id": None, "repo_url": None, "budget_usd": None}
    assert page["items"][0]["details"]["after"]["agents_alive"] == 4


async def test_the_log_pages_and_filters(client: AsyncClient, workspace: UUID) -> None:
    first = await start_run(client, workspace)
    second = await start_run(client, workspace)
    await client.post(f"/runs/{first}/cancel")

    one = await client.get(f"/workspaces/{workspace}/audit", params={"limit": 2})
    assert one.status_code == 200
    rest = await client.get(
        f"/workspaces/{workspace}/audit", params={"cursor": one.json()["next_cursor"]}
    )
    listed = [i["run_id"] for i in one.json()["items"] + rest.json()["items"]]
    assert listed == [first, second, first]
    assert rest.json()["next_cursor"] is None

    by_action = await client.get(
        f"/workspaces/{workspace}/audit",
        params=[("action", "run.created"), ("action", "gate.approved")],
    )
    assert [i["run_id"] for i in by_action.json()["items"]] == [second, first]
    by_run = await client.get(f"/workspaces/{workspace}/audit", params={"run_id": second})
    assert [i["action"] for i in by_run.json()["items"]] == ["run.created"]


async def test_another_workspace_never_sees_the_log(client: AsyncClient, workspace: UUID) -> None:
    await start_run(client, workspace)
    other = uuid4()
    unknown = await client.get(f"/workspaces/{other}/audit")
    assert unknown.status_code == 404


@pytest.mark.parametrize(
    "params",
    [{"cursor": "nope"}, {"limit": 0}, {"limit": 201}, {"action": "run.deleted"}],
)
async def test_bad_filters_are_refused(
    client: AsyncClient, workspace: UUID, params: dict[str, str | int]
) -> None:
    response = await client.get(f"/workspaces/{workspace}/audit", params=params)

    assert response.status_code == 422
