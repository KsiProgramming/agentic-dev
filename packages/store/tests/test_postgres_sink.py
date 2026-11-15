import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.events import RUN_FAILED, RUN_STARTED, RunEventLog
from agentic_engine.graph import run_workflow
from agentic_engine.spec import parse_spec
from agentic_runtime import Failed, Message, Usage
from agentic_runtime.fake import FakeRuntime
from agentic_store import (
    RUN_EVENTS_CHANNEL,
    PostgresEventSink,
    Run,
    create_run,
    get_run,
    list_run_events,
    listen,
)

pytestmark = pytest.mark.integration

SPEC = (
    Path(__file__).resolve().parents[2]
    / "engine"
    / "tests"
    / "fixtures"
    / "specs"
    / "valid"
    / "two-step-sequence.json"
)


def two_step_spec():
    return parse_spec(json.loads(SPEC.read_text(encoding="utf-8")))


async def test_two_step_run_writes_ordered_events_to_postgres(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Done when (0.5): a run produces ordered events in Postgres."""
    run_id = await create_run(sessions, two_step_spec(), "go")
    runtime = FakeRuntime(
        {
            "writer": [Message(text="draft"), Usage(input_tokens=3, output_tokens=5)],
            "reviewer": [Message(text="LGTM"), Usage(input_tokens=7, output_tokens=1)],
        }
    )

    result = await run_workflow(
        two_step_spec(), runtime, "go", run_id=run_id, sink=PostgresEventSink(sessions)
    )
    events = await list_run_events(sessions, run_id)

    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    assert [(e.type, e.node_id) for e in events] == [
        ("run_started", None),
        ("node_started", "writer"),
        ("message", "writer"),
        ("usage", "writer"),
        ("completed", "writer"),
        ("node_completed", "writer"),
        ("node_started", "reviewer"),
        ("message", "reviewer"),
        ("usage", "reviewer"),
        ("completed", "reviewer"),
        ("node_completed", "reviewer"),
        ("run_completed", None),
    ]
    for node_id in ("writer", "reviewer"):
        stored = [
            e.agent_event()
            for e in events
            if e.node_id == node_id and not e.type.startswith(("node_", "run_"))
        ]
        assert stored == result.results[node_id].events
    async with sessions() as session:
        run = await session.get(Run, run_id)
    assert run is not None
    assert run.status == "completed"


async def test_failed_run_sets_status_failed(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await create_run(sessions, two_step_spec(), "go")
    runtime = FakeRuntime({"writer": [Failed(error="boom")]})

    await run_workflow(
        two_step_spec(), runtime, "go", run_id=run_id, sink=PostgresEventSink(sessions)
    )

    events = await list_run_events(sessions, run_id)
    assert events[-1].type == "run_failed"
    assert [e.type for e in await list_run_events(sessions, run_id, after_seq=len(events) - 1)] == [
        "run_failed"
    ]
    async with sessions() as session:
        run = await session.get(Run, run_id)
    assert run is not None
    assert run.status == "failed"


async def test_an_end_event_says_until_when_the_sandbox_is_kept(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """12.3: the worker adds `sandbox_kept_until` to a failed or cancelled run's end event, and
    the run gets it with its end status, in one transaction."""
    run_id = await create_run(sessions, two_step_spec(), "go")
    until = datetime(2026, 11, 16, 9, 30, tzinfo=UTC)
    log = RunEventLog(run_id, PostgresEventSink(sessions))
    await log.emit(RUN_STARTED)
    await log.emit(RUN_FAILED, payload={"error": "boom", "sandbox_kept_until": until.isoformat()})

    async with sessions() as session:
        run = await session.get(Run, run_id)
    assert run is not None
    assert (run.status, run.sandbox_kept_until, run.sandbox_removed_at) == ("failed", until, None)


async def test_create_run_stores_spec_and_input_as_queued(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    spec = two_step_spec()

    run_id = await create_run(sessions, spec, "hello")
    run = await get_run(sessions, run_id)

    assert run is not None
    assert (run.status, run.spec, run.input) == ("queued", spec, "hello")
    assert await list_run_events(sessions, run_id) == []


async def test_sink_notifies_each_event_on_commit(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str
) -> None:
    run_id = await create_run(sessions, two_step_spec(), "go")
    notifications: asyncio.Queue[str] = asyncio.Queue()
    async with listen(postgres_url, RUN_EVENTS_CHANNEL, notifications.put_nowait):
        await run_workflow(
            two_step_spec(), FakeRuntime(), "go", run_id=run_id, sink=PostgresEventSink(sessions)
        )
        count = len(await list_run_events(sessions, run_id))
        received = [await asyncio.wait_for(notifications.get(), 5) for _ in range(count)]

    assert received == [f"{run_id}:{seq}" for seq in range(1, count + 1)]
