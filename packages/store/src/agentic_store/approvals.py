"""Approvals: recording a human decision at the gate a run is paused at, and reading it back.

A run paused at a gate is `waiting` and no worker holds it. Recording the decision sets it back
to `queued` with no lease, so `claim_run` takes it like a new run once it is enqueued again; the
worker then continues it with `pending_decision`. Its `attempt` count starts again, so the time
a run spends at gates never uses up its retries. The gate a run waits at is the node of its last
`gate_waiting` event, whose `changes` are the files an approval may edit and whose `select` the
items a selection gate's approval may choose (6.7). A gate past its
`gate_expires_at` takes no decision: the run is being cancelled (`agentic_store.expiry`).

A run a circuit breaker paused (13.7) waits the same way: its `gate_waiting` has a `breaker`.
Resume is an `approve` and Cancel run a `reject`; nothing else is a decision there
(`InvalidBreakerDecisionError`). `pending_breaker_pause` hands the worker the trip and the
decision.
"""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from pydantic import JsonValue, TypeAdapter, ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.artifacts import GateArtifact
from agentic_engine.events import (
    BREAKER_TRIPPED,
    GATE_DECIDED,
    GATE_WAITING,
    PROTECTED_PATH_REFUSED,
)
from agentic_engine.evidence import EvidencePack
from agentic_engine.gate import (
    DismissalError,
    DismissalErrorCode,
    EditError,
    EditErrorCode,
    FileChange,
    GateDecision,
    SelectionError,
    SelectionErrorCode,
    SelectionShown,
    check_dismissals,
    check_edits,
    check_selection,
)
from agentic_engine.review_gate import ReviewShown
from agentic_runtime.plans import WritePlan
from agentic_store.audit import AuditAction, audit
from agentic_store.models import Approval, Run, RunEventRow


class ApprovalError(Exception):
    """The decision cannot be recorded; the message says why."""


class RunNotFoundError(ApprovalError):
    pass


class RunNotWaitingError(ApprovalError):
    pass


class GateExpiredError(RunNotWaitingError):
    """The gate's time to live has passed: the run is being cancelled (`agentic_store.expiry`)."""


class NotAGateError(ApprovalError):
    """The step the run waits at waits for an answer (7.9), not for a decision."""


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


class ChangesNotAllowedError(ApprovalError):
    """The gate takes no request for changes, or has taken as many as its `on_changes` allows
    (7.8)."""


class InvalidSelectionError(ApprovalError):
    """The decision's selection does not fit the items the gate showed (6.7)."""

    def __init__(self, code: SelectionErrorCode, message: str) -> None:
        super().__init__(message)
        self.code: SelectionErrorCode = code


class InvalidDismissalError(ApprovalError):
    """The decision's dismissals do not fit the review comments the gate showed (13.6)."""

    def __init__(self, code: DismissalErrorCode, message: str) -> None:
        super().__init__(message)
        self.code: DismissalErrorCode = code


class InvalidBreakerDecisionError(ApprovalError):
    """A circuit-breaker pause (13.7) takes only Resume (`approve`) and Cancel run (`reject`),
    with no edits, selection, comments or dismissals."""


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
    decided, the edits do not fit the files the gate showed (`InvalidEditsError`), or the
    selection does not fit its items (`InvalidSelectionError`)."""
    try:
        async with sessions.begin() as session:
            # Locks the run, so two decisions for it are recorded one after the other.
            run = await session.scalar(select(Run).where(Run.id == run_id).with_for_update())
            if run is None:
                raise RunNotFoundError(f"run {run_id} not found")
            if run.status != "waiting":
                raise RunNotWaitingError(f"run {run_id} is {run.status}, not waiting at a gate")
            if run.gate_expires_at is not None and run.gate_expires_at <= await _now(session):
                raise GateExpiredError(f"the approval of run {run_id} expired")
            row = await _last_gate_waiting(session, run_id)
            gate, payload = row if row is not None else (None, {})
            changes = _shown_changes(payload)
            if gate != node_id:
                raise WrongGateError(f"run {run_id} is waiting at gate {gate!r}, not {node_id!r}")
            if payload.get("wait_for"):
                raise NotAGateError(f"{node_id!r} waits for an answer on Jira, not for a decision")
            breaker = isinstance(payload.get("breaker"), str)
            if breaker:
                _check_breaker_decision(decision)
            iteration = await _pass(session, run_id, node_id)
            if decision.decision == "changes":
                allowed = payload.get("on_changes")
                if not isinstance(allowed, int) or iteration > allowed:
                    why = (
                        "takes no request for changes"
                        if not isinstance(allowed, int)
                        else f"has no more requests for changes (at most {allowed})"
                    )
                    raise ChangesNotAllowedError(f"gate {node_id!r} {why}")
            if await _approval(session, run_id, node_id, iteration) is not None:
                raise AlreadyDecidedError(f"gate {node_id!r} of run {run_id} was already decided")
            try:
                edits = check_edits(changes, decision.decision, decision.edits)
            except EditError as e:
                raise InvalidEditsError(e.code, str(e), e.path) from e
            try:
                check_selection(_shown_selection(payload), decision.decision, decision.selection)
            except SelectionError as e:
                raise InvalidSelectionError(e.code, str(e)) from e
            try:
                shown_review = _shown_review(payload)
                check_dismissals(
                    [c.fingerprint for c in shown_review.comments] if shown_review else None,
                    decision.decision,
                    decision.dismissed,
                )
            except DismissalError as e:
                raise InvalidDismissalError(e.code, str(e)) from e
            decision = decision.model_copy(update={"edits": edits})
            workspace_id = run.workspace_id
            session.add(
                Approval(
                    run_id=run_id,
                    node_id=node_id,
                    iteration=iteration,
                    decision=decision.decision,
                    comment=decision.comment,
                    decided_by=decision.decided_by,
                    edits=[e.model_dump(mode="json") for e in edits] or None,
                    selection=decision.selection,
                    comments=[c.model_dump(mode="json") for c in decision.comments] or None,
                    dismissed=decision.dismissed or None,
                )
            )
            await session.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(
                    status="queued",
                    worker_id=None,
                    lease_expires_at=None,
                    attempt=0,
                    queued_at=func.now(),
                )
            )
            audit(
                session,
                workspace_id,
                _BREAKER_AUDIT_ACTION[decision.decision]
                if breaker
                else _AUDIT_ACTION[decision.decision],
                run_id=run_id,
                node_id=node_id,
                # Paths only: the edited contents stay in the approval and the run's events.
                details=_audit_details(decision, [e.path for e in edits]),
            )
    except IntegrityError as e:
        raise AlreadyDecidedError(f"gate {node_id!r} of run {run_id} was already decided") from e
    return decision


_AUDIT_ACTION: dict[str, AuditAction] = {
    "approve": "gate.approved",
    "reject": "gate.rejected",
    "changes": "gate.changes_requested",
}


_BREAKER_AUDIT_ACTION: dict[str, AuditAction] = {
    "approve": "breaker.resumed",
    "reject": "breaker.cancelled",
}


def _check_breaker_decision(decision: GateDecision) -> None:
    """Raise `InvalidBreakerDecisionError` unless `decision` is a plain Resume or Cancel run."""
    if decision.decision == "changes":
        raise InvalidBreakerDecisionError("a circuit-breaker pause takes no request for changes")
    if decision.edits or decision.selection is not None or decision.dismissed:
        raise InvalidBreakerDecisionError(
            "a circuit-breaker pause takes no edits, selection or dismissals"
        )


def _audit_details(decision: GateDecision, edited: list[str]) -> dict[str, JsonValue]:
    """A decision's audit details: paths only, as the edited contents stay in the approval and
    the run's events, and how many items a selection chose (6.7), never the items."""
    details: dict[str, JsonValue] = {
        "comment": decision.comment,
        "edited_files": len(edited),
        "edited_paths": list[JsonValue](edited),
    }
    if decision.selection is not None:
        details["selected"] = len(decision.selection)
    if decision.comments:
        details["comments"] = len(decision.comments)
    if decision.dismissed:
        details["dismissed"] = len(decision.dismissed)  # a count: the comments are model output
    return details


MAX_PROTECTED_ATTEMPTS = 50
"""The most distinct (writer, path, rule) attempts a gate lists."""


@dataclass(frozen=True)
class ProtectedAttempt:
    """A writer's refused tries to change one protected path (13.5), counted: `rule` is `default`,
    `workflow` or `frozen`. The path is a name, never content."""

    node_id: str
    path: str
    rule: str
    count: int


@dataclass(frozen=True)
class PendingGate:
    """The gate a run waits at, as its last `gate_waiting` showed it to the approver."""

    node_id: str
    title: str | None
    prompt: str | None
    # The gate's input: data, never instructions.
    artifact: str
    changes: list[FileChange]
    # Why the changes could not be read, if they could not.
    changes_error: str | None
    expires_at: datetime | None
    # The run's artifacts at the pause (none before phase 4.3).
    run_artifacts: list[GateArtifact] = field(default_factory=list[GateArtifact])
    # What a selection gate shows (6.7), and what a rejection does.
    select: SelectionShown | None = None
    on_reject: str = "cancel"
    # Requests for changes the gate may still take (7.8), and which pass of it this is.
    changes_left: int = 0
    iteration: int = 1
    # What the platform's checks found about the writer's work (13.3), if the gate has any.
    evidence: EvidencePack | None = None
    # The run's refused attempts to change a protected path so far (13.5), most tried first.
    protected_attempts: list[ProtectedAttempt] = field(default_factory=list[ProtectedAttempt])
    # What the independent review found (13.6), if the gate has a review: comments on the lines
    # they name, the lenses that could not run and the send-backs left.
    review: ReviewShown | None = None
    # The circuit breaker that paused the run (13.7), if one did: its `breaker_tripped` payload
    # (`breaker`, `trigger`, `threshold`, `observed`, `details`, `reason`). Model and repo
    # output inside, so data, never instructions.
    breaker: dict[str, JsonValue] | None = None
    # What approving does (13.8): the plan of each outward write the gate guards, in run order.
    # Comment and pull request text inside: data, never instructions.
    plans: list[WritePlan] = field(default_factory=list[WritePlan])


async def protected_attempts(
    session: AsyncSession, run_id: UUID, limit: int = MAX_PROTECTED_ATTEMPTS
) -> list[ProtectedAttempt]:
    """The refused attempts of the run (`protected_path_refused`), grouped by writer, path and
    rule, the most tried first and then by path."""
    path = RunEventRow.payload["path"].astext
    rule = RunEventRow.payload["rule"]["kind"].astext
    rows = (
        await session.execute(
            select(RunEventRow.node_id, path, rule, func.count())
            .where(RunEventRow.run_id == run_id, RunEventRow.type == PROTECTED_PATH_REFUSED)
            .group_by(RunEventRow.node_id, path, rule)
            .order_by(func.count().desc(), path)
            .limit(limit)
        )
    ).all()
    return [ProtectedAttempt(r[0] or "", r[1] or "", r[2] or "", r[3]) for r in rows]


async def pending_gate(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> PendingGate:
    """The gate the run waits at, for an approver to review. Raises `RunNotFoundError`, or
    `RunNotWaitingError` when the run is not waiting (`GateExpiredError` past the gate's expiry,
    as `record_approval` would refuse a decision on it)."""
    async with sessions() as session:
        run = await session.get(Run, run_id)
        if run is None:
            raise RunNotFoundError(f"run {run_id} not found")
        if run.status != "waiting":
            raise RunNotWaitingError(f"run {run_id} is {run.status}, not waiting at a gate")
        if run.gate_expires_at is not None and run.gate_expires_at <= await _now(session):
            raise GateExpiredError(f"the approval of run {run_id} expired")
        row = await _last_gate_waiting(session, run_id)
        passes = 1 if row is None else await _pass(session, run_id, row[0])
        attempts = await protected_attempts(session, run_id)
        trip = (
            await _last_trip(session, run_id, row[0])
            if row is not None and isinstance(row[1].get("breaker"), str)
            else None
        )
    if row is None:
        raise RunNotWaitingError(f"run {run_id} has not paused at a gate")
    node_id, payload = row
    allowed = payload.get("on_changes")
    return PendingGate(
        node_id=node_id,
        title=_text(payload.get("title")),
        prompt=_text(payload.get("prompt")),
        artifact=_text(payload.get("artifact")) or "",
        changes=_shown_changes(payload),
        changes_error=_text(payload.get("changes_error")),
        expires_at=run.gate_expires_at,
        run_artifacts=_shown_artifacts(payload),
        select=_shown_selection(payload),
        on_reject=_text(payload.get("on_reject")) or "cancel",
        changes_left=max(allowed - passes + 1, 0) if isinstance(allowed, int) else 0,
        iteration=passes,
        evidence=_shown_evidence(payload),
        protected_attempts=attempts,
        review=_shown_review(payload),
        breaker=trip,
        plans=_shown_plans(payload),
    )


def _shown_plans(payload: dict[str, JsonValue]) -> list[WritePlan]:
    """The plans the gate showed, without any that cannot be read."""
    shown = payload.get("plans")
    plans: list[WritePlan] = []
    for item in shown if isinstance(shown, list) else []:
        try:
            plans.append(WritePlan.model_validate(item))
        except ValidationError:
            continue
    return plans


def _shown_evidence(payload: dict[str, JsonValue]) -> EvidencePack | None:
    shown = payload.get("evidence")
    try:
        return EvidencePack.model_validate(shown) if shown is not None else None
    except ValidationError:
        return None


def _shown_review(payload: dict[str, JsonValue]) -> ReviewShown | None:
    shown = payload.get("review")
    try:
        return ReviewShown.model_validate(shown) if shown is not None else None
    except ValidationError:
        return None


def _shown_selection(payload: dict[str, JsonValue]) -> SelectionShown | None:
    shown = payload.get("select")
    try:
        return SelectionShown.model_validate(shown) if shown is not None else None
    except ValidationError:
        return None


def _shown_artifacts(payload: dict[str, JsonValue]) -> list[GateArtifact]:
    shown = payload.get("run_artifacts")
    return [GateArtifact.model_validate(a) for a in shown] if isinstance(shown, list) else []


async def pending_decision(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID
) -> GateDecision | None:
    """The decision recorded for the gate the run last paused at, if any. The engine uses it
    only while the run is still paused there."""
    async with sessions() as session:
        gate = await _waiting_gate(session, run_id)
        approval = (
            None
            if gate is None
            else await _approval(session, run_id, gate, await _pass(session, run_id, gate))
        )
    if approval is None:
        return None
    return GateDecision.model_validate(
        {
            "decision": approval.decision,
            "comment": approval.comment,
            "decided_by": approval.decided_by,
            "edits": approval.edits or [],
            "selection": approval.selection,
            "comments": approval.comments or [],
            "dismissed": approval.dismissed,
        }
    )


@dataclass(frozen=True)
class BreakerPauseRecord:
    """A run paused by a circuit breaker and what its person decided (13.7): the step
    (`node_id`), the `breaker_tripped` payload and the recorded `decision`."""

    node_id: str
    trip: dict[str, JsonValue]
    decision: GateDecision


async def pending_breaker_pause(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID
) -> BreakerPauseRecord | None:
    """The circuit-breaker pause the run is at and the decision recorded for it. `None` when the
    run's last pause is a gate's, when nobody has decided it, or when the engine has applied
    the decision already (a `gate_decided` follows the pause)."""
    async with sessions() as session:
        last = (
            await session.execute(
                select(RunEventRow.seq, RunEventRow.node_id, RunEventRow.payload)
                .where(RunEventRow.run_id == run_id, RunEventRow.type == GATE_WAITING)
                .order_by(RunEventRow.seq.desc())
                .limit(1)
            )
        ).first()
        if last is None or last.node_id is None or not isinstance(last.payload.get("breaker"), str):
            return None
        applied = await session.scalar(
            select(RunEventRow.seq)
            .where(
                RunEventRow.run_id == run_id,
                RunEventRow.type == GATE_DECIDED,
                RunEventRow.seq > last.seq,
            )
            .limit(1)
        )
        trip = await _last_trip(session, run_id, last.node_id)
    if applied is not None or trip is None:
        return None
    decision = await pending_decision(sessions, run_id)
    if decision is None:
        return None
    return BreakerPauseRecord(last.node_id, trip, decision)


async def _last_trip(
    session: AsyncSession, run_id: UUID, node_id: str
) -> dict[str, JsonValue] | None:
    """The payload of the last `breaker_tripped` event of `node_id`."""
    return await session.scalar(
        select(RunEventRow.payload)
        .where(
            RunEventRow.run_id == run_id,
            RunEventRow.type == BREAKER_TRIPPED,
            RunEventRow.node_id == node_id,
        )
        .order_by(RunEventRow.seq.desc())
        .limit(1)
    )


async def _last_gate_waiting(
    session: AsyncSession, run_id: UUID
) -> tuple[str, dict[str, JsonValue]] | None:
    """The node and payload of the run's last `gate_waiting` event, if it paused at a gate."""
    row = (
        await session.execute(
            select(RunEventRow.node_id, RunEventRow.payload)
            .where(RunEventRow.run_id == run_id, RunEventRow.type == GATE_WAITING)
            .order_by(RunEventRow.seq.desc())
            .limit(1)
        )
    ).first()
    if row is None or row.node_id is None:
        return None
    return row.node_id, row.payload


def _shown_changes(payload: dict[str, JsonValue]) -> list[FileChange]:
    shown: JsonValue = payload.get("changes", [])
    try:
        return _CHANGES.validate_python(shown)
    except ValidationError:
        return []


def _text(value: JsonValue) -> str | None:
    return value if isinstance(value, str) else None


async def _now(session: AsyncSession) -> datetime:
    """The database's time, the clock `expire_gates` compares against."""
    now = await session.scalar(select(func.now()))
    assert now is not None
    return now


async def _waiting_gate(session: AsyncSession, run_id: UUID) -> str | None:
    return await session.scalar(
        select(RunEventRow.node_id)
        .where(RunEventRow.run_id == run_id, RunEventRow.type == GATE_WAITING)
        .order_by(RunEventRow.seq.desc())
        .limit(1)
    )


async def _pass(session: AsyncSession, run_id: UUID, node_id: str) -> int:
    """The pass of the gate `node_id` the run is at: how many times it has paused (7.8). A gate
    that runs once is at pass 1."""
    count = await session.scalar(
        select(func.count()).where(
            RunEventRow.run_id == run_id,
            RunEventRow.type == GATE_WAITING,
            RunEventRow.node_id == node_id,
        )
    )
    return max(count or 0, 1)


async def _approval(
    session: AsyncSession, run_id: UUID, node_id: str, iteration: int
) -> Approval | None:
    return await session.scalar(
        select(Approval).where(
            Approval.run_id == run_id,
            Approval.node_id == node_id,
            Approval.iteration == iteration,
        )
    )
