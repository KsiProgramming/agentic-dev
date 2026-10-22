"""The run summary columns `PostgresEventSink` projects from each run's events."""

import json
from pathlib import Path
from uuid import UUID

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.events import RunEvent, RunEventLog
from agentic_engine.gate import GateDecision
from agentic_engine.graph import checkpoint_serde, resume_workflow, run_workflow
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import Failed, Message
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime
from agentic_sandbox import RepoSource
from agentic_store import (
    DEFAULT_WORKSPACE_ID,
    PostgresEventSink,
    RunSummaryRow,
    create_run,
    get_run_summary,
    list_run_events,
    max_event_seq,
    record_approval,
)

pytestmark = pytest.mark.integration

SPECS = Path(__file__).resolve().parents[2] / "engine" / "tests" / "fixtures" / "specs" / "valid"


def spec(name: str) -> WorkflowSpec:
    return parse_spec(json.loads((SPECS / name).read_text(encoding="utf-8")))


def gated_spec() -> WorkflowSpec:
    """The gate fixture without its `repo.*` tools, so it runs with no sandbox."""
    data = json.loads((SPECS / "gate-approval.json").read_text(encoding="utf-8"))
    data["root"]["steps"][0]["tools"] = []
    data["root"]["steps"][2] = {"type": "agent", "id": "list", "role": "L", "instructions": "Go."}
    return parse_spec(data)


async def summary(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> RunSummaryRow:
    row = await get_run_summary(sessions, run_id)
    assert row is not None
    return row


async def first(sessions: async_sessionmaker[AsyncSession], run_id: UUID, type: str) -> RunEvent:
    return next(e for e in await list_run_events(sessions, run_id) if e.type == type)


async def test_a_completed_run_has_its_timings_from_the_log(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    repo = RepoSource(url="https://github.com/acme/docs")
    run_id = await create_run(
        sessions, spec("two-step-sequence.json"), "go", repo, template_id="generate-docs"
    )
    await run_workflow(
        spec("two-step-sequence.json"),
        FakeRuntime(),
        "go",
        run_id=run_id,
        sink=PostgresEventSink(sessions),
    )

    row = await summary(sessions, run_id)
    assert row.status == "completed"
    assert row.started_at == (await first(sessions, run_id, "run_started")).created_at
    assert row.finished_at == (await first(sessions, run_id, "run_completed")).created_at
    assert (row.failure_reason, row.pr_url, row.waiting_gate) == (None, None, None)
    assert (row.template_id, row.repo, row.workspace_id) == (
        "generate-docs",
        repo,
        DEFAULT_WORKSPACE_ID,
    )
    workflow = spec("two-step-sequence.json")
    assert (row.workflow_id, row.workflow_name) == (workflow.id, workflow.name)


async def test_a_failed_run_keeps_the_failing_nodes_error(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await create_run(sessions, spec("two-step-sequence.json"), "go")
    await run_workflow(
        spec("two-step-sequence.json"),
        FakeRuntime({"writer": [Failed(error="boom")]}),
        "go",
        run_id=run_id,
        sink=PostgresEventSink(sessions),
    )

    row = await summary(sessions, run_id)
    assert row.status == "failed"
    assert row.failure_reason == "node writer: boom"
    assert row.finished_at == (await first(sessions, run_id, "run_failed")).created_at


async def test_run_failed_with_an_error_sets_the_reason(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await create_run(sessions, spec("two-step-sequence.json"), "go")
    log = RunEventLog(run_id, PostgresEventSink(sessions))
    await log.emit("run_started")
    await log.emit("run_failed", payload={"error": "SandboxError: no docker"})

    row = await summary(sessions, run_id)
    assert (row.status, row.failure_reason) == ("failed", "SandboxError: no docker")


async def test_a_run_at_a_gate_shows_the_gate_until_it_is_decided(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    checkpointer = InMemorySaver(serde=checkpoint_serde())
    run_id = await create_run(sessions, gated_spec(), "go")
    await run_workflow(
        gated_spec(),
        FakeRuntime({"writer": [Message(text="notes"), ECHO_USAGE]}),
        "go",
        run_id=run_id,
        sink=PostgresEventSink(sessions),
        checkpointer=checkpointer,
    )

    row = await summary(sessions, run_id)
    assert row.status == "waiting"
    assert row.waiting_gate == {"node_id": "gate", "title": "Approve the notes"}
    assert row.finished_at is None
    started_at = row.started_at

    await record_approval(sessions, run_id, "gate", GateDecision(decision="approve"))
    await resume_workflow(
        gated_spec(),
        FakeRuntime(),
        "go",
        run_id=run_id,
        sink=PostgresEventSink(sessions),
        checkpointer=checkpointer,
        next_seq=await max_event_seq(sessions, run_id) + 1,
        attempt=2,
        decision=GateDecision(decision="approve"),
    )

    row = await summary(sessions, run_id)
    assert row.status == "completed"
    assert row.waiting_gate is None
    # A resumed run keeps its first start.
    assert row.started_at == started_at
    assert row.finished_at == (await first(sessions, run_id, "run_completed")).created_at


async def test_a_rejected_gate_ends_the_run_cancelled_with_no_gate(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    checkpointer = InMemorySaver(serde=checkpoint_serde())
    run_id = await create_run(sessions, gated_spec(), "go")
    await run_workflow(
        gated_spec(),
        FakeRuntime({"writer": [Message(text="notes"), ECHO_USAGE]}),
        "go",
        run_id=run_id,
        sink=PostgresEventSink(sessions),
        checkpointer=checkpointer,
    )
    reject = GateDecision(decision="reject", comment="no")
    await record_approval(sessions, run_id, "gate", reject)
    await resume_workflow(
        gated_spec(),
        FakeRuntime(),
        "go",
        run_id=run_id,
        sink=PostgresEventSink(sessions),
        checkpointer=checkpointer,
        next_seq=await max_event_seq(sessions, run_id) + 1,
        attempt=2,
        decision=reject,
    )

    row = await summary(sessions, run_id)
    assert row.status == "cancelled"
    assert (row.waiting_gate, row.failure_reason) == (None, None)
    assert row.finished_at == (await first(sessions, run_id, "run_cancelled")).created_at


async def test_the_last_opened_pr_is_the_runs_pr(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await create_run(sessions, spec("two-step-sequence.json"), "go")
    log = RunEventLog(run_id, PostgresEventSink(sessions))
    await log.emit("run_started")
    for number in (1, 2):
        url = f"https://github.com/acme/docs/pull/{number}"
        await log.emit("pr_opened", node_id="publish", payload={"url": url, "number": number})
    await log.emit("run_completed")

    row = await summary(sessions, run_id)
    assert row.pr_url == "https://github.com/acme/docs/pull/2"


async def test_a_second_run_started_keeps_the_first_start(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await create_run(sessions, spec("two-step-sequence.json"), "go")
    log = RunEventLog(run_id, PostgresEventSink(sessions))
    await log.emit("run_started")
    started_at = (await summary(sessions, run_id)).started_at
    await log.emit("run_started")

    assert started_at is not None
    assert (await summary(sessions, run_id)).started_at == started_at


async def test_an_unknown_run_has_no_summary(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    assert await get_run_summary(sessions, UUID(int=0)) is None
