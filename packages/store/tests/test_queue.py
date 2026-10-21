from uuid import uuid4

import pytest
from redis.asyncio import Redis

from agentic_store import dequeue_run, enqueue_run

pytestmark = pytest.mark.integration


async def test_queue_is_first_in_first_out(redis_url: str) -> None:
    redis = Redis.from_url(redis_url)  # pyright: ignore[reportUnknownMemberType]
    first, second = uuid4(), uuid4()
    try:
        await enqueue_run(redis, first)
        await enqueue_run(redis, second)

        assert await dequeue_run(redis, 1) == first
        assert await dequeue_run(redis, 1) == second
        assert await dequeue_run(redis, 0.1) is None
    finally:
        await redis.aclose()
