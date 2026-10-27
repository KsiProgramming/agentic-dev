"""Recording a decision at the gate a run is paused at, and continuing the run with it."""

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.gate import FileChange, FileEdit, GateDecision, GateReview
from agentic_engine.graph import checkpoint_serde, resume_workflow, run_workflow
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import Message
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime
from agentic_store import (
    AlreadyDecidedError,
    Approval,
    GateExpiredError,
    InvalidEditsError,
    PostgresEventSink,
    Run,
    RunNotFoundError,
    RunNotWaitingError,
    WrongGateError,
    create_run,
    get_run,
    max_event_seq,
    pending_decision,
    pending_gate,
    record_approval,
)

pytestmark = pytest.mark.integration

SPEC = (
    Path(__file__).resolve().parents[2]
    / "engine"
    / "tests"
    / "fixtures"
    / "specs"
    / "valid"
    / "gate-approval.json"
)
APPROVE = GateDecision(decision="approve", comment="looks good")


def gated_spec() -> WorkflowSpec:
    """The gate fixture without its `repo.*` tools, so it runs with no sandbox."""
    data = json.loads(SPEC.read_text(encoding="utf-8"))
    data["root"]["steps"][0]["tools"] = []
    data["root"]["steps"][2] = {"type": "agent", "id": "list", "role": "L", "instructions": "Go."}
    return parse_spec(data)


PAGE = FileChange(node_id="writer", path="docs/a.md", status="added", editable=True, after="# A\n")
LOGO = FileChange(
    node_id="writer", path="logo.png", status="added", editable=False, reason="binary"
)
EDIT = FileEdit(node_id="writer", path="docs/a.md", content="# A, edited\n")


class ShownReview:
    """Shows `PAGE` and `LOGO` at the gate; edits are not applied here."""

    async def changes(self, ran: Sequence[str]) -> list[FileChange]:
        return [PAGE, LOGO]

    async def apply(self, gate_id: str, edits: Sequence[FileEdit]) -> dict[str, str]:
        return {"writer": "0" * 40}


async def paused_run(
    sessions: async_sessionmaker[AsyncSession],
    checkpointer: InMemorySaver,
    review: GateReview | None = None,
) -> UUID:
    spec = gated_spec()
    run_id = await create_run(sessions, spec, "go")
    result = await run_workflow(
        spec,
        FakeRuntime({"writer": [Message(text="notes"), ECHO_USAGE]}),
        "go",
        run_id=run_id,
        sink=PostgresEventSink(sessions),
        checkpointer=checkpointer,
        review=review,
    )
    assert result.status == "waiting"
    return run_id


async def test_gate_waiting_sets_the_run_waiting(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await paused_run(sessions, InMemorySaver(serde=checkpoint_serde()))

    run = await get_run(sessions, run_id)
    assert run is not None and run.status == "waiting"
    assert await pending_decision(sessions, run_id) is None


async def test_approval_queues_the_run_and_it_completes(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    checkpointer = InMemorySaver(serde=checkpoint_serde())
    run_id = await paused_run(sessions, checkpointer)

    await record_approval(sessions, run_id, "gate", APPROVE)

    run = await get_run(sessions, run_id)
    assert run is not None and run.status == "queued"
    assert await pending_decision(sessions, run_id) == APPROVE
    async with sessions() as session:
        approval = await session.scalar(select(Approval).where(Approval.run_id == run_id))
    assert approval is not None
    assert approval.node_id == "gate"
    assert (approval.decision, approval.comment) == ("approve", "looks good")

    result = await resume_workflow(
        gated_spec(),
        FakeRuntime(),
        "go",
        run_id=run_id,
        sink=PostgresEventSink(sessions),
        checkpointer=checkpointer,
        next_seq=await max_event_seq(sessions, run_id) + 1,
        attempt=2,
        decision=await pending_decision(sessions, run_id),
    )

    assert result.status == "completed"
    run = await get_run(sessions, run_id)
    assert run is not None and run.status == "completed"


async def test_decisions_that_do_not_fit_are_refused(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await paused_run(sessions, InMemorySaver(serde=checkpoint_serde()))

    with pytest.raises(RunNotFoundError):
        await record_approval(sessions, uuid4(), "gate", APPROVE)
    with pytest.raises(WrongGateError, match="waiting at gate 'gate', not 'writer'"):
        await record_approval(sessions, run_id, "writer", APPROVE)

    await record_approval(sessions, run_id, "gate", APPROVE)
    with pytest.raises(RunNotWaitingError, match="is queued"):
        await record_approval(sessions, run_id, "gate", APPROVE)


async def test_the_pending_gate_is_what_its_pause_showed(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await paused_run(sessions, InMemorySaver(serde=checkpoint_serde()), ShownReview())

    gate = await pending_gate(sessions, run_id)

    assert gate.node_id == "gate"
    assert gate.title == "Approve the notes"
    assert gate.prompt == "Check the writer's summary before the run continues."
    assert gate.artifact == "notes"
    assert gate.changes == [PAGE, LOGO]
    assert gate.changes_error is None
    async with sessions() as session:
        expires_at = await session.scalar(select(Run.gate_expires_at).where(Run.id == run_id))
    assert gate.expires_at == expires_at is not None


async def test_only_a_waiting_run_has_a_pending_gate(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await paused_run(sessions, InMemorySaver(serde=checkpoint_serde()))

    with pytest.raises(RunNotFoundError):
        await pending_gate(sessions, uuid4())
    async with sessions.begin() as session:
        await session.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(gate_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    with pytest.raises(GateExpiredError):
        await pending_gate(sessions, run_id)
    async with sessions.begin() as session:
        await session.execute(update(Run).where(Run.id == run_id).values(status="queued"))
    with pytest.raises(RunNotWaitingError, match="is queued"):
        await pending_gate(sessions, run_id)


async def test_a_gate_is_decided_once(sessions: async_sessionmaker[AsyncSession]) -> None:
    run_id = await paused_run(sessions, InMemorySaver(serde=checkpoint_serde()))
    async with sessions.begin() as session:
        session.add(Approval(run_id=run_id, node_id="gate", decision="reject"))

    with pytest.raises(AlreadyDecidedError):
        await record_approval(sessions, run_id, "gate", APPROVE)


async def test_an_approval_keeps_its_edits_for_the_run(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await paused_run(sessions, InMemorySaver(serde=checkpoint_serde()), ShownReview())
    same = FileEdit(node_id="writer", path="docs/a.md", content="# A\n")

    recorded = await record_approval(
        sessions, run_id, "gate", GateDecision(decision="approve", edits=[EDIT])
    )

    assert recorded.edits == [EDIT]
    decision = await pending_decision(sessions, run_id)
    assert decision is not None and decision.edits == [EDIT]
    async with sessions() as session:
        approval = await session.scalar(select(Approval).where(Approval.run_id == run_id))
    assert approval is not None and approval.edits == [EDIT.model_dump(mode="json")]
    # An edit that leaves the file as it was is no edit.
    other = await paused_run(sessions, InMemorySaver(serde=checkpoint_serde()), ShownReview())
    unchanged = await record_approval(
        sessions, other, "gate", GateDecision(decision="approve", edits=[same])
    )
    assert unchanged.edits == []
    async with sessions() as session:
        approval = await session.scalar(select(Approval).where(Approval.run_id == other))
    assert approval is not None and approval.edits is None


@pytest.mark.parametrize(
    ("decision", "code", "path"),
    [
        (
            GateDecision(
                decision="approve",
                edits=[FileEdit(node_id="writer", path="logo.png", content="x")],
            ),
            "edit_not_allowed",
            "logo.png",
        ),
        (GateDecision(decision="reject", edits=[EDIT]), "edits_with_reject", None),
        (
            GateDecision(
                decision="approve",
                edits=[EDIT.model_copy(update={"content": "x" * (256 * 1024 + 1)})],
            ),
            "edit_too_large",
            "docs/a.md",
        ),
        (GateDecision(decision="approve", edits=[EDIT, EDIT]), "duplicate_edit", "docs/a.md"),
    ],
    ids=["not-editable", "reject", "too-large", "duplicate"],
)
async def test_edits_that_do_not_fit_the_gate_are_refused(
    sessions: async_sessionmaker[AsyncSession],
    decision: GateDecision,
    code: str,
    path: str | None,
) -> None:
    run_id = await paused_run(sessions, InMemorySaver(serde=checkpoint_serde()), ShownReview())

    with pytest.raises(InvalidEditsError) as e:
        await record_approval(sessions, run_id, "gate", decision)

    assert (e.value.code, e.value.path) == (code, path)
    run = await get_run(sessions, run_id)
    assert run is not None and run.status == "waiting"
    assert await pending_decision(sessions, run_id) is None


async def test_a_gate_that_showed_no_changes_takes_no_edits(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await paused_run(sessions, InMemorySaver(serde=checkpoint_serde()))

    with pytest.raises(InvalidEditsError) as e:
        await record_approval(
            sessions, run_id, "gate", GateDecision(decision="approve", edits=[EDIT])
        )

    assert e.value.code == "edit_not_allowed"
