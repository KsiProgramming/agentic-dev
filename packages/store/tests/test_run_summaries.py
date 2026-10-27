"""The run summary columns `PostgresEventSink` projects from each run's events."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.agent import sum_usage
from agentic_engine.events import RunEvent, RunEventLog
from agentic_engine.gate import GateDecision
from agentic_engine.graph import checkpoint_serde, resume_workflow, run_workflow
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import Failed, Message, Usage, agent_event_adapter
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime
from agentic_sandbox import RepoSource
from agentic_store import (
    DEFAULT_WORKSPACE_ID,
    PostgresEventSink,
    RunSummaryRow,
    RunUsageRow,
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


async def test_usage_totals_equal_the_sum_of_the_logged_usage_events(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await create_run(sessions, spec("two-step-sequence.json"), "go")
    priced = Usage(
        model="claude-opus-5-5",
        input_tokens=1200,
        output_tokens=300,
        cache_read_tokens=5000,
        cache_write_tokens=700,
        estimated_usd=0.01234567,
    )
    runtime = FakeRuntime(
        {
            "writer": [Message(text="draft"), priced, priced],
            "reviewer": [Message(text="LGTM"), ECHO_USAGE],
        }
    )
    await run_workflow(
        spec("two-step-sequence.json"),
        runtime,
        "go",
        run_id=run_id,
        sink=PostgresEventSink(sessions),
    )

    logged = [e.agent_event() for e in await list_run_events(sessions, run_id) if e.type == "usage"]
    total = sum_usage(u for u in logged if isinstance(u, Usage))
    assert total is not None and total.estimated_usd is not None
    usage = (await summary(sessions, run_id)).usage
    assert usage == RunUsageRow(
        input_tokens=total.input_tokens,
        output_tokens=total.output_tokens,
        cache_read_tokens=total.cache_read_tokens,
        cache_write_tokens=total.cache_write_tokens,
        estimated_usd=Decimal("0.02479134"),
        cost_complete=True,
    )
    assert float(usage.estimated_usd) == total.estimated_usd


async def test_unpriced_usage_marks_the_cost_incomplete(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await create_run(sessions, spec("two-step-sequence.json"), "go")
    runtime = FakeRuntime(
        {
            "writer": [Message(text="draft"), ECHO_USAGE],
            "reviewer": [Message(text="LGTM"), Usage(input_tokens=7, output_tokens=1)],
        }
    )
    await run_workflow(
        spec("two-step-sequence.json"),
        runtime,
        "go",
        run_id=run_id,
        sink=PostgresEventSink(sessions),
    )

    usage = (await summary(sessions, run_id)).usage
    assert (usage.input_tokens, usage.output_tokens) == (17, 11)
    assert (usage.estimated_usd, usage.cost_complete) == (Decimal("0.0001"), False)


async def test_concurrent_usage_events_all_count(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Map items write usage at the same time; increments in SQL lose none of them."""
    run_id = await create_run(sessions, spec("two-step-sequence.json"), "go")
    sink = PostgresEventSink(sessions)
    payload = agent_event_adapter.dump_python(ECHO_USAGE, mode="json")
    events = [
        RunEvent(
            run_id=run_id,
            seq=seq,
            type="usage",
            node_id="describe",
            payload={**payload, "item": seq},
            created_at=datetime.now(UTC),
        )
        for seq in range(1, 21)
    ]

    await asyncio.gather(*(sink.emit(e) for e in events))

    usage = (await summary(sessions, run_id)).usage
    assert (usage.input_tokens, usage.estimated_usd) == (200, Decimal("0.002"))


async def test_an_unknown_run_has_no_summary(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    assert await get_run_summary(sessions, UUID(int=0)) is None


T0 = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)


async def emit_at(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID, *events: tuple[str, float]
) -> None:
    """Writes `(type, seconds after T0)` events in order, as the sink receives them."""
    sink = PostgresEventSink(sessions)
    seq = await max_event_seq(sessions, run_id)
    for type, seconds in events:
        seq += 1
        await sink.emit(
            RunEvent(
                run_id=run_id,
                seq=seq,
                type=type,
                node_id="gate" if type == "gate_waiting" else None,
                created_at=T0 + timedelta(seconds=seconds),
            )
        )


async def test_a_run_that_waited_an_hour_and_worked_two_minutes(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Done when (11.2): active and waiting time are kept apart."""
    run_id = await create_run(sessions, spec("two-step-sequence.json"), "go")
    await emit_at(
        sessions,
        run_id,
        ("run_started", 0),
        ("node_started", 30),
        ("gate_waiting", 60),
        ("run_resumed", 3660),
        ("gate_decided", 3661),
        ("run_completed", 3720),
    )

    times = (await summary(sessions, run_id)).times
    assert (times.active_ms, times.waiting_ms) == (120_000, 3_600_000)
    assert (times.active_since, times.waiting_since) == (None, None)


async def test_the_open_stretch_counts_up_to_now(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await create_run(sessions, spec("two-step-sequence.json"), "go")
    await emit_at(sessions, run_id, ("run_started", 0), ("gate_waiting", 60))

    times = (await summary(sessions, run_id)).times
    assert (times.active_ms, times.waiting_ms, times.waiting_since) == (
        60_000,
        0,
        T0 + timedelta(seconds=60),
    )
    assert times.at(T0 + timedelta(minutes=31)) == (60_000, 1_800_000)

    await emit_at(sessions, run_id, ("run_resumed", 120))
    times = (await summary(sessions, run_id)).times
    assert times.at(T0 + timedelta(seconds=130)) == (70_000, 60_000)


async def test_a_cut_off_attempt_counts_until_its_last_event(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The gap before the next attempt is neither active nor waiting."""
    run_id = await create_run(sessions, spec("two-step-sequence.json"), "go")
    await emit_at(
        sessions,
        run_id,
        ("run_started", 0),
        ("node_started", 10),  # the worker dies here
        ("run_resumed", 600),
        ("run_completed", 605),
    )

    times = (await summary(sessions, run_id)).times
    assert (times.active_ms, times.waiting_ms) == (15_000, 0)


async def test_a_run_cancelled_while_waiting_closes_its_wait(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await create_run(sessions, spec("two-step-sequence.json"), "go")
    await emit_at(sessions, run_id, ("run_started", 0), ("gate_waiting", 5), ("run_cancelled", 65))

    times = (await summary(sessions, run_id)).times
    assert (times.active_ms, times.waiting_ms) == (5_000, 60_000)


async def test_two_gates_add_up(sessions: async_sessionmaker[AsyncSession]) -> None:
    run_id = await create_run(sessions, spec("two-step-sequence.json"), "go")
    await emit_at(
        sessions,
        run_id,
        ("run_started", 0),
        ("gate_waiting", 10),
        ("run_resumed", 70),
        ("gate_waiting", 80),
        ("run_resumed", 200),
        ("run_completed", 210),
    )

    times = (await summary(sessions, run_id)).times
    assert (times.active_ms, times.waiting_ms) == (30_000, 180_000)


async def test_a_run_cancelled_before_it_started_has_no_active_time(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await create_run(sessions, spec("two-step-sequence.json"), "go")
    await emit_at(sessions, run_id, ("run_cancelled", 0))

    times = (await summary(sessions, run_id)).times
    assert (times.active_ms, times.waiting_ms) == (None, 0)
    assert times.at(T0) == (None, 0)
