"""The run queue: a Redis list of run ids. The API pushes, workers pop.

Only the id travels; the spec and input are read from Postgres. Popping removes the job: the
queue only announces runs. Who runs a run is decided by its lease in Postgres
(`agentic_store.lease`), and a run whose worker died comes back by reclaiming it there.

Postgres is the queue's source of truth (12.1). A run `queued` with no lease was announced but
never claimed, or its id was lost (a worker killed between popping it and claiming it), so every
worker sweeps (`requeue_stale_runs`): a run left like that past a threshold is announced again.
Announcing an id twice is harmless, since only one claim of it succeeds.
"""

from datetime import timedelta
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_store.models import Run

RUN_QUEUE = "runs:queue"


async def enqueue_run(redis: Redis, run_id: UUID) -> None:
    await redis.lpush(RUN_QUEUE, str(run_id))  # pyright: ignore[reportUnknownMemberType]


async def dequeue_run(redis: Redis, timeout_s: float) -> UUID | None:
    """The oldest queued run id, waiting up to `timeout_s`; `None` if the queue stayed empty."""
    item: Any = await redis.brpop([RUN_QUEUE], timeout=timeout_s)  # pyright: ignore[reportUnknownMemberType]
    return None if item is None else UUID(bytes(item[1]).decode())


async def requeue_stale_runs(
    sessions: async_sessionmaker[AsyncSession], redis: Redis, stale_s: float
) -> list[UUID]:
    """Announce again every run `queued` with no lease that neither became queued nor was
    announced by a sweep in the last `stale_s` seconds, and return their ids.

    The rows are locked (`SKIP LOCKED`) and stamped `enqueued_at` before their ids are pushed,
    so workers sweeping at once push each id once, and the next sweep waits `stale_s` again.
    `queued_at` is left alone: it says since when the run has waited. If the push fails after
    the commit, the next sweep past `stale_s` pushes the ids again."""
    cutoff = func.now() - timedelta(seconds=stale_s)
    async with sessions.begin() as session:
        stale = (
            select(Run.id)
            .where(
                Run.status == "queued",
                Run.lease_expires_at.is_(None),
                # GREATEST skips NULLs: a run never swept counts from `queued_at`.
                func.greatest(Run.queued_at, Run.enqueued_at) < cutoff,
            )
            .with_for_update(skip_locked=True)
        )
        ids = list(
            await session.scalars(
                update(Run)
                .where(Run.id.in_(stale))
                .values(enqueued_at=func.now())
                .returning(Run.id)
            )
        )
    for run_id in ids:
        await enqueue_run(redis, run_id)
    return ids
