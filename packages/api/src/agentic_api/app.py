from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine

from agentic_api.health import router as health_router
from agentic_api.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        db = create_async_engine(settings.database_url, pool_pre_ping=True)
        redis = Redis.from_url(  # pyright: ignore[reportUnknownMemberType]
            settings.redis_url,
            socket_connect_timeout=settings.readiness_timeout_s,
            socket_timeout=settings.readiness_timeout_s,
        )
        app.state.db = db
        app.state.redis = redis
        try:
            yield
        finally:
            await redis.aclose()
            await db.dispose()

    app = FastAPI(title="Agentic Dev Platform API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.include_router(health_router)
    return app
