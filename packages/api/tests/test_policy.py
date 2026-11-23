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
    "approval_ttl_s": 259_200,
    "budget_usd": None,
    "sandbox_ttl_s": 86_400,
    "branch_retention_days": 30,
    "review_rounds": 3,
}
UNSET = {**dict.fromkeys(DEFAULTS), "breakers": None}
BREAKER_DEFAULTS = {
    "repeat_calls": 5,
    "repeat_errors": 3,
    "cost_multiple": 3.0,
    "cost_floor_usd": 0.5,
    "flip_flops": 2,
}
BREAKER_UNSET = dict.fromkeys(BREAKER_DEFAULTS)
CEILINGS = {**DEFAULTS, "sandbox_ttl_s": 259_200, "branch_retention_days": 90, "review_rounds": 10}


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
    body = response.json()
    assert {k: v for k, v in body.items() if k != "breakers"} == {
        "defaults": DEFAULTS,
        "ceilings": CEILINGS,
        "overrides": UNSET,
        "effective": DEFAULTS,
    }
    assert body["breakers"]["defaults"] == BREAKER_DEFAULTS
    assert body["breakers"]["effective"] == BREAKER_DEFAULTS
    assert body["breakers"]["overrides"] == BREAKER_UNSET
    assert body["breakers"]["ranges"]["repeat_calls"] == {"min": 2, "max": 50}
    assert body["breakers"]["ranges"]["cost_floor_usd"] == {"min": 0, "max": 1000}


async def test_the_retention_limits_may_go_above_their_default(
    client: AsyncClient, workspace: UUID
) -> None:
    """12.3: a kept sandbox's time to live and the saved commits' retention (and 7.6, the review
    rounds) may be raised, up to their ceiling; the other limits only go down."""
    raised = {"sandbox_ttl_s": 259_200, "branch_retention_days": 90, "review_rounds": 10}
    put = await client.put(f"/workspaces/{workspace}/policy", json=raised)

    assert put.status_code == 200, put.text
    assert put.json()["effective"] == {**DEFAULTS, **raised}


async def test_lowered_limits_round_trip_and_reset(client: AsyncClient, workspace: UUID) -> None:
    lowered = {"loop_iterations": 2, "wall_time_s": 600, "approval_ttl_s": 3600}
    put = await client.put(f"/workspaces/{workspace}/policy", json=lowered)
    got = await client.get(f"/workspaces/{workspace}/policy")
    reset = await client.put(f"/workspaces/{workspace}/policy", json={})

    assert put.status_code == 200
    assert put.json() == got.json()
    assert got.json()["overrides"] == {**UNSET, **lowered}
    assert got.json()["effective"] == {**DEFAULTS, **lowered}
    assert reset.json()["overrides"] == UNSET
    assert reset.json()["effective"] == DEFAULTS


@pytest.mark.parametrize(
    "body",
    [
        {"agents_spawned": 41},
        {"wall_time_s": 7201},
        {"approval_ttl_s": 259_201},
        {"sandbox_ttl_s": 259_201},
        {"sandbox_ttl_s": 0},
        {"branch_retention_days": 91},
        {"review_rounds": 11},
        {"review_rounds": 0},
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


async def test_breaker_thresholds_round_trip_reset_and_stay_in_their_range(
    client: AsyncClient, workspace: UUID
) -> None:
    """13.7: a workspace tunes the circuit breakers within the platform's ranges."""
    tuned = {"repeat_calls": 10, "cost_multiple": 5.5}
    put = await client.put(f"/workspaces/{workspace}/policy", json={"breakers": tuned})
    got = await client.get(f"/workspaces/{workspace}/policy")
    reset = await client.put(f"/workspaces/{workspace}/policy", json={})

    assert put.status_code == 200, put.text
    assert put.json() == got.json()
    breakers = got.json()["breakers"]
    assert breakers["overrides"] == {**BREAKER_UNSET, **tuned}
    assert breakers["effective"] == {**BREAKER_DEFAULTS, **tuned}
    assert reset.json()["breakers"]["effective"] == BREAKER_DEFAULTS
    assert reset.json()["breakers"]["overrides"] == BREAKER_UNSET


@pytest.mark.parametrize(
    "breakers",
    [
        {"repeat_calls": 1},
        {"repeat_errors": 51},
        {"cost_multiple": 1.4},
        {"cost_multiple": 21},
        {"cost_floor_usd": -1},
        {"flip_flops": 0},
        {"flip_flops": 11},
        {"off": True},
    ],
)
async def test_breaker_thresholds_outside_their_range_are_refused(
    client: AsyncClient, workspace: UUID, breakers: dict[str, float]
) -> None:
    response = await client.put(f"/workspaces/{workspace}/policy", json={"breakers": breakers})

    assert response.status_code == 422
    got = await client.get(f"/workspaces/{workspace}/policy")
    assert got.json()["overrides"]["breakers"] is None


async def test_a_run_keeps_the_breaker_thresholds_it_was_created_with(
    sessions: async_sessionmaker[AsyncSession], client: AsyncClient, workspace: UUID
) -> None:
    """The workspace's thresholds, then the workflow's own over them, are frozen on the run."""
    from agentic_engine.spec import parse_spec
    from agentic_store import create_run, get_run

    await client.put(
        f"/workspaces/{workspace}/policy", json={"breakers": {"repeat_calls": 10, "flip_flops": 4}}
    )
    workflow = parse_spec(
        {
            "spec_version": "0",
            "id": "w",
            "name": "W",
            "breakers": {"flip_flops": 6},
            "root": {"type": "agent", "id": "a", "role": "R", "instructions": "Go."},
        }
    )
    run_id = await create_run(sessions, workflow, "go", workspace_id=workspace)
    await client.put(f"/workspaces/{workspace}/policy", json={"breakers": {"repeat_calls": 20}})

    run = await get_run(sessions, run_id)
    assert run is not None
    assert (run.policy.breakers.repeat_calls, run.policy.breakers.flip_flops) == (10, 6)
