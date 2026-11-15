import asyncio
import json
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_store import (
    RUN_QUEUE,
    Run,
    StoredRun,
    UnloadableRun,
    claim_run,
    create_run,
    dequeue_run,
    enqueue_run,
    reclaim_expired_run,
    requeue_stale_runs,
)

pytestmark = pytest.mark.integration

SPECS = Path(__file__).resolve().parents[2] / "engine" / "tests" / "fixtures" / "specs" / "valid"
# Each sweep below uses this threshold and moves its own runs two hours back, so runs other
# tests left queued in the shared database (created minutes ago) are never swept here.
STALE_S = 3600


def single_agent() -> WorkflowSpec:
    return parse_spec(json.loads((SPECS / "single-agent.json").read_text(encoding="utf-8")))


@pytest.fixture
async def redis(redis_url: str) -> AsyncIterator[Redis]:
    client = Redis.from_url(redis_url)  # pyright: ignore[reportUnknownMemberType]
    await client.delete(RUN_QUEUE)
    yield client
    await client.delete(RUN_QUEUE)
    await client.aclose()


async def queued_run(sessions: async_sessionmaker[AsyncSession], *, ago_s: float = 0) -> UUID:
    """A new queued run that became queued `ago_s` seconds ago."""
    run_id = await create_run(sessions, single_agent(), "go")
    if ago_s:
        await set_run(sessions, run_id, queued_at=func.now() - timedelta(seconds=ago_s))
    return run_id


async def set_run(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID, **values: object
) -> None:
    async with sessions.begin() as session:
        await session.execute(update(Run).where(Run.id == run_id).values(**values))


async def spoil_spec(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> None:
    """Give the run's stored spec a field this worker does not know, as an older worker sees a
    field a newer API wrote (2026-11-02: `budget_usd`)."""
    async with sessions.begin() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        run.spec = {**run.spec, "unknown_field": 1}


async def queue_contents(redis: Redis) -> list[UUID]:
    items: list[Any] = await redis.lrange(RUN_QUEUE, 0, -1)  # pyright: ignore[reportUnknownMemberType]
    return [UUID(bytes(i).decode()) for i in items]


async def test_queue_is_first_in_first_out(redis: Redis) -> None:
    first, second = uuid4(), uuid4()
    await enqueue_run(redis, first)
    await enqueue_run(redis, second)

    assert await dequeue_run(redis, 1) == first
    assert await dequeue_run(redis, 1) == second
    assert await dequeue_run(redis, 0.1) is None


async def test_a_queued_run_with_no_lease_past_the_threshold_is_announced_again(
    sessions: async_sessionmaker[AsyncSession], redis: Redis
) -> None:
    lost = await queued_run(sessions, ago_s=2 * STALE_S)

    assert await requeue_stale_runs(sessions, redis, STALE_S) == [lost]
    assert await queue_contents(redis) == [lost]
    assert await claim_run(sessions, lost, "w1", 30) is not None


async def test_the_sweep_skips_fresh_leased_and_unqueued_runs(
    sessions: async_sessionmaker[AsyncSession], redis: Redis
) -> None:
    fresh = await queued_run(sessions)
    leased = await queued_run(sessions, ago_s=2 * STALE_S)
    assert await claim_run(sessions, leased, "w1", 300) is not None
    skipped = [fresh, leased]
    for status in ("running", "waiting", "completed", "failed", "cancelled"):
        run_id = await queued_run(sessions, ago_s=2 * STALE_S)
        await set_run(sessions, run_id, status=status)
        skipped.append(run_id)

    swept = await requeue_stale_runs(sessions, redis, STALE_S)

    assert not set(swept) & set(skipped)


async def test_a_swept_run_keeps_its_queued_at_and_waits_the_threshold_again(
    sessions: async_sessionmaker[AsyncSession], redis: Redis
) -> None:
    lost = await queued_run(sessions, ago_s=2 * STALE_S)
    async with sessions() as session:
        queued_at = await session.scalar(select(Run.queued_at).where(Run.id == lost))

    assert await requeue_stale_runs(sessions, redis, STALE_S) == [lost]
    assert await requeue_stale_runs(sessions, redis, STALE_S) == []

    async with sessions() as session:
        run = await session.get(Run, lost)
    assert run is not None
    assert run.queued_at == queued_at
    assert run.enqueued_at is not None
    assert await queue_contents(redis) == [lost]


async def test_workers_sweeping_at_once_announce_each_run_once(
    sessions: async_sessionmaker[AsyncSession], redis: Redis
) -> None:
    lost = {await queued_run(sessions, ago_s=2 * STALE_S) for _ in range(5)}

    sweeps = await asyncio.gather(*(requeue_stale_runs(sessions, redis, STALE_S) for _ in range(4)))

    swept = [run_id for sweep in sweeps for run_id in sweep]
    assert sorted(swept) == sorted(lost)
    assert sorted(await queue_contents(redis)) == sorted(lost)


async def test_a_claim_of_a_spec_this_worker_cannot_load_commits_and_names_the_error(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await queued_run(sessions)
    await spoil_spec(sessions, run_id)

    claimed = await claim_run(sessions, run_id, "w1", 300)

    assert isinstance(claimed, UnloadableRun)
    assert claimed.id == run_id
    assert claimed.attempt == 1
    assert claimed.error == "unknown_field: Extra inputs are not permitted"
    assert claimed.workflow_id == single_agent().id
    assert claimed.workflow_name == single_agent().name
    async with sessions() as session:
        run = await session.get(Run, run_id)
    assert run is not None
    assert run.worker_id == "w1"  # the claim was kept, not rolled back
    assert await claim_run(sessions, run_id, "w2", 300) is None


async def test_a_reclaim_of_a_spec_this_worker_cannot_load_names_the_error(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await queued_run(sessions)
    assert isinstance(await claim_run(sessions, run_id, "w1", 300), StoredRun)
    await spoil_spec(sessions, run_id)
    await set_run(
        sessions,
        run_id,
        status="running",
        lease_expires_at=func.now() - timedelta(days=3650),  # before any other test's runs
    )

    reclaimed = await reclaim_expired_run(sessions, "w2", 300)

    assert isinstance(reclaimed, UnloadableRun)
    assert reclaimed.id == run_id
    assert reclaimed.attempt == 2
