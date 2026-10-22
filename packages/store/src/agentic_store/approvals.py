"""Approvals: recording a human decision at the gate a run is paused at, and reading it back.

A run paused at a gate is `waiting` and no worker holds it. Recording the decision sets it back
to `queued` with no lease, so `claim_run` takes it like a new run once it is enqueued again; the
worker then continues it with `pending_decision`. The gate a run waits at is the node of its last
`gate_waiting` event.
"""

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.events import GATE_WAITING
from agentic_engine.gate import GateDecision
from agentic_store.models import Approval, Run, RunEventRow


class ApprovalError(Exception):
    """The decision cannot be recorded; the message says why."""


class RunNotFoundError(ApprovalError):
    pass


class RunNotWaitingError(ApprovalError):
    pass


class WrongGateError(ApprovalError):
    pass


class AlreadyDecidedError(ApprovalError):
    pass


async def record_approval(
    sessions: async_sessionmaker[AsyncSession],
    run_id: UUID,
    node_id: str,
    decision: GateDecision,
) -> None:
    """Record `decision` for the gate `node_id` the run is waiting at, and queue the run again.
    The caller enqueues it. Raises an `ApprovalError` if the run is not waiting at that gate or
    the gate was already decided."""
    try:
        async with sessions.begin() as session:
            # Locks the run, so two decisions for it are recorded one after the other.
            run = await session.scalar(select(Run).where(Run.id == run_id).with_for_update())
            if run is None:
                raise RunNotFoundError(f"run {run_id} not found")
            if run.status != "waiting":
                raise RunNotWaitingError(f"run {run_id} is {run.status}, not waiting at a gate")
            gate = await _waiting_gate(session, run_id)
            if gate != node_id:
                raise WrongGateError(f"run {run_id} is waiting at gate {gate!r}, not {node_id!r}")
            if await _approval(session, run_id, node_id) is not None:
                raise AlreadyDecidedError(f"gate {node_id!r} of run {run_id} was already decided")
            session.add(
                Approval(
                    run_id=run_id,
                    node_id=node_id,
                    decision=decision.decision,
                    comment=decision.comment,
                    decided_by=decision.decided_by,
                )
            )
            await session.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(status="queued", worker_id=None, lease_expires_at=None)
            )
    except IntegrityError as e:
        raise AlreadyDecidedError(f"gate {node_id!r} of run {run_id} was already decided") from e


async def pending_decision(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID
) -> GateDecision | None:
    """The decision recorded for the gate the run last paused at, if any. The engine uses it
    only while the run is still paused there."""
    async with sessions() as session:
        gate = await _waiting_gate(session, run_id)
        approval = None if gate is None else await _approval(session, run_id, gate)
    if approval is None:
        return None
    return GateDecision.model_validate(
        {
            "decision": approval.decision,
            "comment": approval.comment,
            "decided_by": approval.decided_by,
        }
    )


async def _waiting_gate(session: AsyncSession, run_id: UUID) -> str | None:
    return await session.scalar(
        select(RunEventRow.node_id)
        .where(RunEventRow.run_id == run_id, RunEventRow.type == GATE_WAITING)
        .order_by(RunEventRow.seq.desc())
        .limit(1)
    )


async def _approval(session: AsyncSession, run_id: UUID, node_id: str) -> Approval | None:
    return await session.scalar(
        select(Approval).where(Approval.run_id == run_id, Approval.node_id == node_id)
    )
