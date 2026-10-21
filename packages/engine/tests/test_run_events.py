import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest

from agentic_engine.events import InMemoryEventSink
from agentic_engine.graph import run_workflow
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import Failed, Message, TextDelta, Usage
from agentic_runtime.fake import ECHO_USAGE, Delay, FakeRuntime

SPEC = Path(__file__).parent / "fixtures" / "specs" / "valid" / "two-step-sequence.json"


def two_step() -> WorkflowSpec:
    return parse_spec(json.loads(SPEC.read_text(encoding="utf-8")))


async def test_two_step_sequence_emits_ordered_events() -> None:
    sink = InMemoryEventSink()
    run_id = uuid4()
    runtime = FakeRuntime(
        {
            "writer": [TextDelta(text="dr"), Message(text="draft"), ECHO_USAGE],
            "reviewer": [Message(text="LGTM"), Usage(input_tokens=7, output_tokens=1)],
        }
    )

    result = await run_workflow(two_step(), runtime, "go", run_id=run_id, sink=sink)

    assert result.run_id == run_id
    assert [e.seq for e in sink.events] == list(range(1, len(sink.events) + 1))
    assert {e.run_id for e in sink.events} == {run_id}
    assert [(e.type, e.node_id) for e in sink.events] == [
        ("run_started", None),
        ("node_started", "writer"),
        ("text_delta", "writer"),
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
    assert sink.events[0].payload["input"] == "go"
    writer_events = [e.agent_event() for e in sink.events[2:6]]
    assert writer_events == result.results["writer"].events


async def test_failed_node_ends_with_run_failed() -> None:
    sink = InMemoryEventSink()
    runtime = FakeRuntime({"writer": [Failed(error="boom")]})

    await run_workflow(two_step(), runtime, "go", sink=sink)

    assert [e.type for e in sink.events][-3:] == ["failed", "node_failed", "run_failed"]
    assert sink.events[-2].payload == {"error": "boom"}
    assert sink.events[-1].payload == {"stopped_at": "writer"}


async def test_caller_cancellation_ends_with_run_cancelled() -> None:
    sink = InMemoryEventSink()
    runtime = FakeRuntime({"writer": [Message(text="a"), Delay(30), ECHO_USAGE]})
    task = asyncio.create_task(run_workflow(two_step(), runtime, "go", sink=sink))
    await asyncio.sleep(0.05)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert [e.type for e in sink.events][-2:] == ["node_cancelled", "run_cancelled"]
    assert [e.seq for e in sink.events] == list(range(1, len(sink.events) + 1))
