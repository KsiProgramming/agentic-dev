"""The `tool` primitive: one platform tool call with fixed arguments, no model (phase 1.6)."""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.graph import checkpoint_serde, resume_workflow, run_workflow
from agentic_engine.graph.compile import step_nodes
from agentic_engine.spec import (
    AgentNode,
    SequenceNode,
    ToolNode,
    WorkflowSpec,
    node_tools,
    parse_spec,
    writer_node_ids,
)
from agentic_runtime import ToolOutput
from agentic_runtime.fake import ECHO_USAGE, Delay, FakeRuntime
from agentic_runtime.testing import ScriptedToolExecutor

FIXTURES = Path(__file__).parent / "fixtures" / "specs" / "valid"
LISTING = "README.md\nsrc/"


def load(name: str) -> WorkflowSpec:
    return parse_spec(json.loads((FIXTURES / name).read_text(encoding="utf-8")))


def listing_tools(output: str | ToolOutput | Exception = LISTING) -> ScriptedToolExecutor:
    return ScriptedToolExecutor({"repo.list_files": output})


def summary(events: list[RunEvent]) -> list[tuple[str, str | None]]:
    return [(e.type, e.node_id) for e in events]


def test_a_tool_node_is_a_step_in_run_order() -> None:
    spec = load("tool-node.json")

    steps = step_nodes(spec.root)

    assert [n.id for n in steps] == ["list", "summariser"]
    assert steps[0] == ToolNode(
        type="tool", id="list", tool="repo.list_files", args={"path": ".", "max_depth": 1}
    )


def test_the_spec_schema_has_the_tool_node() -> None:
    schema = WorkflowSpec.model_json_schema()

    assert schema["$defs"]["ToolNode"]["required"] == ["type", "id", "tool"]


def test_writers_are_the_nodes_naming_a_write_tool() -> None:
    write_tools = {"repo.write_file", "repo.commit"}
    root = SequenceNode(
        type="sequence",
        id="main",
        steps=[
            AgentNode(type="agent", id="reader", role="r", instructions="i", tools=["repo.search"]),
            AgentNode(
                type="agent", id="writer", role="w", instructions="i", tools=["repo.write_file"]
            ),
            ToolNode(type="tool", id="commit", tool="repo.commit", args={"message": "m"}),
        ],
    )

    assert writer_node_ids(root, write_tools) == {"writer", "commit"}
    assert node_tools(root) == []
    assert writer_node_ids(load("write-file.json").root, write_tools) == {"writer"}


async def test_the_output_is_logged_and_becomes_the_next_input() -> None:
    tools, runtime, sink = listing_tools(), FakeRuntime(), InMemoryEventSink()

    result = await run_workflow(load("tool-node.json"), runtime, "go", sink=sink, tools=tools)

    assert result.status == "completed"
    assert summary(sink.events)[:5] == [
        ("run_started", None),
        ("node_started", "list"),
        ("tool_call", "list"),
        ("tool_result", "list"),
        ("node_completed", "list"),
    ]
    call, output = sink.events[2].payload, sink.events[3].payload
    assert (call["name"], call["arguments"]) == ("repo.list_files", {"path": ".", "max_depth": 1})
    assert (output["output"], output["is_error"]) == (LISTING, False)
    assert tools.calls == [("repo.list_files", {"path": ".", "max_depth": 1})]
    assert tools.node_ids == ["list"]
    assert [r.input for r in runtime.requests] == [LISTING]  # data for the agent, not a prompt
    assert result.results["list"].usage is None


async def test_an_error_result_fails_the_run_at_the_tool_node() -> None:
    tools = listing_tools(ToolOutput(text="not a directory in the repository: x", is_error=True))
    runtime, sink = FakeRuntime(), InMemoryEventSink()

    result = await run_workflow(load("tool-node.json"), runtime, sink=sink, tools=tools)

    assert (result.status, result.stopped_at) == ("failed", "list")
    assert runtime.requests == []
    failed = next(e for e in sink.events if e.type == "node_failed")
    assert failed.payload == {"error": "not a directory in the repository: x"}
    assert sink.events[-1].type == "run_failed"
    assert sink.events[-1].payload == {"stopped_at": "list"}


async def test_a_raising_tool_fails_the_node_without_details() -> None:
    tools = listing_tools(RuntimeError("lost /var/secret"))

    result = await run_workflow(load("tool-node.json"), FakeRuntime(), tools=tools)

    assert result.results["list"].error == "tool failed: RuntimeError"


async def test_without_tools_a_tool_node_fails() -> None:
    result = await run_workflow(load("tool-node.json"), FakeRuntime())

    assert result.status == "failed"
    assert result.results["list"].error == "no tools are available to this run: repo.list_files"


async def test_resume_does_not_call_a_completed_tool_node_again() -> None:
    spec, checkpointer = load("tool-node.json"), InMemorySaver(serde=checkpoint_serde())
    run_id, first_tools = uuid4(), listing_tools()
    hanging = FakeRuntime({"summariser": [Delay(60), ECHO_USAGE]})
    started = asyncio.Event()

    class Watch(InMemoryEventSink):
        async def emit(self, event: RunEvent) -> None:
            await super().emit(event)
            if (event.type, event.node_id) == ("node_started", "summariser"):
                started.set()

    task = asyncio.create_task(
        run_workflow(
            spec, hanging, run_id=run_id, sink=Watch(), checkpointer=checkpointer, tools=first_tools
        )
    )
    await asyncio.wait_for(started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    second_tools, sink = listing_tools(), InMemoryEventSink()
    result = await resume_workflow(
        spec,
        FakeRuntime(),
        run_id=run_id,
        sink=sink,
        checkpointer=checkpointer,
        next_seq=50,
        attempt=2,
        tools=second_tools,
    )

    assert result.status == "completed"
    assert result.order == ["list", "summariser"]
    assert second_tools.calls == []
    assert sink.events[0].payload == {"attempt": 2, "completed_nodes": ["list"]}
