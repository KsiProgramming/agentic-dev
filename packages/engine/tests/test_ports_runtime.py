"""Typed ports at runtime (4.2): a wrong-shaped value fails at the edge with a clear error."""

import json
from typing import Any

from pydantic import JsonValue

from agentic_engine.agent import OUTPUT_SCHEMA_INSTRUCTION
from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.graph import run_workflow
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import Message, ToolOutput
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime
from agentic_runtime.testing import ScriptedToolExecutor

FINDINGS: dict[str, Any] = {
    "type": "object",
    "required": ["findings"],
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["severity"],
                "properties": {"severity": {"enum": ["low", "high"]}},
            },
        }
    },
}
MODULES: dict[str, Any] = {
    "type": "object",
    "required": ["modules"],
    "properties": {"modules": {"type": "array", "items": {"type": "string"}}},
}


def agent(node_id: str, **fields: Any) -> dict[str, Any]:
    return {"type": "agent", "id": node_id, "role": "R", "instructions": "Go.", **fields}


def spec(*steps: dict[str, Any]) -> WorkflowSpec:
    root = {"type": "sequence", "id": "main", "steps": list(steps)}
    return parse_spec({"spec_version": "0", "id": "wf", "name": "Workflow", "root": root})


def answers(**texts: str) -> FakeRuntime:
    """A runtime whose nodes answer the given texts; the others echo their input."""
    return FakeRuntime({node: [Message(text=text), ECHO_USAGE] for node, text in texts.items()})


def failed(events: list[RunEvent], node_id: str) -> RunEvent:
    return next(e for e in events if e.type == "node_failed" and e.node_id == node_id)


async def test_a_typed_output_becomes_data_and_the_next_input_is_its_json() -> None:
    runtime = answers(triage='Found one.\n```json\n{"findings": [{"severity": "high"}]}\n```')

    result = await run_workflow(
        spec(agent("triage", output_schema=FINDINGS), agent("report", input_schema=FINDINGS)),
        runtime,
        "src/app.py",
    )

    assert result.status == "completed"
    assert result.results["triage"].data == {"findings": [{"severity": "high"}]}
    expected = json.dumps({"findings": [{"severity": "high"}]}, indent=2)
    assert [r.input for r in runtime.requests] == ["src/app.py", expected]
    assert OUTPUT_SCHEMA_INSTRUCTION in runtime.requests[0].instructions
    assert json.dumps(FINDINGS) in runtime.requests[0].instructions
    assert OUTPUT_SCHEMA_INSTRUCTION not in runtime.requests[1].instructions


async def test_prose_instead_of_json_fails_the_producer_and_keeps_its_usage() -> None:
    sink = InMemoryEventSink()
    runtime = answers(triage="Everything looks fine.")

    result = await run_workflow(
        spec(agent("triage", output_schema=FINDINGS), agent("report")), runtime, sink=sink
    )

    assert (result.status, result.stopped_at) == ("failed", "triage")
    assert [r.node_id for r in runtime.requests] == ["triage"]
    assert result.results["triage"].usage == ECHO_USAGE
    assert failed(sink.events, "triage").payload == {
        "error": "output of 'triage' is not JSON: Expecting value: line 1 column 1",
        "port": {
            "side": "output",
            "node_id": "triage",
            "from_node_id": None,
            "errors": [{"pointer": "", "message": "not JSON: Expecting value: line 1 column 1"}],
        },
    }


async def test_a_wrong_shaped_output_fails_at_the_edge_with_its_pointer() -> None:
    sink = InMemoryEventSink()
    runtime = answers(triage='{"findings": [{"severity": "urgent"}]}')

    result = await run_workflow(
        spec(agent("triage", output_schema=FINDINGS), agent("report")), runtime, sink=sink
    )

    assert result.stopped_at == "triage"
    assert result.results["triage"].error == (
        "output of 'triage' does not match its output_schema at /findings/0/severity: "
        "'urgent' is not one of ['low', 'high']"
    )
    port = failed(sink.events, "triage").payload["port"]
    assert port == {
        "side": "output",
        "node_id": "triage",
        "from_node_id": None,
        "errors": [
            {"pointer": "/findings/0/severity", "message": "'urgent' is not one of ['low', 'high']"}
        ],
    }


async def test_a_wrong_shaped_input_fails_the_consumer_before_its_agent_starts() -> None:
    sink = InMemoryEventSink()
    runtime = FakeRuntime()

    result = await run_workflow(
        spec(agent("triage"), agent("report", input_schema=FINDINGS)),
        runtime,
        '{"issues": []}',
        sink=sink,
    )

    assert result.stopped_at == "report"
    assert [r.node_id for r in runtime.requests] == ["triage"]
    report = [(e.type, e.node_id) for e in sink.events if e.node_id == "report"]
    assert report == [("node_started", "report"), ("node_failed", "report")]
    assert failed(sink.events, "report").payload["error"] == (
        "input of 'report' (from 'triage') does not match its input_schema at the top level: "
        "'findings' is a required property"
    )


async def test_the_run_input_is_checked_by_the_first_step() -> None:
    runtime = FakeRuntime()

    result = await run_workflow(spec(agent("triage", input_schema=FINDINGS)), runtime, "hello")

    assert result.stopped_at == "triage"
    assert runtime.requests == []
    assert result.results["triage"].error == (
        "input of 'triage' is not JSON: Expecting value: line 1 column 1"
    )


async def test_a_tools_structured_result_is_checked_and_passed_on_as_json() -> None:
    modules: dict[str, JsonValue] = {"modules": ["api", "web"]}
    tools = ScriptedToolExecutor({"repo.list_modules": ToolOutput(text="2 modules", data=modules)})
    runtime = FakeRuntime()
    scan = {"type": "tool", "id": "scan", "tool": "repo.list_modules", "output_schema": MODULES}

    result = await run_workflow(
        spec(scan, agent("triage", input_schema=MODULES)), runtime, tools=tools
    )

    assert result.status == "completed"
    assert runtime.requests[0].input == json.dumps(modules, indent=2)


async def test_a_tool_result_of_the_wrong_shape_fails_the_tool_node() -> None:
    bad = ToolOutput(text="2 modules", data={"modules": "api, web"})
    tools = ScriptedToolExecutor({"repo.list_modules": bad})
    scan = {"type": "tool", "id": "scan", "tool": "repo.list_modules", "output_schema": MODULES}

    result = await run_workflow(spec(scan, agent("triage")), FakeRuntime(), tools=tools)

    assert result.stopped_at == "scan"
    assert result.results["scan"].error == (
        "output of 'scan' does not match its output_schema at /modules: "
        "'api, web' is not of type 'array'"
    )


async def test_cel_reads_a_typed_output_as_data() -> None:
    runtime = answers(triage='{"findings": [{"severity": "low"}, {"severity": "high"}]}')
    each = {
        "type": "map",
        "id": "each",
        "over": "results.triage.data.findings",
        "max_concurrency": 2,
        "body": agent("fix"),
    }

    result = await run_workflow(spec(agent("triage", output_schema=FINDINGS), each), runtime)

    assert result.status == "completed"
    assert sorted(r.input for r in runtime.requests if r.node_id == "fix") == [
        '{"severity": "high"}',
        '{"severity": "low"}',
    ]


async def test_a_map_item_of_the_wrong_shape_fails_its_item_and_the_map() -> None:
    sink = InMemoryEventSink()
    severity = {"type": "object", "required": ["severity"]}
    each = {
        "type": "map",
        "id": "each",
        "over": '[{"severity": "low"}, "urgent"]',
        "max_concurrency": 1,
        "body": agent("fix", input_schema=severity),
    }

    result = await run_workflow(spec(each), FakeRuntime(), sink=sink)

    assert result.stopped_at == "each"
    item = next(e for e in sink.events if e.type == "node_failed" and e.node_id == "fix")
    assert item.payload["item"] == 1
    assert item.payload["error"] == "input of 'fix' is not JSON: Expecting value: line 1 column 1"


async def test_a_branch_of_the_wrong_shape_fails_alone_under_join_any() -> None:
    other = {"type": "object", "required": ["other"]}
    review = {
        "type": "parallel",
        "id": "review",
        "join": "any",
        "branches": [agent("good", output_schema=FINDINGS), agent("bad", output_schema=other)],
    }

    result = await run_workflow(spec(review), FakeRuntime(), '{"findings": []}')

    assert result.status == "completed"
    assert result.results["good"].data == {"findings": []}
    assert result.results["bad"].status in {"failed", "cancelled"}


async def test_an_untyped_workflow_passes_text_unchanged() -> None:
    runtime = answers(triage="Not JSON at all.")

    result = await run_workflow(spec(agent("triage"), agent("report")), runtime)

    assert result.status == "completed"
    assert result.results["triage"].data is None
    assert runtime.requests[1].input == "Not JSON at all."
