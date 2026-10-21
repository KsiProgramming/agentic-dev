"""The run queue: a Redis list of run ids. The API pushes, workers pop.

Only the id travels; the spec and input are read from Postgres. Popping removes the job, so a
run whose worker dies before finishing is not retried (durable execution comes later).
"""

from typing import Any
from uuid import UUID

from redis.asyncio import Redis

RUN_QUEUE = "runs:queue"


async def enqueue_run(redis: Redis, run_id: UUID) -> None:
    await redis.lpush(RUN_QUEUE, str(run_id))  # pyright: ignore[reportUnknownMemberType]


async def dequeue_run(redis: Redis, timeout_s: float) -> UUID | None:
    """The oldest queued run id, waiting up to `timeout_s`; `None` if the queue stayed empty."""
    item: Any = await redis.brpop([RUN_QUEUE], timeout=timeout_s)  # pyright: ignore[reportUnknownMemberType]
    return None if item is None else UUID(bytes(item[1]).decode())
