import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pytest

from agentic_engine.agent import run_agent_node, to_request
from agentic_engine.spec import AgentNode, SequenceNode, parse_spec
from agentic_runtime import (
    AgentEvent,
    AgentRequest,
    Cancelled,
    ContractViolation,
    Failed,
    Message,
    TextDelta,
    ToolCall,
    ToolResult,
    Usage,
)
from agentic_runtime.fake import ECHO_USAGE, Delay, FakeRun, FakeRuntime

FIXTURES = Path(__file__).parent / "fixtures" / "specs" / "valid"

NODE = AgentNode(
    type="agent",
    id="writer",
    role="Technical writer",
    instructions="Draft the overview.",
    model="claude-sonnet-5-5",
    tools=["repo.read_file"],
)


def load_agent(fixture: str, index: int | None = None) -> AgentNode:
    spec = parse_spec(json.loads((FIXTURES / fixture).read_text(encoding="utf-8")))
    node = spec.root
    if index is not None:
        assert isinstance(node, SequenceNode)
        node = node.steps[index]
    assert isinstance(node, AgentNode)
    return node


async def test_runs_agent_node_from_spec_on_fake_runtime() -> None:
    node = load_agent("single-agent.json")
    runtime = FakeRuntime()

    result = await run_agent_node(node, runtime, "The README says hello.")

    assert result.status == "completed"
    assert result.text == "The README says hello."
    assert result.usage == ECHO_USAGE
    assert result.error is None
    assert runtime.requests == [to_request(node, "The README says hello.")]


def test_request_maps_the_node() -> None:
    assert to_request(NODE, "data") == AgentRequest(
        node_id="writer",
        role="Technical writer",
        instructions="Draft the overview.",
        input="data",
        model="claude-sonnet-5-5",
        tools=["repo.read_file"],
    )


async def test_runs_a_step_of_a_sequence_spec() -> None:
    node = load_agent("two-step-sequence.json", index=0)
    runtime = FakeRuntime({node.id: [Message(text="draft v1"), ECHO_USAGE]})
    result = await run_agent_node(node, runtime, "")
    assert (result.status, result.text) == ("completed", "draft v1")


async def test_tool_calls_surface_in_the_result() -> None:
    call = ToolCall(call_id="c1", name="repo.read_file", arguments={"path": "README.md"})
    runtime = FakeRuntime(
        {
            "writer": [
                call,
                ToolResult(call_id="c1", output="# Hello"),
                TextDelta(text="Done"),
                Usage(input_tokens=5, output_tokens=1, estimated_usd=0.01),
                Usage(input_tokens=7, output_tokens=2, estimated_usd=0.02),
            ]
        }
    )
    result = await run_agent_node(NODE, runtime, "")
    assert result.tool_calls == [call]
    assert result.text == "Done"
    assert result.usage == Usage(input_tokens=12, output_tokens=3, estimated_usd=0.03)


async def test_failure_is_a_status_not_an_exception() -> None:
    runtime = FakeRuntime({"writer": [Failed(error="rate limited", retryable=True)]})
    result = await run_agent_node(NODE, runtime, "")
    assert (result.status, result.error, result.usage) == ("failed", "rate limited", None)


async def test_cancelled_is_a_status_not_an_exception() -> None:
    runtime = FakeRuntime({"writer": [Message(text="partial"), Cancelled()]})
    result = await run_agent_node(NODE, runtime, "")
    assert (result.status, result.text) == ("cancelled", "partial")


class SpyRun:
    """Counts `cancel()` calls on a replayed script."""

    def __init__(self, steps: Sequence[AgentEvent | Delay]) -> None:
        self.inner = FakeRun(steps)  # unchecked, so tests can break the contract
        self.cancel_calls = 0

    def cancel(self) -> None:
        self.cancel_calls += 1
        self.inner.cancel()

    def __aiter__(self) -> AsyncIterator[AgentEvent]:
        return aiter(self.inner)


class SpyRuntime:
    def __init__(self, steps: Sequence[AgentEvent | Delay]) -> None:
        self.run = SpyRun(steps)

    def start(self, request: AgentRequest) -> SpyRun:
        return self.run


async def test_caller_cancellation_cancels_the_run() -> None:
    runtime = SpyRuntime([Message(text="a"), Delay(30), ECHO_USAGE])
    task = asyncio.create_task(run_agent_node(NODE, runtime, ""))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runtime.run.cancel_calls == 1


async def test_contract_violation_is_raised() -> None:
    runtime = SpyRuntime([Message(text="no terminal")])
    with pytest.raises(ContractViolation, match="terminal"):
        await run_agent_node(NODE, runtime, "")
    assert runtime.run.cancel_calls == 1
