"""Run artifacts at runtime (4.3): nodes exchange `findings.json` through the run's artifacts,
whatever runs between them."""

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agentic_engine.artifacts import (
    MAX_ARTIFACT_BYTES,
    ArtifactError,
    InMemoryArtifactStore,
    artifact_content,
    media_type,
    write_artifact,
)
from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.gate import GateDecision
from agentic_engine.graph import checkpoint_serde, resume_workflow, run_workflow
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import Message, ToolOutput
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime, Step
from agentic_runtime.testing import ScriptedToolExecutor

FIXTURES = Path(__file__).parent / "fixtures" / "specs"
FINDINGS = {"findings": [{"id": "F1", "severity": "high"}]}
APPROVE = GateDecision(decision="approve", decided_by="ada")


def agent(node_id: str, **fields: Any) -> dict[str, Any]:
    return {"type": "agent", "id": node_id, "role": "R", "instructions": "Go.", **fields}


def spec(*steps: dict[str, Any]) -> WorkflowSpec:
    root = {"type": "sequence", "id": "main", "steps": list(steps)}
    return parse_spec({"spec_version": "0", "id": "wf", "name": "Workflow", "root": root})


def answers(**texts: str) -> FakeRuntime:
    """A runtime whose nodes answer the given texts; the others echo their input."""
    return FakeRuntime({node: [Message(text=text), ECHO_USAGE] for node, text in texts.items()})


def of_type(events: list[RunEvent], type: str, node_id: str | None = None) -> list[RunEvent]:
    return [e for e in events if e.type == type and (node_id is None or e.node_id == node_id)]


def inputs(runtime: FakeRuntime) -> dict[str, str]:
    return {r.node_id: r.input for r in runtime.requests}


async def test_the_fixture_exchanges_findings_across_a_step_and_a_gate() -> None:
    raw = json.loads((FIXTURES / "valid" / "artifacts-findings.json").read_text(encoding="utf-8"))
    workflow = parse_spec(raw)
    runtime = answers(summary="All good.", report="# Report\n\nOne high finding.")
    store, sink, run_id = InMemoryArtifactStore(), InMemoryEventSink(), uuid4()
    saver = InMemorySaver(serde=checkpoint_serde())

    paused = await run_workflow(
        workflow,
        runtime,
        json.dumps(FINDINGS),
        run_id=run_id,
        sink=sink,
        checkpointer=saver,
        artifacts=store,
    )

    assert paused.status == "waiting"
    [waiting] = of_type(sink.events, "gate_waiting")
    assert waiting.payload["run_artifacts"] == [
        {
            "name": "findings.json",
            "version": 1,
            "node_id": "scan",
            "media_type": "application/json",
            "size": len(json.dumps(FINDINGS, indent=2).encode()),
        }
    ]

    done = await resume_workflow(
        workflow,
        runtime,
        run_id=run_id,
        sink=sink,
        checkpointer=saver,
        next_seq=sink.events[-1].seq + 1,
        attempt=2,
        decision=APPROVE,
        artifacts=store,
    )

    assert done.status == "completed"
    assert inputs(runtime)["summary"] == json.dumps(FINDINGS, indent=2)
    assert inputs(runtime)["report"] == json.dumps(FINDINGS, indent=2)
    [started] = of_type(sink.events, "node_started", "report")
    assert started.payload == {"reads": [{"name": "findings.json", "version": 1}]}
    written = [
        (e.node_id, e.payload["name"], e.payload["version"])
        for e in sink.events
        if e.type == "artifact_written"
    ]
    assert written == [("scan", "findings.json", 1), ("report", "report.md", 1)]
    report = await store.get("report.md")
    assert report is not None and report.content == "# Report\n\nOne high finding."
    assert report.media_type == "text/markdown"
    assert set(done.artifacts) == {"findings.json", "report.md"}


async def test_artifact_written_comes_before_the_writers_end() -> None:
    sink = InMemoryEventSink()

    await run_workflow(spec(agent("a", writes="notes.txt")), answers(a="hi"), sink=sink)

    types = [e.type for e in sink.events if e.node_id == "a"]
    assert types[-2:] == ["artifact_written", "node_completed"]


async def test_several_reads_are_an_object_by_name() -> None:
    runtime = answers(a='{"n": 1}', b="some notes")

    result = await run_workflow(
        spec(
            agent("a", writes="a.json"),
            agent("b", writes="b.md"),
            agent("both", reads=["a.json", "b.md"]),
        ),
        runtime,
    )

    assert result.status == "completed"
    assert json.loads(inputs(runtime)["both"]) == {"a.json": {"n": 1}, "b.md": "some notes"}


async def test_a_loop_writes_a_new_version_each_iteration_and_until_reads_it() -> None:
    sink = InMemoryEventSink()
    store = InMemoryArtifactStore()
    loop = {
        "type": "loop",
        "id": "refine",
        "until": "artifacts['count.json'].n >= 2",
        "max_iterations": 5,
        "body": agent("count", writes="count.json"),
    }

    def count(text: str) -> list[Step]:
        """One more than the previous iteration's count."""
        n = json.loads(text)["n"] + 1 if text.startswith("{") else 1
        return [Message(text=json.dumps({"n": n})), ECHO_USAGE]

    runtime = FakeRuntime(default=count)

    result = await run_workflow(spec(loop), runtime, "x", sink=sink, artifacts=store)

    assert result.status == "completed"
    assert result.results["refine"].data == {"stop_reason": "condition", "iterations": 2}
    assert [a.version for a in store.versions["count.json"]] == [1, 2]
    assert result.artifacts["count.json"].version == 2


async def test_a_read_of_an_artifact_no_branch_wrote_fails_the_reader_before_it_runs() -> None:
    sink = InMemoryEventSink()
    parallel = {
        "type": "parallel",
        "id": "review",
        "join": "any",
        "branches": [agent("good"), agent("bad", writes="bad.json")],
    }
    runtime = answers(bad="not json")

    result = await run_workflow(
        spec(parallel, agent("report", reads=["bad.json"])), runtime, sink=sink
    )

    assert result.status == "failed"
    assert result.stopped_at == "report"
    assert result.results["report"].error == "artifact 'bad.json' was not written"
    assert "report" not in inputs(runtime)
    assert of_type(sink.events, "node_started", "report")[0].payload == {"reads": []}


async def test_a_json_artifact_that_is_not_json_fails_its_writer() -> None:
    sink = InMemoryEventSink()

    result = await run_workflow(
        spec(agent("scan", writes="findings.json")), answers(scan="Nothing found."), sink=sink
    )

    assert result.status == "failed"
    error = result.results["scan"].error
    assert error is not None
    assert error.startswith("cannot write 'findings.json': output of 'scan' is not JSON")
    assert of_type(sink.events, "artifact_written") == []
    assert of_type(sink.events, "node_failed", "scan")[0].payload["error"] == error
    # Its usage still counts.
    assert result.usage is not None


async def test_a_fenced_json_answer_is_stored_as_pretty_json() -> None:
    store = InMemoryArtifactStore()

    await run_workflow(
        spec(agent("scan", writes="findings.json")),
        answers(scan='Here:\n```json\n{"findings": []}\n```'),
        artifacts=store,
    )

    stored = await store.get("findings.json")
    assert stored is not None and stored.content == '{\n  "findings": []\n}'


async def test_a_typed_writer_feeds_a_typed_reader_and_a_wrong_shape_fails_at_the_edge() -> None:
    schema: dict[str, Any] = {
        "type": "object",
        "required": ["findings"],
        "properties": {"findings": {}},
    }
    wants_issues: dict[str, Any] = {
        "type": "object",
        "required": ["issues"],
        "properties": {"issues": {}},
    }

    ok = await run_workflow(
        spec(
            agent("scan", writes="f.json", output_schema=schema),
            agent("other"),
            agent("report", reads=["f.json"], input_schema=schema),
        ),
        answers(scan='{"findings": []}', other="unrelated"),
    )
    sink = InMemoryEventSink()
    bad = await run_workflow(
        spec(
            agent("scan", writes="f.json"),
            agent("report", reads=["f.json"], input_schema=wants_issues),
        ),
        answers(scan='{"findings": []}'),
        sink=sink,
    )

    assert ok.status == "completed"
    assert bad.status == "failed"
    port = of_type(sink.events, "node_failed", "report")[0].payload["port"]
    assert isinstance(port, dict) and port["from_node_id"] == "scan"


async def test_a_tool_nodes_data_is_written_and_a_tool_node_reads() -> None:
    tools = ScriptedToolExecutor(
        {
            "repo.list_modules": ToolOutput(text="2 modules", data={"modules": ["api", "web"]}),
            "repo.list_files": "README.md",
        }
    )
    store = InMemoryArtifactStore()

    result = await run_workflow(
        spec(
            {"type": "tool", "id": "scan", "tool": "repo.list_modules", "writes": "modules.json"},
            {"type": "tool", "id": "list", "tool": "repo.list_files", "reads": ["modules.json"]},
        ),
        FakeRuntime(),
        tools=tools,
        artifacts=store,
    )

    assert result.status == "completed"
    stored = await store.get("modules.json")
    assert stored is not None and json.loads(stored.content) == {"modules": ["api", "web"]}


async def test_a_branch_reads_what_its_earlier_step_wrote_and_the_run_sees_it_after() -> None:
    branch = {
        "type": "sequence",
        "id": "checks",
        "steps": [agent("lint", writes="lint.json"), agent("fix", reads=["lint.json"])],
    }
    parallel = {"type": "parallel", "id": "review", "join": "all", "branches": [branch, agent("x")]}
    runtime = answers(lint='{"errors": 0}')

    result = await run_workflow(spec(parallel, agent("report", reads=["lint.json"])), runtime, "go")

    assert result.status == "completed"
    assert json.loads(inputs(runtime)["fix"]) == {"errors": 0}
    assert json.loads(inputs(runtime)["report"]) == {"errors": 0}


async def test_a_map_item_reads_the_runs_artifact() -> None:
    map_node = {
        "type": "map",
        "id": "each",
        "over": "artifacts['plan.json'].modules",
        "max_concurrency": 2,
        "body": agent("worker", reads=["plan.json"]),
    }
    runtime = answers(plan='{"modules": ["api", "web"]}')

    result = await run_workflow(spec(agent("plan", writes="plan.json"), map_node), runtime)

    assert result.status == "completed"
    worker_inputs = [r.input for r in runtime.requests if r.node_id == "worker"]
    assert [json.loads(i) for i in worker_inputs] == [{"modules": ["api", "web"]}] * 2
    assert result.results["each"].data is not None
    assert result.results["each"].data["items"] == ["api", "web"]


async def test_a_reduce_writes_its_output() -> None:
    map_node = {
        "type": "map",
        "id": "each",
        "over": "['a', 'b']",
        "max_concurrency": 2,
        "body": agent("worker"),
    }
    reduce = {
        "type": "reduce",
        "id": "join",
        "from": "each",
        "strategy": "concat",
        "writes": "all.md",
    }
    store = InMemoryArtifactStore()

    result = await run_workflow(spec(map_node, reduce), FakeRuntime(), artifacts=store)

    assert result.status == "completed"
    stored = await store.get("all.md")
    assert stored is not None and stored.content == "a\n\nb"


async def test_artifacts_over_the_size_limits_fail_their_writer() -> None:
    big = "x" * (MAX_ARTIFACT_BYTES + 1)

    with pytest.raises(
        ArtifactError, match=r"cannot write 'big.txt': 1\.00 MB is over the 1 MB limit"
    ):
        artifact_content("big.txt", "a", big, None)

    store = InMemoryArtifactStore()
    for i in range(8):
        await store.put(f"f{i}.txt", "a", "x" * MAX_ARTIFACT_BYTES)
    with pytest.raises(
        ArtifactError, match=r"the run's artifacts would take 8\.00 MB, over the 8 MB limit"
    ):
        await write_artifact(store, "last.txt", "a", "x")


def test_the_extension_gives_the_media_type() -> None:
    assert [media_type(n) for n in ("a.json", "a.md", "a.txt")] == [
        "application/json",
        "text/markdown",
        "text/plain",
    ]


async def test_a_spec_without_artifacts_runs_as_before() -> None:
    sink = InMemoryEventSink()

    result = await run_workflow(spec(agent("a"), agent("b")), answers(a="hi"), "go", sink=sink)

    assert result.status == "completed"
    assert result.artifacts == {}
    assert of_type(sink.events, "artifact_written") == []
    assert of_type(sink.events, "node_started", "b")[0].payload == {}
