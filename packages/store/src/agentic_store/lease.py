"""Run leases: which worker is running a run, and until when.

A worker claims a run before running it and renews the lease while it is alive. A `queued` or
`running` run whose lease has expired was abandoned (its worker died or stopped), and any worker
may reclaim it and resume it from its checkpoint. Expiry is judged by the database clock, so
workers' clocks do not matter. Runs from before leases existed (no expiry) are never reclaimed.

A claim commits before the run's spec is parsed: a spec this worker cannot load (one written by a
newer API) comes back as an `UnloadableRun`, for the worker to fail with its reason, instead of
an error that would roll the claim back and stop the worker (12.1).
"""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import Update, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_store.models import Run
from agentic_store.runs import StoredRun, stored_run

# How much of a load error a run's `failure_reason` keeps.
_MAX_LOAD_ERROR = 500


@dataclass(frozen=True)
class UnloadableRun:
    """A claimed run whose stored spec this worker cannot load. `workflow_id` and `workflow_name`
    are read from the raw spec where they are strings, for its `run_started` event."""

    id: UUID
    attempt: int
    error: str
    input: str = ""
    workflow_id: str | None = None
    workflow_name: str | None = None


type ClaimedRun = StoredRun | UnloadableRun

# A `waiting` run (paused at a gate) is not live: no worker holds it and none may reclaim it; a
# decision queues it again (`agentic_store.approvals`).
LIVE_STATUSES = ("queued", "running")


async def claim_run(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID, worker_id: str, ttl_s: float
) -> ClaimedRun | None:
    """Take a newly queued run; `None` if it is not queued or another worker already has it."""
    claim = _claim(worker_id, ttl_s).where(
        Run.id == run_id, Run.status == "queued", Run.lease_expires_at.is_(None)
    )
    return await _claimed(sessions, claim)


async def reclaim_expired_run(
    sessions: async_sessionmaker[AsyncSession], worker_id: str, ttl_s: float
) -> ClaimedRun | None:
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


async def _claimed(sessions: async_sessionmaker[AsyncSession], claim: Update) -> ClaimedRun | None:
    async with sessions.begin() as session:
        run = await session.scalar(claim.returning(Run))
    return None if run is None else load_claimed(run)


def load_claimed(run: Run) -> ClaimedRun:
    """`run` as a `StoredRun`, or an `UnloadableRun` naming why its spec cannot be loaded. Any
    error counts: whatever stops this worker from loading the run must end the run, not the
    worker."""
    try:
        return stored_run(run)
    except Exception as e:
        error = _load_error(e)
        if len(error) > _MAX_LOAD_ERROR:
            error = error[: _MAX_LOAD_ERROR - 1] + "…"
        return UnloadableRun(
            id=run.id,
            attempt=run.attempt,
            error=error,
            input=run.input,
            workflow_id=_text(run.spec.get("id")),
            workflow_name=_text(run.spec.get("name")),
        )


def _load_error(error: Exception) -> str:
    """One line per problem: `root.budget_usd: Extra inputs are not permitted` for a spec that
    does not validate (without pydantic's input values and links), else the error's text."""
    if isinstance(error, ValidationError):
        return "; ".join(
            f"{'.'.join(str(part) for part in e['loc']) or 'spec'}: {e['msg']}"
            for e in error.errors(include_url=False, include_input=False)
        )
    return str(error) or type(error).__name__


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None
