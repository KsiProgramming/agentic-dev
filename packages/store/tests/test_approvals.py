"""Recording a decision at the gate a run is paused at, and continuing the run with it."""

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.gate import GateDecision
from agentic_engine.graph import checkpoint_serde, resume_workflow, run_workflow
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import Message
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime
from agentic_store import (
    AlreadyDecidedError,
    Approval,
    PostgresEventSink,
    RunNotFoundError,
    RunNotWaitingError,
    WrongGateError,
    create_run,
    get_run,
    max_event_seq,
    pending_decision,
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


async def paused_run(
    sessions: async_sessionmaker[AsyncSession], checkpointer: InMemorySaver
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


async def test_a_gate_is_decided_once(sessions: async_sessionmaker[AsyncSession]) -> None:
    run_id = await paused_run(sessions, InMemorySaver(serde=checkpoint_serde()))
    async with sessions.begin() as session:
        session.add(Approval(run_id=run_id, node_id="gate", decision="reject"))

    with pytest.raises(AlreadyDecidedError):
        await record_approval(sessions, run_id, "gate", APPROVE)
