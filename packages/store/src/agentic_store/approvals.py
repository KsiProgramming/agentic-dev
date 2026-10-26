"""Approvals: recording a human decision at the gate a run is paused at, and reading it back.

A run paused at a gate is `waiting` and no worker holds it. Recording the decision sets it back
to `queued` with no lease, so `claim_run` takes it like a new run once it is enqueued again; the
worker then continues it with `pending_decision`. Its `attempt` count starts again, so the time
a run spends at gates never uses up its retries. The gate a run waits at is the node of its last
`gate_waiting` event, whose `changes` are the files an approval may edit.
"""

from uuid import UUID

from pydantic import JsonValue, TypeAdapter, ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.events import GATE_WAITING
from agentic_engine.gate import EditError, EditErrorCode, FileChange, GateDecision, check_edits
from agentic_store.audit import audit
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


class InvalidEditsError(ApprovalError):
    """The decision's edits do not fit the files the gate showed (`code`, and the `path` of the
    file at fault, if one is)."""

    def __init__(self, code: EditErrorCode, message: str, path: str | None) -> None:
        super().__init__(message)
        self.code: EditErrorCode = code
        self.path = path


_CHANGES = TypeAdapter(list[FileChange])


async def record_approval(
    sessions: async_sessionmaker[AsyncSession],
    run_id: UUID,
    node_id: str,
    decision: GateDecision,
) -> GateDecision:
    """Record `decision` for the gate `node_id` the run is waiting at, and queue the run again;
    return it as recorded, without the edits that leave a file as it was. The caller enqueues
    it. Raises an `ApprovalError` if the run is not waiting at that gate, the gate was already
    decided, or the edits do not fit the files the gate showed (`InvalidEditsError`)."""
    try:
        async with sessions.begin() as session:
            # Locks the run, so two decisions for it are recorded one after the other.
            run = await session.scalar(select(Run).where(Run.id == run_id).with_for_update())
            if run is None:
                raise RunNotFoundError(f"run {run_id} not found")
            if run.status != "waiting":
                raise RunNotWaitingError(f"run {run_id} is {run.status}, not waiting at a gate")
            gate, changes = await _waiting_gate_changes(session, run_id)
            if gate != node_id:
                raise WrongGateError(f"run {run_id} is waiting at gate {gate!r}, not {node_id!r}")
            if await _approval(session, run_id, node_id) is not None:
                raise AlreadyDecidedError(f"gate {node_id!r} of run {run_id} was already decided")
            try:
                edits = check_edits(changes, decision.decision, decision.edits)
            except EditError as e:
                raise InvalidEditsError(e.code, str(e), e.path) from e
            decision = decision.model_copy(update={"edits": edits})
            workspace_id = run.workspace_id
            session.add(
                Approval(
                    run_id=run_id,
                    node_id=node_id,
                    decision=decision.decision,
                    comment=decision.comment,
                    decided_by=decision.decided_by,
                    edits=[e.model_dump(mode="json") for e in edits] or None,
                )
            )
            await session.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(status="queued", worker_id=None, lease_expires_at=None, attempt=0)
            )
            audit(
                session,
                workspace_id,
                "gate.approved" if decision.decision == "approve" else "gate.rejected",
                run_id=run_id,
                node_id=node_id,
                # Paths only: the edited contents stay in the approval and the run's events.
                details={
                    "comment": decision.comment,
                    "edited_files": len(edits),
                    "edited_paths": [e.path for e in edits],
                },
            )
    except IntegrityError as e:
        raise AlreadyDecidedError(f"gate {node_id!r} of run {run_id} was already decided") from e
    return decision


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
            "edits": approval.edits or [],
        }
    )


async def _waiting_gate_changes(
    session: AsyncSession, run_id: UUID
) -> tuple[str | None, list[FileChange]]:
    """The gate the run last paused at, and the files its pause showed (none if its payload has
    none, as before phase 3.6, or they cannot be read)."""
    row = (
        await session.execute(
            select(RunEventRow.node_id, RunEventRow.payload)
            .where(RunEventRow.run_id == run_id, RunEventRow.type == GATE_WAITING)
            .order_by(RunEventRow.seq.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None, []
    shown: JsonValue = row.payload.get("changes", [])
    try:
        return row.node_id, _CHANGES.validate_python(shown)
    except ValidationError:
        return row.node_id, []


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
