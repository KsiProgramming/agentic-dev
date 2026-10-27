"""Approval expiry: a gate nobody decides cancels its run once its time to live has passed.

A gate's `gate_waiting` event says when it expires (`expires_at`, from the gate's `ttl_s` or the
run policy's `approval_ttl_s`), and the event sink keeps it in `runs.gate_expires_at`. Only
workers write events, so expiry is a cancel request like a user's (`agentic_store.cancel`):
`expire_gates` marks each expired run cancel-requested with `APPROVAL_EXPIRED_REASON` and
queues it again, and the worker that claims it ends it `cancelled` with that reason and removes
its sandbox. Every worker sweeps (`WorkerSettings.gate_sweep_s`); the rows are locked with
`SKIP LOCKED`, so two sweeps never expire a run twice.
"""

from typing import Final
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_store.audit import audit
from agentic_store.models import Approval, Run

APPROVAL_EXPIRED_REASON: Final = "Approval expired"
"""The `reason` of the `run_cancelled` event of a run whose gate expired."""


async def expire_gates(sessions: async_sessionmaker[AsyncSession]) -> list[UUID]:
    """Cancel every run waiting at a gate past its expiry with no decision recorded, and return
    their ids, for the caller to enqueue. Each gets a `gate.expired` audit entry."""
    decided = select(Approval.run_id).where(
        Approval.run_id == Run.id, Approval.node_id == Run.waiting_gate["node_id"].astext
    )
    async with sessions.begin() as session:
        runs = (
            await session.scalars(
                select(Run)
                .where(
                    Run.status == "waiting",
                    Run.gate_expires_at <= func.now(),
                    ~decided.exists(),
                )
                .order_by(Run.gate_expires_at)
                .with_for_update(skip_locked=True)
            )
        ).all()
        expired: list[UUID] = []
        for run in runs:
            gate = run.waiting_gate or {}
            audit(
                session,
                run.workspace_id,
                "gate.expired",
                actor_type="system",
                run_id=run.id,
                node_id=str(gate.get("node_id")) if gate.get("node_id") is not None else None,
                details={
                    "title": gate.get("title"),
                    "expires_at": None
                    if run.gate_expires_at is None
                    else run.gate_expires_at.isoformat(),
                },
            )
            expired.append(run.id)
        if expired:
            await session.execute(
                update(Run)
                .where(Run.id.in_(expired))
                .values(
                    status="queued",
                    worker_id=None,
                    lease_expires_at=None,
                    attempt=0,
                    cancel_requested_at=func.coalesce(Run.cancel_requested_at, func.now()),
                    cancel_reason=func.coalesce(Run.cancel_reason, APPROVAL_EXPIRED_REASON),
                )
            )
    return expired
