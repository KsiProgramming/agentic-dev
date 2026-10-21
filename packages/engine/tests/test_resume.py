"""Resuming a run from its checkpoint after its worker was cut off (phase 1.3, AC-8)."""

import asyncio
import json
import logging
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agentic_engine.agent import AgentNodeResult
from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.graph import checkpoint_serde, resume_workflow, run_workflow
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import Completed, Failed, Message, ToolCall, Usage
from agentic_runtime.fake import ECHO_USAGE, Delay, FakeRuntime

SPEC = Path(__file__).parent / "fixtures" / "specs" / "valid" / "three-step-sequence.json"


def load() -> WorkflowSpec:
    return parse_spec(json.loads(SPEC.read_text(encoding="utf-8")))


def saver() -> InMemorySaver:
    return InMemorySaver(serde=checkpoint_serde())


class WatchingSink(InMemoryEventSink):
    """Records events and flags when `node_id` starts."""

    def __init__(self, node_id: str) -> None:
        super().__init__()
        self.node_id = node_id
        self.started = asyncio.Event()

    async def emit(self, event: RunEvent) -> None:
        await super().emit(event)
        if event.type == "node_started" and event.node_id == self.node_id:
            self.started.set()


async def crash_in(
    node_id: str, spec: WorkflowSpec, checkpointer: InMemorySaver
) -> tuple[UUID, FakeRuntime, WatchingSink]:
    """Start a run whose `node_id` hangs, and cut it off there, as a dying worker would."""
    run_id = uuid4()
    runtime = FakeRuntime({node_id: [Delay(60), ECHO_USAGE]})
    sink = WatchingSink(node_id)
    task = asyncio.create_task(
        run_workflow(spec, runtime, "go", run_id=run_id, sink=sink, checkpointer=checkpointer)
    )
    await asyncio.wait_for(sink.started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    return run_id, runtime, sink


async def test_resume_skips_completed_nodes() -> None:
    """Done when (1.3): a run cut off in `step-2` resumes after `step-1`, its last completed
    node."""
    spec, checkpointer = load(), saver()
    run_id, first, _ = await crash_in("step-2", spec, checkpointer)

    second = FakeRuntime(
        {"step-3": [Message(text="reviewed"), Usage(input_tokens=1, output_tokens=1)]}
    )
    result = await resume_workflow(
        spec,
        second,
        "go",
        run_id=run_id,
        sink=InMemoryEventSink(),
        checkpointer=checkpointer,
        next_seq=100,
        attempt=2,
    )

    assert [r.node_id for r in first.requests] == ["step-1", "step-2"]
    assert [r.node_id for r in second.requests] == ["step-2", "step-3"]
    assert second.requests[0].input == "go"  # step-1 echoed the input; its output was kept
    assert result.status == "completed"
    assert result.order == ["step-1", "step-2", "step-3"]
    assert result.text == "reviewed"


async def test_resume_events_continue_seq() -> None:
    spec, checkpointer = load(), saver()
    run_id, _, first = await crash_in("step-2", spec, checkpointer)
    next_seq = first.events[-1].seq + 1

    sink = InMemoryEventSink()
    await resume_workflow(
        spec,
        FakeRuntime(),
        "go",
        run_id=run_id,
        sink=sink,
        checkpointer=checkpointer,
        next_seq=next_seq,
        attempt=2,
    )

    resumed = sink.events[0]
    assert (resumed.seq, resumed.type) == (next_seq, "run_resumed")
    assert resumed.payload == {"attempt": 2, "completed_nodes": ["step-1"]}
    assert [e.seq for e in sink.events] == list(range(next_seq, next_seq + len(sink.events)))
    assert {e.run_id for e in sink.events} == {run_id}
    lifecycle = [(e.type, e.node_id) for e in sink.events if e.type.startswith(("node_", "run_"))]
    assert lifecycle == [
        ("run_resumed", None),
        ("node_started", "step-2"),
        ("node_completed", "step-2"),
        ("node_started", "step-3"),
        ("node_completed", "step-3"),
        ("run_completed", None),
    ]


async def test_resume_without_checkpoint_starts_fresh() -> None:
    """A run whose worker died before the graph saved anything runs every node from the input."""
    runtime = FakeRuntime()
    sink = InMemoryEventSink()

    result = await resume_workflow(
        load(),
        runtime,
        "go",
        run_id=uuid4(),
        sink=sink,
        checkpointer=saver(),
        next_seq=1,
        attempt=2,
    )

    assert sink.events[0].payload == {"attempt": 2, "completed_nodes": []}
    assert [r.node_id for r in runtime.requests] == ["step-1", "step-2", "step-3"]
    assert (result.status, result.text) == ("completed", "go")


async def test_resume_after_failed_node_keeps_failure() -> None:
    """A run whose graph had already ended (here on a failed node) is reported, not run again."""
    spec, checkpointer, run_id = load(), saver(), uuid4()
    await run_workflow(
        spec,
        FakeRuntime({"step-2": [Failed(error="boom")]}),
        "go",
        run_id=run_id,
        checkpointer=checkpointer,
    )

    runtime = FakeRuntime()
    sink = InMemoryEventSink()
    result = await resume_workflow(
        spec,
        runtime,
        "go",
        run_id=run_id,
        sink=sink,
        checkpointer=checkpointer,
        next_seq=50,
        attempt=2,
    )

    assert runtime.requests == []
    assert (result.status, result.stopped_at) == ("failed", "step-2")
    assert [(e.seq, e.type) for e in sink.events] == [(50, "run_resumed"), (51, "run_failed")]
    assert sink.events[0].payload == {"attempt": 2, "completed_nodes": ["step-1"]}
    assert sink.events[1].payload == {"stopped_at": "step-2"}


def test_checkpoint_round_trips_node_results(caplog: pytest.LogCaptureFixture) -> None:
    """`AgentNodeResult` is on the serializer's allow list, so LangGraph neither warns nor (in
    strict mode) refuses to load it."""
    result = AgentNodeResult(
        status="completed",
        text="hi",
        usage=Usage(input_tokens=1, output_tokens=2, estimated_usd=0.5),
        tool_calls=[ToolCall(call_id="c1", name="repo.read_file", arguments={"path": "a"})],
        events=[Message(text="hi"), Completed()],
    )
    serde = checkpoint_serde()

    with caplog.at_level(logging.WARNING):
        back = serde.loads_typed(serde.dumps_typed({"results": {"n": result}}))

    assert back == {"results": {"n": result}}
    assert "unregistered" not in caplog.text


async def test_run_workflow_without_checkpointer_unchanged() -> None:
    sink = InMemoryEventSink()

    result = await run_workflow(load(), FakeRuntime(), "go", sink=sink)

    assert result.status == "completed"
    assert [e.type for e in sink.events if e.type.startswith("run_")] == [
        "run_started",
        "run_completed",
    ]
