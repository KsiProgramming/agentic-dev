"""The `subflow` primitive (6.5): one workflow calls another stored workflow by id and version.
The called workflow is resolved before the run, checked as part of the caller, and runs inside
the caller's run."""

import asyncio
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import JsonValue

from agentic_engine.artifacts import InMemoryArtifactStore
from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.gate import GateDecision
from agentic_engine.graph import WorkflowRunResult, checkpoint_serde, resume_workflow, run_workflow
from agentic_engine.graph.compile import CompileError, compile_workflow, recursion_limit
from agentic_engine.policy import PLATFORM_POLICY, Policy
from agentic_engine.spec import (
    SubflowNode,
    ValidationIssue,
    WorkflowSpec,
    agents_spawned,
    call_documents,
    expand_workflow,
    iter_nodes,
    parse_spec,
    resolve_from,
    subflow_key,
    subflow_refs,
    validate_workflow,
    writer_node_ids,
)
from agentic_runtime import AgentRequest, AgentRun, Message, ToolDefinition, ToolOutput
from agentic_runtime.fake import ECHO_USAGE, CallTool, FakeRuntime

type Doc = dict[str, Any]


def agent(id: str, **fields: Any) -> Doc:
    return {"type": "agent", "id": id, "role": "R", "instructions": "Go.", **fields}


def gate(id: str) -> Doc:
    return {"type": "gate", "id": id, "title": f"Approve {id}"}


def subflow(id: str, workflow: str, version: int = 1, **fields: Any) -> Doc:
    return {"type": "subflow", "id": id, "workflow": {"id": workflow, "version": version}, **fields}


def workflow(id: str, *steps: Doc, name: str | None = None) -> Doc:
    root = {"type": "sequence", "id": f"{id}_main", "steps": list(steps)}
    return {"spec_version": "0", "id": id, "name": name or id.title(), "root": root}


def library(*documents: Doc, version: int = 1) -> dict[str, Any]:
    """The stored workflows a resolver knows, each at `version`."""
    return {subflow_key(d["id"], version): d for d in documents}


CHILD = workflow("child", agent("x"), agent("y"), name="Child flow")


def validate(
    raw: Doc, known: Mapping[str, Any] | None = None, policy: Policy = PLATFORM_POLICY
) -> list[ValidationIssue]:
    return validate_workflow(
        raw,
        policy=policy,
        priced=lambda _: True,
        default_model="m",
        resolve=resolve_from(dict(known if known is not None else library(CHILD))),
    )


def where(issues: list[ValidationIssue]) -> list[tuple[str, str, str | None]]:
    return [(i.code, i.path, i.node_id) for i in issues]


def expanded(raw: Doc, known: Mapping[str, Any] | None = None) -> WorkflowSpec:
    found = expand_workflow(parse_spec(raw), resolve_from(dict(known or library(CHILD))))
    assert found.issues == []
    return found.spec


# --- The spec -------------------------------------------------------------------------------


def test_a_subflow_names_a_workflow_and_a_version() -> None:
    spec = parse_spec(workflow("parent", agent("a"), subflow("call", "child", 3)))
    [call] = [n for _, n in iter_nodes(spec.root) if isinstance(n, SubflowNode)]
    assert (call.workflow.id, call.workflow.version, call.call) == ("child", 3, None)
    # The called root is never part of the spec as written.
    dumped = spec.model_dump(mode="json")
    assert dumped["root"]["steps"][1] == subflow("call", "child", 3, input=None)


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "subflow", "id": "call", "workflow": {"id": "child"}},
        subflow("call", "child", 0),
        subflow("call", "Child!"),
        {**subflow("call", "child"), "call": agent("x")},
    ],
    ids=["no-version", "version-0", "bad-id", "call-sent"],
)
def test_a_malformed_subflow_is_a_schema_issue(bad: Doc) -> None:
    assert {i.code for i in validate(workflow("parent", bad))} == {"schema"}


def test_subflow_refs_reads_every_call_of_a_document() -> None:
    raw = workflow(
        "parent",
        subflow("one", "child", 2),
        {"type": "parallel", "id": "p", "join": "all", "branches": [subflow("two", "other")]},
    )
    assert sorted(subflow_refs(raw)) == [("child", 2), ("other", 1)]


# --- Validation ------------------------------------------------------------------------------


def test_a_known_call_has_no_issues() -> None:
    assert validate(workflow("parent", agent("a"), subflow("call", "child"), agent("b"))) == []


def test_an_unknown_workflow_or_version_is_subflow_unknown() -> None:
    issues = validate(workflow("parent", subflow("call", "nope"), subflow("old", "child", 7)))
    assert where(issues) == [
        ("subflow_unknown", "root.steps[0].workflow", "call"),
        ("subflow_unknown", "root.steps[1].workflow", "old"),
    ]
    assert issues[1].message == (
        "subflow 'old' at root.steps[1]: the workspace has no workflow 'child' version 7"
    )


def test_a_workflow_may_not_call_itself() -> None:
    issues = validate(workflow("child", agent("a"), subflow("again", "child")))
    assert where(issues) == [("subflow_cycle", "root.steps[1].workflow", "again")]


def test_a_cycle_through_another_workflow_is_refused_on_the_outer_call() -> None:
    a = workflow("a", subflow("to_b", "b"))
    b = workflow("b", subflow("to_a", "a"))
    issues = validate(workflow("parent", subflow("call", "a")), library(a, b))
    assert where(issues) == [("subflow_cycle", "root.steps[0]", "call")]
    assert "'a' → 'b' → 'a'" in issues[0].message
    assert issues[0].message.startswith(
        "subflow 'call' at root.steps[0]: in workflow 'a' version 1"
    )


def test_calls_nest_only_as_deep_as_max_depth() -> None:
    one = workflow("one", subflow("to_two", "two"))
    two = workflow("two", subflow("to_three", "three"))
    three = workflow("three", agent("deep"))
    known = library(one, two, three)

    assert validate(workflow("parent", subflow("call", "two")), known) == []
    issues = validate(workflow("parent", subflow("call", "one")), known)
    assert [(i.code, i.limit, i.node_id) for i in issues] == [("policy_limit", "max_depth", "call")]


def test_a_called_node_whose_id_the_run_has_runs_under_the_calls_name() -> None:
    """A workflow written alone cannot know its callers' ids, and every blank workflow starts
    with the same ones: a clash is renamed `<subflow>-<id>`, never refused."""
    raw = workflow("parent", agent("x"), subflow("call", "child"))
    assert validate(raw) == []

    spec = expanded(raw)
    [call] = [n for _, n in iter_nodes(spec.root) if isinstance(n, SubflowNode)]
    assert call.ids == {"child_main": "child_main", "x": "call-x", "y": "y"}
    assert call.call is not None
    assert [n.id for _, n in iter_nodes(call.call)] == ["child_main", "call-x", "y"]


def test_two_calls_of_one_workflow_each_get_their_own_ids() -> None:
    spec = expanded(workflow("parent", subflow("one", "child"), subflow("two", "child")))
    ids = [n.id for _, n in iter_nodes(spec.root)]
    assert ids == [
        "parent_main",
        "one",
        "child_main",
        "x",
        "y",
        "two",
        "two-child_main",
        "two-x",
        "two-y",
    ]


def test_a_renamed_id_is_cut_to_fit_and_numbered_when_taken() -> None:
    long = "a" * 60
    child = workflow("long", agent(long))
    spec = expanded(
        workflow("parent", agent(long), agent("call-" + long[:58]), subflow("call", "long")),
        library(child),
    )
    [call] = [n for _, n in iter_nodes(spec.root) if isinstance(n, SubflowNode)]
    assert call.ids[long] == "call-" + long[:56] + "-2"
    assert all(len(run_id) <= 63 for run_id in call.ids.values())


def test_references_follow_a_renamed_node() -> None:
    reviewed = workflow(
        "reviewed",
        {
            "type": "parallel",
            "id": "checks",
            "join": "all",
            "branches": [agent("a"), agent("b")],
        },
        {"type": "reduce", "id": "merge", "from": "checks", "strategy": "concat"},
    )
    spec = expanded(
        workflow("parent", agent("checks"), subflow("call", "reviewed")), library(reviewed)
    )
    [merge] = [n for _, n in iter_nodes(spec.root) if n.id == "merge"]
    assert merge.model_dump(by_alias=True)["from"] == "call-checks"


def test_what_is_wrong_inside_the_called_workflow_is_on_the_subflow() -> None:
    gated = workflow("gated", agent("draft"), gate("approve"), agent("unknown", tools=["nope.x"]))
    raw = workflow(
        "parent",
        {
            "type": "map",
            "id": "each",
            "over": "[1, 2]",
            "body": subflow("call", "gated"),
            "max_concurrency": 2,
        },
    )

    issues = validate(raw, library(gated))

    assert {(i.code, i.path, i.node_id) for i in issues} == {
        ("not_allowed_in_map", "root.steps[0].body", "call"),
        ("unknown_tool", "root.steps[0].body", "call"),
    }
    [in_map] = [i for i in issues if i.code == "not_allowed_in_map"]
    # The called workflow's own paths read from its root.
    assert "gate 'approve' at root.steps[1] cannot be inside a map yet" in in_map.message


def test_a_called_workflow_may_run_in_a_map_or_a_branch_when_its_nodes_may() -> None:
    raw = workflow(
        "parent",
        {
            "type": "map",
            "id": "each",
            "over": "[1, 2]",
            "body": subflow("call", "child"),
            "max_concurrency": 2,
        },
        {"type": "parallel", "id": "p", "join": "all", "branches": [agent("b1"), agent("b2")]},
    )
    assert validate(raw) == []


def test_a_subflow_is_not_allowed_in_an_orchestrators_worker() -> None:
    raw = workflow(
        "parent",
        {
            "type": "orchestrator",
            "id": "hub",
            "hub": {"role": "Lead", "instructions": "Plan."},
            "body": subflow("call", "child"),
            "max_workers": 2,
            "max_concurrency": 2,
        },
    )
    assert ("not_allowed_in_orchestrator", "root.steps[0].body", "call") in where(validate(raw))


def test_artifacts_cross_the_call() -> None:
    writer = workflow("writer", agent("scan", writes="findings.json"))
    reads = workflow("parent", subflow("call", "writer"), agent("report", reads=["findings.json"]))
    assert validate(reads, library(writer)) == []

    unread = workflow("parent", subflow("call", "child"), agent("report", reads=["findings.json"]))
    assert where(validate(unread)) == [("artifact_unknown", "root.steps[1].reads[0]", "report")]


def test_an_input_that_is_not_an_expression_is_invalid() -> None:
    issues = validate(workflow("parent", subflow("call", "child", input="last +")))
    assert where(issues) == [("invalid_expression", "root.steps[0].input", "call")]


def test_a_called_version_that_cannot_run_alone_is_checked_in_place() -> None:
    """A stored version may have issues (it is saved anyway); its tree still expands, and what is
    wrong is reported on the call."""
    broken = workflow("broken", agent("w", tools=["repo.write_file"]), agent("w"))
    issues = validate(workflow("parent", subflow("call", "broken")), library(broken))
    assert where(issues) == [("duplicate_node_id", "root.steps[0]", "call")]


# --- Expansion -------------------------------------------------------------------------------


def test_expansion_attaches_the_called_root_and_keeps_the_documents() -> None:
    parent = parse_spec(workflow("parent", agent("a"), subflow("call", "child")))
    found = expand_workflow(parent, resolve_from(library(CHILD)))

    [call] = [n for _, n in iter_nodes(found.spec.root) if isinstance(n, SubflowNode)]
    assert call.call is not None and call.called_name == "Child flow"
    assert [n.id for _, n in iter_nodes(call.call)] == ["child_main", "x", "y"]
    assert found.called == {"child@1": CHILD}
    # The parent as written is unchanged, and so is its dump.
    assert found.spec.model_dump(mode="json") == parent.model_dump(mode="json")
    assert agents_spawned(found.spec.root) == 3  # `a`, then `x` and `y` in the call


def test_a_spec_with_no_subflow_is_returned_as_it_is() -> None:
    spec = parse_spec(workflow("plain", agent("a")))
    assert expand_workflow(spec, resolve_from({})).spec is spec


def test_an_unresolved_subflow_does_not_compile() -> None:
    spec = parse_spec(workflow("parent", subflow("call", "child")))
    with pytest.raises(CompileError, match="'child' version 1 was not resolved"):
        compile_workflow(spec, FakeRuntime({}))


def test_the_step_limit_counts_the_called_workflow() -> None:
    plain = parse_spec(workflow("parent", agent("a"), agent("b")))
    called = expanded(workflow("parent", agent("a"), subflow("call", "child")))
    assert recursion_limit(called) == recursion_limit(plain) + 3  # entry, x, y, done less `b`


# --- Running ---------------------------------------------------------------------------------


class Recorder:
    """A fake runtime that answers each node `<node>(<input>)`, or `answers[node]`."""

    def __init__(self, answers: Mapping[str, str] | None = None) -> None:
        self.answers = dict(answers or {})
        self.requests: list[AgentRequest] = []

    def start(self, request: AgentRequest) -> AgentRun:
        self.requests.append(request)
        text = self.answers.get(request.node_id, f"{request.node_id}({request.input})")
        return FakeRuntime({request.node_id: [Message(text=text), ECHO_USAGE]}).start(request)

    @property
    def nodes(self) -> list[str]:
        return [r.node_id for r in self.requests]


def saver() -> InMemorySaver:
    return InMemorySaver(serde=checkpoint_serde())


async def run(
    spec: WorkflowSpec, runtime: Recorder, sink: InMemoryEventSink | None = None
) -> WorkflowRunResult:
    return await run_workflow(
        spec, runtime, "brief", sink=sink, checkpointer=saver(), artifacts=InMemoryArtifactStore()
    )


def lifecycle(events: list[RunEvent]) -> list[tuple[str, str | None]]:
    return [(e.type, e.node_id) for e in events if e.type.startswith(("node_", "gate_"))]


async def test_a_workflow_calls_another_by_id_and_version() -> None:
    """Done when (6.5): one workflow calls another by id + version. The called workflow's nodes
    run in the caller's run, between the steps around the call, and its output is the call's."""
    runtime, sink = Recorder(), InMemoryEventSink()
    spec = expanded(workflow("parent", agent("a"), subflow("call", "child"), agent("b")))

    result = await run(spec, runtime, sink)

    assert result.status == "completed"
    assert runtime.nodes == ["a", "x", "y", "b"]
    assert result.text == "b(y(x(a(brief))))"
    assert result.results["call"].text == "y(x(a(brief)))"
    assert lifecycle(sink.events) == [
        ("node_started", "a"),
        ("node_completed", "a"),
        ("node_started", "call"),
        ("node_started", "x"),
        ("node_completed", "x"),
        ("node_started", "y"),
        ("node_completed", "y"),
        ("node_completed", "call"),
        ("node_started", "b"),
        ("node_completed", "b"),
    ]
    [started] = [e for e in sink.events if e.node_id == "call" and e.type == "node_started"]
    assert started.payload == {"workflow": {"id": "child", "version": 1, "name": "Child flow"}}


async def test_input_maps_what_the_called_workflow_gets() -> None:
    runtime = Recorder()
    spec = expanded(
        workflow(
            "parent",
            agent("a"),
            subflow("call", "child", input='"topic: " + results.a.text'),
        )
    )

    result = await run(spec, runtime)

    assert result.status == "completed"
    assert runtime.requests[1].input == "topic: a(brief)"


async def test_an_input_that_fails_fails_the_subflow_and_the_run() -> None:
    runtime, sink = Recorder(), InMemoryEventSink()
    spec = expanded(workflow("parent", subflow("call", "child", input="results.nope.text")))

    result = await run(spec, runtime, sink)

    assert result.status == "failed"
    assert runtime.nodes == []
    [failed] = [e for e in sink.events if e.type == "node_failed"]
    assert failed.node_id == "call"
    assert str(failed.payload["error"]).startswith("input failed:")


async def test_a_failure_inside_the_called_workflow_fails_the_run_naming_its_step() -> None:
    runtime, sink = Recorder(), InMemoryEventSink()
    typed = workflow("typed", agent("x"), agent("y", input_schema={"type": "object"}))
    spec = expanded(workflow("parent", subflow("call", "typed"), agent("b")), library(typed))

    result = await run(spec, runtime, sink)

    assert result.status == "failed"
    assert runtime.nodes == ["x"]
    assert ("node_failed", "y") in lifecycle(sink.events)
    run_failed = [e for e in sink.events if e.type == "run_failed"]
    assert run_failed and "y" in str(run_failed[0].payload)


async def test_a_gate_inside_the_called_workflow_pauses_and_resumes_the_run() -> None:
    gated = workflow("gated", agent("draft"), gate("approve"), agent("publish"))
    spec = expanded(workflow("parent", subflow("call", "gated"), agent("after")), library(gated))
    runtime, sink, checkpointer, run_id = Recorder(), InMemoryEventSink(), saver(), uuid4()

    paused = await run_workflow(
        spec, runtime, "brief", run_id=run_id, sink=sink, checkpointer=checkpointer
    )
    assert (paused.status, paused.waiting_at) == ("waiting", "approve")

    result = await resume_workflow(
        spec,
        runtime,
        "brief",
        run_id=run_id,
        sink=sink,
        checkpointer=checkpointer,
        next_seq=sink.events[-1].seq + 1,
        attempt=2,
        decision=GateDecision(decision="approve", decided_by="ada"),
    )

    assert result.status == "completed"
    assert runtime.nodes == ["draft", "publish", "after"]
    assert result.results["call"].status == "completed"


async def test_a_subflow_in_a_map_runs_the_called_workflow_per_item() -> None:
    runtime, sink = Recorder(), InMemoryEventSink()
    spec = expanded(
        workflow(
            "parent",
            {
                "type": "map",
                "id": "each",
                "over": '["p", "q"]',
                "body": subflow("call", "child"),
                "max_concurrency": 2,
            },
        )
    )

    result = await run(spec, runtime, sink)

    assert result.status == "completed"
    assert sorted(runtime.nodes) == ["x", "x", "y", "y"]
    ends = [
        (e.payload.get("item"), e.type)
        for e in sink.events
        if e.node_id == "call" and e.type != "node_started"
    ]
    assert sorted(ends, key=str) == [(0, "node_completed"), (1, "node_completed")]
    assert result.results["each"].data == {"items": ["p", "q"], "outputs": ["y(x(p))", "y(x(q))"]}


async def test_a_run_cut_off_inside_the_called_workflow_resumes_there() -> None:
    """AC-8 inside a call: the nodes that completed are not run again."""
    spec = expanded(workflow("parent", agent("a"), subflow("call", "child"), agent("b")))
    checkpointer, run_id = saver(), uuid4()
    sink = StopAt("y")
    first = Recorder()
    task = asyncio.create_task(
        run_workflow(spec, first, "brief", run_id=run_id, sink=sink, checkpointer=checkpointer)
    )
    await asyncio.wait_for(sink.reached.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert first.nodes == ["a", "x"]

    second = Recorder()
    result = await resume_workflow(
        spec,
        second,
        "brief",
        run_id=run_id,
        sink=sink,
        checkpointer=checkpointer,
        next_seq=sink.events[-1].seq + 1,
        attempt=2,
    )

    assert result.status == "completed"
    assert second.nodes == ["y", "b"]
    assert result.text == "b(y(x(a(brief))))"


class StopAt(InMemoryEventSink):
    """Holds the run at the start of `node_id`, so a test can cut it off there."""

    def __init__(self, node_id: str) -> None:
        super().__init__()
        self.node_id = node_id
        self.reached = asyncio.Event()

    async def emit(self, event: RunEvent) -> None:
        await super().emit(event)
        if event.type == "node_started" and event.node_id == self.node_id:
            self.reached.set()
            if not hasattr(self, "_held"):
                self._held = True
                await asyncio.sleep(60)


def test_a_caller_that_reads_what_its_call_writes_parses_and_expands() -> None:
    """A calling spec is checked once its calls are resolved: alone, `report` would read an
    artifact no node writes."""
    writer = workflow("writer", agent("scan", writes="findings.json"))
    raw = workflow("parent", subflow("call", "writer"), agent("report", reads=["findings.json"]))

    found = expand_workflow(parse_spec(raw), resolve_from(library(writer)))

    assert found.issues == []
    assert found.called == {"writer@1": writer}


def test_expansion_reports_what_is_wrong_on_the_expanded_tree() -> None:
    broken = workflow("broken", agent("w"), agent("w"))
    found = expand_workflow(
        parse_spec(workflow("parent", subflow("call", "broken"), subflow("u", "nope"))),
        resolve_from(library(broken)),
    )
    assert where(found.issues) == [
        ("duplicate_node_id", "root.steps[0]", "call"),
        ("subflow_unknown", "root.steps[1].workflow", "u"),
    ]


async def test_a_called_workflow_names_its_own_nodes_in_its_expressions() -> None:
    """Its `x` runs as `call-x`, but its loop's condition still reads `results.x`: its own `x`,
    not the caller's."""
    looped = workflow(
        "looped",
        agent("x"),
        {
            "type": "loop",
            "id": "again",
            "body": agent("body"),
            "until": 'results.x.text == "mine"',
            "max_iterations": 3,
        },
    )
    spec = expanded(workflow("parent", agent("x"), subflow("call", "looped")), library(looped))
    runtime = Recorder(answers={"x": "parent's", "call-x": "mine"})

    result = await run(spec, runtime)

    assert result.status == "completed"
    assert runtime.nodes == ["x", "call-x", "body"]
    assert result.results["again"].data == {"stop_reason": "condition", "iterations": 1}


def test_call_documents_describe_each_call_as_it_runs() -> None:
    inner = workflow("inner", agent("x"))
    outer = workflow("outer", agent("z"), subflow("deeper", "inner"))
    spec = expanded(workflow("parent", agent("x"), subflow("call", "outer")), library(inner, outer))

    documents = call_documents(spec.root)

    assert set(documents) == {"call", "deeper"}
    assert documents["call"] == {
        "workflow": {"id": "outer", "version": 1, "name": "Outer"},
        "root": {
            "type": "sequence",
            "id": "outer_main",
            "steps": [
                {
                    "type": "agent",
                    "id": "z",
                    "role": "R",
                    "instructions": "Go.",
                    "tools": [],
                    "reads": [],
                },
                {"type": "subflow", "id": "deeper", "workflow": {"id": "inner", "version": 1}},
            ],
        },
        "renamed": {},
    }
    assert documents["deeper"]["renamed"] == {"deeper-x": "x"}  # type: ignore[index]


class Desk:
    """The repo's tools, recording each call and the node it was made for."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def definitions(self) -> list[ToolDefinition]:
        return [ToolDefinition(name="repo.write_file")]

    async def call(
        self, name: str, arguments: dict[str, JsonValue], *, node_id: str | None = None
    ) -> ToolOutput:
        self.calls.append((name, node_id))
        return ToolOutput(text="written")


async def test_a_called_writer_writes_under_the_id_it_runs_as() -> None:
    """A called workflow's writer gets its own branch like any writer (`agent/<run>/<id>`): the
    tools are called for the id it runs under, renamed when the caller has the id too."""
    writes = workflow("writes", agent("writer", tools=["repo.write_file"]))
    spec = expanded(
        workflow("parent", agent("writer", tools=["repo.write_file"]), subflow("call", "writes")),
        library(writes),
    )
    script = [
        CallTool("repo.write_file", {"path": "a.md", "content": "x"}),
        Message(text="ok"),
        ECHO_USAGE,
    ]
    desk = Desk()
    runtime = FakeRuntime({"writer": script, "call-writer": script}, tools=desk)

    result = await run_workflow(spec, runtime, "brief", checkpointer=saver(), tools=desk)

    assert result.status == "completed"
    assert desk.calls == [("repo.write_file", "writer"), ("repo.write_file", "call-writer")]
    assert writer_node_ids(spec.root) == {"writer", "call-writer"}
