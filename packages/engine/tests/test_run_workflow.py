import asyncio
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentic_engine.graph import run_workflow
from agentic_engine.spec import AgentNode, SequenceNode, WorkflowSpec, parse_spec
from agentic_runtime import AgentEvent, AgentRequest, Cancelled, Failed, Message, Usage
from agentic_runtime.fake import ECHO_USAGE, Delay, FakeRun, FakeRuntime

FIXTURES = Path(__file__).parent / "fixtures" / "specs" / "valid"


def load(name: str) -> WorkflowSpec:
    return parse_spec(json.loads((FIXTURES / name).read_text(encoding="utf-8")))


async def test_two_step_sequence_runs_on_fake_runtime() -> None:
    """Done when (0.4): a 2-node sequence runs end to end on the fake runtime."""
    spec = load("two-step-sequence.json")
    runtime = FakeRuntime(
        {
            "writer": [Message(text="draft"), Usage(input_tokens=3, output_tokens=5)],
            "reviewer": [Message(text="LGTM"), Usage(input_tokens=7, output_tokens=1)],
        }
    )

    result = await run_workflow(spec, runtime, "Write the overview.")

    assert result.status == "completed"
    assert result.order == ["writer", "reviewer"]
    assert result.text == "LGTM"
    assert result.stopped_at is None
    writer, reviewer = runtime.requests
    assert writer.input == "Write the overview."
    assert reviewer.input == "draft"
    assert isinstance(spec.root, SequenceNode)
    reviewer_node = spec.root.steps[1]
    assert isinstance(reviewer_node, AgentNode)
    assert reviewer.instructions == reviewer_node.instructions
    assert result.usage == Usage(input_tokens=10, output_tokens=6)
    assert {n: r.status for n, r in result.results.items()} == {
        "writer": "completed",
        "reviewer": "completed",
    }


async def test_nested_sequence_passes_output_down_the_chain() -> None:
    runtime = FakeRuntime(
        {
            "planner": [Message(text="plan"), ECHO_USAGE],
            "implementer": [Message(text="code"), ECHO_USAGE],
        }
    )

    result = await run_workflow(load("nested-sequence.json"), runtime, "task")

    assert result.order == ["planner", "implementer", "tester"]
    assert [r.input for r in runtime.requests] == ["task", "plan", "code"]
    assert result.text == "code"  # the tester echoes its input
    assert result.usage == Usage(
        model="fake", input_tokens=30, output_tokens=30, estimated_usd=0.0003
    )


async def test_single_agent_root_runs_one_node() -> None:
    spec = load("single-agent.json")
    runtime = FakeRuntime()

    result = await run_workflow(spec, runtime, "hello")

    assert (result.status, result.order, result.text) == ("completed", [spec.root.id], "hello")


async def test_failed_node_stops_the_run() -> None:
    runtime = FakeRuntime({"writer": [Failed(error="boom")]})

    result = await run_workflow(load("two-step-sequence.json"), runtime, "go")

    assert (result.status, result.stopped_at, result.order) == ("failed", "writer", ["writer"])
    assert result.results["writer"].error == "boom"
    assert [r.node_id for r in runtime.requests] == ["writer"]


async def test_cancelled_node_stops_the_run() -> None:
    runtime = FakeRuntime({"writer": [Cancelled()]})

    result = await run_workflow(load("two-step-sequence.json"), runtime, "go")

    assert (result.status, result.stopped_at) == ("cancelled", "writer")
    assert [r.node_id for r in runtime.requests] == ["writer"]


class SpyRun:
    def __init__(self, inner: FakeRun) -> None:
        self.inner = inner
        self.cancel_calls = 0

    def cancel(self) -> None:
        self.cancel_calls += 1
        self.inner.cancel()

    def __aiter__(self) -> AsyncIterator[AgentEvent]:
        return aiter(self.inner)


class SpyRuntime:
    """Wraps `FakeRuntime` and keeps each started run so tests can see it was cancelled."""

    def __init__(self, fake: FakeRuntime) -> None:
        self.fake = fake
        self.runs: dict[str, SpyRun] = {}

    def start(self, request: AgentRequest) -> SpyRun:
        run = SpyRun(self.fake.start(request))
        self.runs[request.node_id] = run
        return run


async def test_caller_cancellation_cancels_the_in_flight_node() -> None:
    runtime = SpyRuntime(FakeRuntime({"writer": [Message(text="a"), Delay(30), ECHO_USAGE]}))
    task = asyncio.create_task(run_workflow(load("two-step-sequence.json"), runtime, "go"))
    await asyncio.sleep(0.05)

    started = time.monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert time.monotonic() - started < 0.1
    assert runtime.runs["writer"].cancel_calls == 1
    assert "reviewer" not in runtime.runs
