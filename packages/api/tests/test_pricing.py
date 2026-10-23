from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api import create_app
from agentic_api.settings import Settings
from agentic_runtime import PRICES_AS_OF
from agentic_store import Workspace, workspace_price_table

pytestmark = pytest.mark.integration

PRICE = {"input": 1.5, "output": 7, "cache_write_5m": 2, "cache_write_1h": 3, "cache_read": 0.15}


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
    """A workspace of its own, so overrides never leak between tests."""
    workspace_id = uuid4()
    async with sessions.begin() as session:
        session.add(Workspace(id=workspace_id, name=f"pricing-{workspace_id.hex[:6]}"))
    return workspace_id


def by_model(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {m["model"]: m for m in body["models"]}


async def test_list_prices_are_shown_with_their_date(client: AsyncClient, workspace: UUID) -> None:
    response = await client.get(f"/workspaces/{workspace}/pricing")

    assert response.status_code == 200
    body = response.json()
    assert body["as_of"] == PRICES_AS_OF.isoformat()
    models = by_model(body)
    assert models["claude-opus-5-5"]["default"] == {
        "input": 4,
        "output": 20,
        "cache_write_5m": 5,
        "cache_write_1h": 8,
        "cache_read": 0.2,
    }
    assert models["claude-opus-5-5"]["override"] is None
    haiku = models["claude-haiku-5-5"]["long_context"]
    assert (haiku["above_tokens"], haiku["price"]["input"]) == (100_000, 0.5)


async def test_overrides_replace_list_prices_for_new_runs(
    client: AsyncClient, workspace: UUID, sessions: async_sessionmaker[AsyncSession]
) -> None:
    overrides = [
        {"model": "claude-opus-5-5", "price": PRICE},
        {"model": "acme/proxy-model", "price": PRICE},
    ]

    response = await client.put(f"/workspaces/{workspace}/pricing", json={"overrides": overrides})

    assert response.status_code == 200
    models = by_model(response.json())
    assert models["claude-opus-5-5"]["override"] == PRICE
    assert models["acme/proxy-model"] == {
        "model": "acme/proxy-model",
        "default": None,
        "long_context": None,
        "override": PRICE,
    }
    assert by_model((await client.get(f"/workspaces/{workspace}/pricing")).json()) == models
    table = await workspace_price_table(sessions, workspace)
    assert str(table["claude-opus-5-5"].base.output) == "7.0000"


async def test_an_empty_list_resets_every_model(client: AsyncClient, workspace: UUID) -> None:
    url = f"/workspaces/{workspace}/pricing"
    await client.put(url, json={"overrides": [{"model": "claude-opus-5-5", "price": PRICE}]})

    response = await client.put(url, json={"overrides": []})

    assert all(m["override"] is None for m in response.json()["models"])
    assert "acme/proxy-model" not in by_model(response.json())


@pytest.mark.parametrize(
    ("overrides", "where"),
    [
        ([{"model": "m", "price": {**PRICE, "output": -1}}], "output"),
        ([{"model": "", "price": PRICE}], "model"),
        ([{"model": "has space", "price": PRICE}], "model"),
        ([{"model": "m", "price": {**PRICE, "extra": 1}}], "extra"),
        ([{"model": "m", "price": PRICE}, {"model": "m", "price": PRICE}], "overrides"),
    ],
)
async def test_invalid_overrides_are_refused_on_their_field(
    client: AsyncClient, workspace: UUID, overrides: list[dict[str, Any]], where: str
) -> None:
    response = await client.put(f"/workspaces/{workspace}/pricing", json={"overrides": overrides})

    assert response.status_code == 422
    assert any(where in map(str, e["loc"]) for e in response.json()["detail"])
    models = by_model((await client.get(f"/workspaces/{workspace}/pricing")).json())
    assert all(m["override"] is None for m in models.values())


async def test_a_workspace_sees_only_its_own_overrides(
    client: AsyncClient, workspace: UUID, sessions: async_sessionmaker[AsyncSession]
) -> None:
    other = uuid4()
    async with sessions.begin() as session:
        session.add(Workspace(id=other, name="pricing-other"))
    overrides = [{"model": "claude-opus-5-5", "price": PRICE}]
    await client.put(f"/workspaces/{other}/pricing", json={"overrides": overrides})

    models = by_model((await client.get(f"/workspaces/{workspace}/pricing")).json())

    assert models["claude-opus-5-5"]["override"] is None


async def test_an_unknown_workspace_is_404(client: AsyncClient) -> None:
    missing = f"/workspaces/{uuid4()}/pricing"

    assert (await client.get(missing)).status_code == 404
    assert (await client.put(missing, json={"overrides": []})).status_code == 404
