"""Composites (6.6): a workflow's steps moved into a stored workflow (`extract`) and called by a
`subflow` pinned to a published version. Drafts of a composite are not callable
(`subflow_unpublished`), a typed workflow gives its subflow ports, and an agent moved into a
composite is given exactly what it was given inline."""

from collections.abc import Mapping
from typing import Any

import pytest
from pydantic import TypeAdapter

from agentic_engine.agent import RunContext
from agentic_engine.artifacts import InMemoryArtifactStore
from agentic_engine.events import InMemoryEventSink
from agentic_engine.graph import WorkflowRunResult, run_workflow
from agentic_engine.policy import PLATFORM_POLICY
from agentic_engine.spec import (
    GraphOp,
    OpError,
    ValidationIssue,
    WorkflowSpec,
    apply_graph_ops,
    expand_workflow,
    parse_spec,
    port_edges,
    resolve_from,
    subflow_key,
    validate_workflow,
)
from agentic_runtime import AgentRequest, AgentRun, Message
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime

type Doc = dict[str, Any]

OPS: TypeAdapter[list[GraphOp]] = TypeAdapter(list[GraphOp])

NEEDS_Q: Doc = {"type": "object", "required": ["q"], "properties": {"q": {"type": "string"}}}
GIVES_MD: Doc = {"type": "object", "required": ["md"], "properties": {"md": {"type": "string"}}}


def agent(id: str, **fields: Any) -> Doc:
    return {"type": "agent", "id": id, "role": "R", "instructions": f"Do {id}.", **fields}


def subflow(id: str, workflow: str, version: int = 1, **fields: Any) -> Doc:
    return {"type": "subflow", "id": id, "workflow": {"id": workflow, "version": version}, **fields}


def workflow(id: str, *steps: Doc, **fields: Any) -> Doc:
    root = {"type": "sequence", "id": f"{id}_main", "steps": list(steps)}
    return {"spec_version": "0", "id": id, "name": id.title(), **fields, "root": root}


def validate(
    raw: Doc, known: Mapping[str, Any], drafts: tuple[str, ...] = ()
) -> list[ValidationIssue]:
    return validate_workflow(
        raw,
        policy=PLATFORM_POLICY,
        priced=lambda _: True,
        default_model="m",
        resolve=resolve_from(dict(known)),
        drafts=drafts,
    )


def where(issues: list[ValidationIssue]) -> list[tuple[str, str, str | None]]:
    return [(i.code, i.path, i.node_id) for i in issues]


def expanded(raw: Doc, known: Mapping[str, Any]) -> WorkflowSpec:
    found = expand_workflow(parse_spec(raw), resolve_from(dict(known)))
    assert found.issues == []
    return found.spec


REVIEW = workflow("review", agent("x"), agent("y"))


# --- Drafts ----------------------------------------------------------------------------------


def test_a_call_to_a_composites_draft_is_subflow_unpublished() -> None:
    known = {subflow_key("review", 1): REVIEW, subflow_key("review", 2): REVIEW}
    caller = workflow("caller", agent("a"), subflow("call", "review", 2))

    issues = validate(caller, known, drafts=(subflow_key("review", 2),))

    assert where(issues) == [("subflow_unpublished", "root.steps[1].workflow", "call")]
    assert "draft" in issues[0].message
    # Its published version is callable, and so is any version of a never-published workflow.
    published = workflow("caller", agent("a"), subflow("call", "review", 1))
    assert validate(published, known, drafts=(subflow_key("review", 2),)) == []
    assert validate(caller, known) == []


def test_a_draft_called_deeper_is_reported_on_the_outer_call() -> None:
    known = {
        subflow_key("outer", 1): workflow("outer", subflow("inner", "review", 2)),
        subflow_key("review", 2): REVIEW,
    }
    caller = workflow("caller", subflow("call", "outer"))

    issues = validate(caller, known, drafts=(subflow_key("review", 2),))

    assert where(issues) == [("subflow_unpublished", "root.steps[0]", "call")]


# --- Typed composites ------------------------------------------------------------------------


def test_a_workflows_own_schemas_must_be_port_schemas() -> None:
    raw = workflow("typed", agent("a"), input_schema={"type": "array"})

    issues = validate(raw, {})

    assert where(issues) == [("invalid_schema", "input_schema", None)]


def test_a_typed_call_is_checked_against_the_step_before_and_after() -> None:
    typed = workflow("typed", agent("x"), input_schema=NEEDS_Q, output_schema=GIVES_MD)
    known = {subflow_key("typed", 1): typed}
    caller = workflow(
        "caller",
        agent("a", output_schema={"type": "object", "properties": {"other": {}}}),
        subflow("call", "typed"),
        agent("b", input_schema={"type": "object", "required": ["html"], "properties": {}}),
    )

    issues = validate(caller, known)

    assert where(issues) == [
        ("port_mismatch", "root.steps[1]", "call"),
        ("port_mismatch", "root.steps[2]", "b"),
    ]
    assert "requires 'q'" in issues[0].message
    assert "requires 'html', which the output_schema of 'call'" in issues[1].message


def test_a_typed_call_that_fits_has_no_issue() -> None:
    typed = workflow("typed", agent("x"), input_schema=NEEDS_Q, output_schema=GIVES_MD)
    caller = workflow(
        "caller",
        agent("a", output_schema=NEEDS_Q),
        subflow("call", "typed"),
        agent("b", input_schema=GIVES_MD),
    )

    assert validate(caller, {subflow_key("typed", 1): typed}) == []


def test_an_untyped_call_or_one_with_its_own_input_breaks_the_edge() -> None:
    typed = workflow("typed", agent("x"), input_schema=NEEDS_Q)
    known = {subflow_key("typed", 1): typed, subflow_key("plain", 1): workflow("plain", agent("y"))}
    caller = workflow(
        "caller",
        agent("a", output_schema={"type": "object", "properties": {}}),
        subflow("mapped", "typed", input='{"q": "x"}'),
        subflow("plain_call", "plain"),
        agent("b", input_schema=GIVES_MD),
    )

    spec = expanded(caller, known)

    consumers = {consumer.id for _, consumer, _ in port_edges(spec.root)}
    assert "mapped" not in consumers and "b" not in consumers


# --- Running a typed composite ----------------------------------------------------------------


class Recorder:
    """A fake runtime that answers each node `answers[node]`, or `<node>(<input>)`."""

    def __init__(self, answers: Mapping[str, str] | None = None) -> None:
        self.answers = dict(answers or {})
        self.requests: list[AgentRequest] = []

    def start(self, request: AgentRequest) -> AgentRun:
        self.requests.append(request)
        text = self.answers.get(request.node_id, f"{request.node_id}({request.input})")
        return FakeRuntime({request.node_id: [Message(text=text), ECHO_USAGE]}).start(request)


async def run(
    spec: WorkflowSpec,
    runtime: Recorder,
    sink: InMemoryEventSink | None = None,
    context: RunContext | None = None,
    input: str = "brief",
) -> WorkflowRunResult:
    return await run_workflow(
        spec, runtime, input, sink=sink, artifacts=InMemoryArtifactStore(), context=context
    )


TYPED = workflow("typed", agent("x"), input_schema=NEEDS_Q, output_schema=GIVES_MD)


async def test_a_typed_composite_checks_its_input_at_the_call() -> None:
    runtime, sink = Recorder(), InMemoryEventSink()
    spec = expanded(workflow("caller", subflow("call", "typed")), {subflow_key("typed", 1): TYPED})

    result = await run(spec, runtime, sink, input='{"other": 1}')

    assert result.status == "failed"
    assert runtime.requests == []
    [failed] = [e for e in sink.events if e.type == "node_failed"]
    assert failed.node_id == "call"
    assert failed.payload["port"]["side"] == "input"  # type: ignore[index]
    assert "input of 'call'" in str(failed.payload["error"])


async def test_a_typed_composite_checks_its_output_at_the_call() -> None:
    runtime, sink = Recorder({"x": '{"wrong": true}'}), InMemoryEventSink()
    spec = expanded(workflow("caller", subflow("call", "typed")), {subflow_key("typed", 1): TYPED})

    result = await run(spec, runtime, sink, input='{"q": "why"}')

    assert result.status == "failed"
    [failed] = [e for e in sink.events if e.type == "node_failed"]
    assert failed.node_id == "call"
    assert failed.payload["port"]["side"] == "output"  # type: ignore[index]


async def test_a_typed_composite_that_fits_gives_its_output_as_data() -> None:
    runtime = Recorder({"x": 'Here it is.\n{"md": "# Done"}'})
    spec = expanded(
        workflow("caller", subflow("call", "typed"), agent("b", input_schema=GIVES_MD)),
        {subflow_key("typed", 1): TYPED},
    )

    result = await run(spec, runtime, input='{"q": "why"}')

    assert result.status == "completed"
    assert result.results["call"].data == {"md": "# Done"}
    assert runtime.requests[-1].input == '{\n  "md": "# Done"\n}'


async def test_a_typed_composite_in_a_map_is_checked_per_item() -> None:
    runtime, sink = Recorder({"x": '{"md": "ok"}'}), InMemoryEventSink()
    each = {
        "type": "map",
        "id": "each",
        "over": '["{\\"q\\": \\"a\\"}", "nope"]',
        "max_concurrency": 1,
        "body": subflow("call", "typed"),
    }
    spec = expanded(workflow("caller", each), {subflow_key("typed", 1): TYPED})

    result = await run(spec, runtime, sink)

    assert result.status == "failed"
    failed = [e for e in sink.events if e.type == "node_failed" and e.node_id == "call"]
    assert [f.payload["port"]["side"] for f in failed] == ["input"]  # type: ignore[index]


# --- What agents receive once extracted (lessons rule 1) --------------------------------------


async def test_an_extracted_agent_receives_what_it_received_inline() -> None:
    """An agent moved into a composite gets the same role, instructions, input, tools and run
    context as it did when it was a step of the caller: extracting changes where it is stored,
    never what it is told."""
    inline = workflow(
        "docs",
        agent("plan"),
        agent("write", tools=["repo.read_file", "repo.list_files"], role="writer"),
        agent("check", instructions="Check the docs."),
        agent("after"),
    )
    ops = [
        {
            "op": "extract",
            "node_ids": ["write", "check"],
            "subflow_id": "writing",
            "workflow": {"id": "writing", "name": "Writing"},
        }
    ]
    applied = apply_graph_ops(inline, OPS.validate_python(ops))
    assert applied.extracted is not None
    spec = expanded(applied.spec, {subflow_key("writing", 1): applied.extracted})
    context = RunContext(repo="acme/docs")

    before, after = Recorder(), Recorder()
    await run(parse_spec(inline), before, context=context)
    await run(spec, after, context=context)

    def told(requests: list[AgentRequest]) -> list[dict[str, Any]]:
        fields = {"node_id", "role", "instructions", "input", "tools", "context", "model"}
        return [r.model_dump(include=fields) for r in requests]

    assert told(after.requests) == told(before.requests)
    assert [r.node_id for r in after.requests] == ["plan", "write", "check", "after"]


# --- Ops the browser does not mirror ----------------------------------------------------------


def test_a_wrap_whose_container_misses_its_parameters_is_off_the_schema() -> None:
    """Only the server checks the schema (the browser's `applyOps` is a preview), so this case
    is not in the shared fixture: the builder fills `with` from the kind's manifest default."""
    spec = workflow("w", agent("a"), agent("b"))
    ops = [{"op": "wrap", "node_ids": ["b"], "with": {"type": "loop", "id": "redo"}}]

    with pytest.raises(OpError) as exc:
        apply_graph_ops(spec, OPS.validate_python(ops))

    assert (exc.value.code, exc.value.op_index, exc.value.node_id) == ("schema", None, "redo")
