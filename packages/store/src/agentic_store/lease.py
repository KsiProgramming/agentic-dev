"""Run leases: which worker is running a run, and until when.

A worker claims a run before running it and renews the lease while it is alive. A `queued` or
`running` run whose lease has expired was abandoned (its worker died or stopped), and any worker
may reclaim it and resume it from its checkpoint. Expiry is judged by the database clock, so
workers' clocks do not matter. Runs from before leases existed (no expiry) are never reclaimed.
"""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import Update, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_store.models import Run
from agentic_store.runs import StoredRun, stored_run

# A `waiting` run (paused at a gate) is not live: no worker holds it and none may reclaim it; a
# decision queues it again (`agentic_store.approvals`).
LIVE_STATUSES = ("queued", "running")


async def claim_run(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID, worker_id: str, ttl_s: float
) -> StoredRun | None:
    """Take a newly queued run; `None` if it is not queued or another worker already has it."""
    claim = _claim(worker_id, ttl_s).where(
        Run.id == run_id, Run.status == "queued", Run.lease_expires_at.is_(None)
    )
    return await _claimed(sessions, claim)


async def reclaim_expired_run(
    sessions: async_sessionmaker[AsyncSession], worker_id: str, ttl_s: float
) -> StoredRun | None:
    """Take the abandoned run whose lease expired first, if any. Workers reclaiming at the same
    time get different runs (`SKIP LOCKED`)."""
    expired = (
        select(Run.id)
        .where(Run.status.in_(LIVE_STATUSES), Run.lease_expires_at < func.now())
        .order_by(Run.lease_expires_at)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    return await _claimed(sessions, _claim(worker_id, ttl_s).where(Run.id == expired))


async def renew_lease(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID, worker_id: str, ttl_s: float
) -> bool:
    """Extend `worker_id`'s lease on the run; `False` if it no longer holds it."""
    async with sessions.begin() as session:
        renewed = await session.scalar(
            update(Run)
            .where(Run.id == run_id, Run.worker_id == worker_id)
            .values(lease_expires_at=func.now() + timedelta(seconds=ttl_s))
            .returning(Run.id)
        )
    return renewed is not None


async def release_run(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID, worker_id: str
) -> None:
    """Give the run up. If it has not ended, its lease is expired now, so the next worker that
    looks reclaims it straight away (a drain); an ended run is never reclaimed."""
    async with sessions.begin() as session:
        await session.execute(
            update(Run)
            .where(Run.id == run_id, Run.worker_id == worker_id)
            .values(worker_id=None, lease_expires_at=func.now())
        )


async def leased_run_ids(sessions: async_sessionmaker[AsyncSession]) -> set[UUID]:
    """Runs some worker holds a live lease on, i.e. that are in flight right now."""
    async with sessions() as session:
        rows = await session.scalars(
            select(Run.id).where(Run.status.in_(LIVE_STATUSES), Run.lease_expires_at > func.now())
        )
        return set(rows)


async def waiting_run_ids(sessions: async_sessionmaker[AsyncSession]) -> set[UUID]:
    """Runs paused at a gate: no worker holds them, but their sandboxes are kept for them."""
    async with sessions() as session:
        return set(await session.scalars(select(Run.id).where(Run.status == "waiting")))


def _claim(worker_id: str, ttl_s: float) -> Update:
    return update(Run).values(
        worker_id=worker_id,
        lease_expires_at=func.now() + timedelta(seconds=ttl_s),
        attempt=Run.attempt + 1,
    )


async def _claimed(sessions: async_sessionmaker[AsyncSession], claim: Update) -> StoredRun | None:
    async with sessions.begin() as session:
        run = await session.scalar(claim.returning(Run))
        return None if run is None else stored_run(run)
