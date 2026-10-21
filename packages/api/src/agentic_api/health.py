import asyncio
from collections.abc import Coroutine
from typing import Any, Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from agentic_api.settings import Settings

router = APIRouter(tags=["health"])

ComponentStatus = Literal["ok", "error"]


class Health(BaseModel):
    status: Literal["ok"] = "ok"


class Readiness(BaseModel):
    status: ComponentStatus
    postgres: ComponentStatus
    redis: ComponentStatus


@router.get("/health", operation_id="getHealth")
async def health() -> Health:
    """Liveness: the process is up. Checks no dependencies."""
    return Health()


@router.get(
    "/health/ready",
    operation_id="getReadiness",
    responses={503: {"model": Readiness, "description": "A dependency is unavailable"}},
)
async def ready(request: Request, response: Response) -> Readiness:
    """Readiness: Postgres and Redis both answer."""
    settings: Settings = request.app.state.settings
    db: AsyncEngine = request.app.state.db
    redis: Redis = request.app.state.redis

    pg_status, redis_status = await asyncio.gather(
        _check(_ping_postgres(db), settings.readiness_timeout_s),
        _check(_ping_redis(redis), settings.readiness_timeout_s),
    )
    healthy = pg_status == "ok" and redis_status == "ok"
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return Readiness(status="ok" if healthy else "error", postgres=pg_status, redis=redis_status)


async def _ping_postgres(db: AsyncEngine) -> None:
    async with db.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _ping_redis(redis: Redis) -> None:
    await redis.ping()  # pyright: ignore[reportUnknownMemberType]


async def _check(probe: Coroutine[Any, Any, None], timeout_s: float) -> ComponentStatus:
    try:
        async with asyncio.timeout(timeout_s):
            await probe
    except Exception:
        return "error"
    return "ok"
