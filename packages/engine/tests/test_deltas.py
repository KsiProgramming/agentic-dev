"""Streamed text is merged so the log gets at most one `text_delta` per interval, and a cancelled
run says why (phase 2.5)."""

import asyncio
from uuid import uuid4

import pytest

from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.graph import run_workflow
from agentic_engine.graph.deltas import DeltaBuffer
from agentic_engine.spec import parse_spec
from agentic_runtime import AgentEvent, Message, ReasoningDelta, TextDelta, Usage
from agentic_runtime.fake import ECHO_USAGE, Delay, FakeRuntime

CHUNKS = ["The ", "pages ", "are ", "clear", "."]


class Recorder:
    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    async def __call__(self, event: AgentEvent) -> None:
        self.events.append(event)

    def texts(self) -> list[str]:
        return [e.text for e in self.events if isinstance(e, TextDelta)]


async def test_chunks_in_a_burst_are_written_as_one_delta_after_the_first() -> None:
    out = Recorder()
    buffer = DeltaBuffer(out, interval=10)
    for chunk in CHUNKS:
        await buffer.emit(TextDelta(text=chunk))
    await buffer.emit(Message(text="The pages are clear."))

    assert out.texts() == ["The ", "pages are clear."]
    assert "".join(out.texts()) == "".join(CHUNKS)
    assert isinstance(out.events[-1], Message)


async def test_a_slow_stream_is_written_chunk_by_chunk() -> None:
    out = Recorder()
    buffer = DeltaBuffer(out, interval=0.01)
    for chunk in CHUNKS:
        await buffer.emit(TextDelta(text=chunk))
        await asyncio.sleep(0.03)
    await buffer.close()

    assert out.texts() == CHUNKS


async def test_pending_text_is_written_after_the_interval_with_no_other_event() -> None:
    out = Recorder()
    buffer = DeltaBuffer(out, interval=0.05)
    for chunk in CHUNKS:
        await buffer.emit(TextDelta(text=chunk))
    assert out.texts() == ["The "]

    await asyncio.sleep(0.1)

    assert out.texts() == ["The ", "pages are clear."]
    await buffer.close()
    assert out.texts() == ["The ", "pages are clear."]


async def test_any_other_event_writes_the_pending_text_first() -> None:
    out = Recorder()
    buffer = DeltaBuffer(out, interval=10)
    await buffer.emit(TextDelta(text="a"))
    await buffer.emit(TextDelta(text="b"))
    await buffer.emit(Usage(input_tokens=1, output_tokens=1))
    await buffer.emit(TextDelta(text="c"))
    await buffer.close()

    assert [type(e).__name__ for e in out.events] == [
        "TextDelta",
        "TextDelta",
        "Usage",
        "TextDelta",
    ]
    assert out.texts() == ["a", "b", "c"]


async def test_reasoning_is_merged_like_text_and_never_mixed_with_it() -> None:
    out = Recorder()
    buffer = DeltaBuffer(out, interval=10)
    for chunk in ["Read ", "the ", "config."]:
        await buffer.emit(ReasoningDelta(text=chunk))
    await buffer.emit(TextDelta(text="Done"))
    await buffer.emit(TextDelta(text="."))
    await buffer.emit(ReasoningDelta(text="Check."))
    await buffer.close()

    assert out.events == [
        ReasoningDelta(text="Read "),
        ReasoningDelta(text="the config."),
        TextDelta(text="Done."),
        ReasoningDelta(text="Check."),
    ]


async def test_close_writes_what_is_pending_and_stops_the_timer() -> None:
    out = Recorder()
    buffer = DeltaBuffer(out, interval=0.05)
    await buffer.emit(TextDelta(text="a"))
    await buffer.emit(TextDelta(text="b"))
    await buffer.close()
    await asyncio.sleep(0.1)

    assert out.texts() == ["a", "b"]


class DeltaSignal(InMemoryEventSink):
    """Sets `first_delta` once a `text_delta` is written."""

    def __init__(self) -> None:
        super().__init__()
        self.first_delta = asyncio.Event()

    async def emit(self, event: RunEvent) -> None:
        await super().emit(event)
        if event.type == "text_delta":
            self.first_delta.set()


def _deltas(events: list[RunEvent]) -> list[RunEvent]:
    return [e for e in events if e.type == "text_delta"]


async def test_a_run_logs_far_fewer_deltas_with_the_same_text_per_map_item() -> None:
    spec = parse_spec(
        {
            "spec_version": "0",
            "id": "deltas",
            "name": "Deltas",
            "root": {
                "type": "map",
                "id": "document",
                "over": '["a", "b"]',
                "body": {"type": "agent", "id": "writer", "role": "Writer", "instructions": "Go."},
                "max_concurrency": 2,
            },
        }
    )
    many = [TextDelta(text=f"w{i} ") for i in range(50)]
    text = "".join(d.text for d in many)
    runtime = FakeRuntime(
        {"writer": [*many, Message(text=text), Usage(input_tokens=1, output_tokens=1)]}
    )
    sink = InMemoryEventSink()

    await run_workflow(spec, runtime, run_id=uuid4(), sink=sink)

    deltas = _deltas(sink.events)
    assert len(deltas) <= 4  # 2 per item: the first chunk, then the rest
    for item in (0, 1):
        mine = [e for e in deltas if e.payload.get("item") == item]
        assert "".join(str(e.payload["text"]) for e in mine) == text
        # Each item's text is written before its message.
        message = next(
            e for e in sink.events if e.type == "message" and e.payload.get("item") == item
        )
        assert all(e.seq < message.seq for e in mine)


async def test_a_cancelled_node_writes_its_pending_text_before_node_cancelled() -> None:
    spec = parse_spec(
        {
            "spec_version": "0",
            "id": "cancel",
            "name": "Cancel",
            "root": {"type": "agent", "id": "writer", "role": "Writer", "instructions": "Go."},
        }
    )
    runtime = FakeRuntime(
        {
            "writer": [
                TextDelta(text="a"),
                TextDelta(text="b"),
                Delay(10),
                Message(text="ab"),
                ECHO_USAGE,
            ]
        }
    )
    sink = DeltaSignal()
    task = asyncio.create_task(run_workflow(spec, runtime, run_id=uuid4(), sink=sink))
    await sink.first_delta.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    types = [e.type for e in sink.events]
    assert "".join(str(e.payload["text"]) for e in _deltas(sink.events)) == "ab"
    assert types.index("node_cancelled") > max(i for i, t in enumerate(types) if t == "text_delta")
    assert types[-1] == "run_cancelled"


@pytest.mark.parametrize(
    ("message", "reason"),
    [(None, "caller cancelled"), ("cancelled by user", "cancelled by user")],
)
async def test_run_cancelled_says_why_the_caller_cancelled(
    message: str | None, reason: str
) -> None:
    spec = parse_spec(
        {
            "spec_version": "0",
            "id": "cancel",
            "name": "Cancel",
            "root": {"type": "agent", "id": "writer", "role": "Writer", "instructions": "Go."},
        }
    )
    runtime = FakeRuntime(
        {"writer": [TextDelta(text="a"), Delay(10), Message(text="a"), ECHO_USAGE]}
    )
    sink = DeltaSignal()
    task = asyncio.create_task(run_workflow(spec, runtime, run_id=uuid4(), sink=sink))
    await sink.first_delta.wait()

    task.cancel(message)
    with pytest.raises(asyncio.CancelledError):
        await task

    assert sink.events[-1].type == "run_cancelled"
    assert sink.events[-1].payload == {"reason": reason}
