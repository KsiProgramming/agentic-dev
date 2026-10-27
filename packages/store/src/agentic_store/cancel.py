"""Cancelling a run: recording that a user asked, and reading it back.

Only workers write a run's events, so the API never ends a run itself: it sets
`cancel_requested_at` and the worker ends the run `cancelled`. A running run's worker sees the
request within `cancel_poll_s`; a queued run is ended by the worker that claims it. A run paused
at a gate has no worker, so it is queued again (like a decision) and the API enqueues it. A gate
that expires is cancelled the same way, by the worker's sweep (`agentic_store.expiry`); the run
keeps the first reason it was cancelled for (`cancel_reason`).
"""

from typing import Final
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.events import RUN_END_STATUS
from agentic_store.approvals import RunNotFoundError
from agentic_store.audit import audit
from agentic_store.models import Run

USER_CANCEL_REASON: Final = "cancelled by user"
"""The `reason` of the `run_cancelled` event of a run a user cancelled."""

ENDED_STATUSES: Final = frozenset(RUN_END_STATUS.values())


class RunEndedError(Exception):
    """The run has already ended; there is nothing to cancel."""


async def request_cancel(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> str:
    """Record that the run should be cancelled and return its status before. A run waiting at a
    gate is queued again, for the caller to enqueue. Asking again is harmless. Raises
    `RunNotFoundError`, or `RunEndedError` if the run has already ended."""
    async with sessions.begin() as session:
        # Locks the run, so a cancel and a gate decision are recorded one after the other.
        run = await session.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if run is None:
            raise RunNotFoundError(f"run {run_id} not found")
        # Read before the update, which also refreshes `run`.
        before = run.status
        first_request = run.cancel_requested_at is None
        workspace_id = run.workspace_id
        if before in ENDED_STATUSES:
            raise RunEndedError(f"run {run_id} has already ended ({before})")
        values: dict[str, object] = {
            "cancel_requested_at": func.coalesce(Run.cancel_requested_at, func.now()),
            "cancel_reason": func.coalesce(Run.cancel_reason, USER_CANCEL_REASON),
        }
        if before == "waiting":
            values |= {
                "status": "queued",
                "worker_id": None,
                "lease_expires_at": None,
                "attempt": 0,
            }
        await session.execute(update(Run).where(Run.id == run_id).values(values))
        if first_request:
            audit(
                session,
                workspace_id,
                "run.cancel_requested",
                run_id=run_id,
                details={"status": before},
            )
        return before


async def cancel_requested(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> bool:
    """Whether a user asked to cancel the run, or its gate expired."""
    async with sessions() as session:
        at = await session.scalar(select(Run.cancel_requested_at).where(Run.id == run_id))
    return at is not None


async def cancel_reason(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> str:
    """Why the run is being cancelled: `USER_CANCEL_REASON` unless its gate expired
    (`agentic_store.expiry.APPROVAL_EXPIRED_REASON`)."""
    async with sessions() as session:
        reason = await session.scalar(select(Run.cancel_reason).where(Run.id == run_id))
    return reason or USER_CANCEL_REASON


async def run_ended(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> bool:
    """Whether the run's final event has been written."""
    async with sessions() as session:
        status = await session.scalar(select(Run.status).where(Run.id == run_id))
    return status in ENDED_STATUSES
