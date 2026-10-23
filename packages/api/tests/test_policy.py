"""`GET`/`PUT /workspaces/{id}/policy`: a workspace lowers the platform's run limits (3.2) and
sets a default budget (3.3)."""

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api import create_app
from agentic_api.settings import Settings
from agentic_store import Workspace

pytestmark = pytest.mark.integration

DEFAULTS = {
    "agents_alive": 8,
    "agents_spawned": 40,
    "max_depth": 2,
    "loop_iterations": 5,
    "wall_time_s": 7200,
    "budget_usd": None,
}
UNSET = dict.fromkeys(DEFAULTS)


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
    """A workspace of its own, so limits never leak between tests."""
    workspace_id = uuid4()
    async with sessions.begin() as session:
        session.add(Workspace(id=workspace_id, name=f"policy-{workspace_id.hex[:6]}"))
    return workspace_id


async def test_a_new_workspace_has_the_platform_limits(
    client: AsyncClient, workspace: UUID
) -> None:
    response = await client.get(f"/workspaces/{workspace}/policy")

    assert response.status_code == 200
    assert response.json() == {"defaults": DEFAULTS, "overrides": UNSET, "effective": DEFAULTS}


async def test_lowered_limits_round_trip_and_reset(client: AsyncClient, workspace: UUID) -> None:
    put = await client.put(
        f"/workspaces/{workspace}/policy", json={"loop_iterations": 2, "wall_time_s": 600}
    )
    got = await client.get(f"/workspaces/{workspace}/policy")
    reset = await client.put(f"/workspaces/{workspace}/policy", json={})

    assert put.status_code == 200
    assert put.json() == got.json()
    assert got.json()["overrides"] == {**UNSET, "loop_iterations": 2, "wall_time_s": 600}
    assert got.json()["effective"] == {**DEFAULTS, "loop_iterations": 2, "wall_time_s": 600}
    assert reset.json()["overrides"] == UNSET
    assert reset.json()["effective"] == DEFAULTS


@pytest.mark.parametrize(
    "body",
    [
        {"agents_spawned": 41},
        {"wall_time_s": 7201},
        {"loop_iterations": 0},
        {"max_depth": -1},
        {"budget_usd": 0},
        {"budget_usd": -1},
        {"budget_usd": 0.001},
        {"budget_usd": 1_000_001},
        {"budget": 5},
    ],
)
async def test_limits_outside_the_platform_range_are_refused(
    client: AsyncClient, workspace: UUID, body: dict[str, float]
) -> None:
    response = await client.put(f"/workspaces/{workspace}/policy", json=body)

    assert response.status_code == 422
    got = await client.get(f"/workspaces/{workspace}/policy")
    assert got.json()["overrides"] == UNSET


async def test_a_default_budget_round_trips_and_resets(
    client: AsyncClient, workspace: UUID
) -> None:
    put = await client.put(f"/workspaces/{workspace}/policy", json={"budget_usd": 2.5})
    reset = await client.put(f"/workspaces/{workspace}/policy", json={})

    assert put.status_code == 200, put.text
    # A budget has no platform ceiling: it is a default, not a lowered limit.
    assert put.json()["defaults"] == DEFAULTS
    assert put.json()["overrides"] == {**UNSET, "budget_usd": 2.5}
    assert put.json()["effective"] == {**DEFAULTS, "budget_usd": 2.5}
    assert reset.json()["effective"]["budget_usd"] is None


async def test_an_unknown_workspace_is_not_found(client: AsyncClient) -> None:
    missing = uuid4()

    assert (await client.get(f"/workspaces/{missing}/policy")).status_code == 404
    assert (await client.put(f"/workspaces/{missing}/policy", json={})).status_code == 404
