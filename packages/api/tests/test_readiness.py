from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from agentic_api import create_app
from agentic_api.settings import Settings

pytestmark = pytest.mark.integration

# Nothing listens on port 1, so connecting fails fast.
UNREACHABLE_REDIS = "redis://127.0.0.1:1/0"


async def _client(settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


async def test_ready_ok(postgres_url: str, redis_url: str) -> None:
    settings = Settings(database_url=postgres_url, redis_url=redis_url)
    async for client in _client(settings):
        response = await client.get("/health/ready")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "postgres": "ok", "redis": "ok"}


async def test_ready_redis_down(postgres_url: str) -> None:
    settings = Settings(
        database_url=postgres_url, redis_url=UNREACHABLE_REDIS, readiness_timeout_s=1.0
    )
    async for client in _client(settings):
        response = await client.get("/health/ready")

        assert response.status_code == 503
        assert response.json() == {"status": "error", "postgres": "ok", "redis": "error"}
