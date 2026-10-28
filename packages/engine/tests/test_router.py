"""The `router` primitive: a run branches on a condition, by a CEL rule or a classifier agent
(phase 4.6), and runs only the route it chose."""

import asyncio
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agentic_engine.agent import OUTPUT_SCHEMA_INSTRUCTION
from agentic_engine.artifacts import InMemoryArtifactStore
from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.graph import WorkflowRunResult, checkpoint_serde, resume_workflow, run_workflow
from agentic_engine.graph.compile import (
    CLASSIFIER_ROLE,
    classifier_instructions,
    recursion_limit,
    step_nodes,
)
from agentic_engine.policy import PLATFORM_POLICY, Policy
from agentic_engine.spec import (
    RouterNode,
    SequenceNode,
    WorkflowSpec,
    agents_spawned,
    parse_spec,
    policy_issues,
    validate_workflow,
)
from agentic_runtime import AgentEvent, AgentRequest, AgentRun, Message
from agentic_runtime.fake import ECHO_USAGE, Delay, FakeRuntime, Script

FIXTURES = Path(__file__).parent / "fixtures" / "specs" / "valid"
FINDINGS_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["findings"],
    "properties": {"findings": {}},
}


def agent(id: str, **fields: object) -> dict[str, object]:
    return {"type": "agent", "id": id, "role": "R", "instructions": "Go.", **fields}


def route(id: str, then: Mapping[str, object], when: str | None = None) -> dict[str, object]:
    found: dict[str, object] = {"id": id, "then": then}
    if when is not None:
        found["when"] = when
    return found


def router(
    routes: Sequence[Mapping[str, object]],
    default: Mapping[str, object] | None = None,
    classifier: Mapping[str, object] | None = None,
    id: str = "pick",
) -> dict[str, object]:
    node: dict[str, object] = {"type": "router", "id": id, "routes": list(routes)}
    if default is not None:
        node["default"] = default
    if classifier is not None:
        node["classifier"] = classifier
    return node


def spec(*steps: Mapping[str, object]) -> WorkflowSpec:
    return parse_spec(
        {
            "spec_version": "0",
            "id": "routed",
            "name": "Routed",
            "root": {"type": "sequence", "id": "main", "steps": list(steps)},
        }
    )


class Recorder:
    """A fake runtime that answers each node `<node>(<input>)`, or with `answers[node]`, after
    `delays[node]` seconds, and records each request."""

    def __init__(
        self, answers: Mapping[str, str] | None = None, delays: Mapping[str, float] | None = None
    ) -> None:
        self._answers = dict(answers or {})
        self._delays = dict(delays or {})
        self.requests: list[AgentRequest] = []

    def start(self, request: AgentRequest) -> AgentRun:
        self.requests.append(request)
        text = self._answers.get(request.node_id, f"{request.node_id}({request.input})")
        script: Script = [Delay(self._delays.get(request.node_id, 0)), Message(text=text)]
        return FakeRuntime({request.node_id: [*script, ECHO_USAGE]}).start(request)

    @property
    def nodes(self) -> list[str]:
        return [r.node_id for r in self.requests]


def saver() -> InMemorySaver:
    return InMemorySaver(serde=checkpoint_serde())


async def run(
    spec: WorkflowSpec,
    runtime: Recorder,
    sink: InMemoryEventSink | None = None,
    input: str = "brief",
    policy: Policy = PLATFORM_POLICY,
) -> WorkflowRunResult:
    return await run_workflow(
        spec,
        runtime,
        input,
        sink=sink,
        checkpointer=saver(),
        policy=policy,
        artifacts=InMemoryArtifactStore(),
    )


def of(events: list[RunEvent], node_id: str) -> list[tuple[str, object]]:
    """The router's own events: type and payload."""
    return [(e.type, e.payload) for e in events if e.node_id == node_id]


def branch_of(event: RunEvent) -> int | None:
    """The branch an event's node ran in, if it ran in one."""
    branch = event.payload.get("branch")
    return branch if isinstance(branch, int) else None


def choice(answer: str, reason: str = "It says so.") -> str:
    return json.dumps({"route": answer, "reason": reason})


async def test_a_rule_router_runs_the_first_route_whose_condition_holds() -> None:
    """Done when (4.6): a run branches on a condition. Both conditions hold; the first route
    runs, on the router's input, and its output goes on to the next step."""
    runtime, sink = Recorder(), InMemoryEventSink()
    routed = spec(
        router(
            [
                route("short", agent("brief_reply"), 'last.startsWith("bri")'),
                route("long", agent("long_reply"), "true"),
            ]
        ),
        agent("after"),
    )

    result = await run(routed, runtime, sink)

    assert result.status == "completed"
    assert runtime.nodes == ["brief_reply", "after"]
    assert result.text == "after(brief_reply(brief))"
    assert result.results["pick"].text == "brief_reply(brief)"
    assert of(sink.events, "pick") == [
        ("node_started", {"routes": ["short", "long"], "mode": "rule"}),
        ("route_chosen", {"route": "short", "mode": "rule", "reason": 'last.startsWith("bri")'}),
        ("node_completed", {"route": "short"}),
    ]
    started = [e.node_id for e in sink.events if e.type == "node_started"]
    assert started == ["pick", "brief_reply", "after"]
    assert result.order == ["brief_reply", "pick", "after"]


async def test_the_default_runs_when_no_route_matches() -> None:
    runtime, sink = Recorder(), InMemoryEventSink()
    routed = spec(router([route("never", agent("a"), "false")], default=agent("fallback")))

    result = await run(routed, runtime, sink)

    assert result.status == "completed"
    assert runtime.nodes == ["fallback"]
    assert ("route_chosen", {"route": "default", "mode": "rule", "reason": "no route matched"}) in (
        of(sink.events, "pick")
    )
    assert of(sink.events, "pick")[-1] == ("node_completed", {"route": "default"})


async def test_no_match_and_no_default_fails_the_router_and_the_run() -> None:
    runtime, sink = Recorder(), InMemoryEventSink()

    result = await run(
        spec(router([route("never", agent("a"), "false")]), agent("b")), runtime, sink
    )

    assert result.status == "failed"
    assert result.stopped_at == "pick"
    assert runtime.nodes == []
    error = "no route of 'pick' matched, and it has no default"
    assert of(sink.events, "pick")[-1] == ("node_failed", {"error": error})
    assert result.results["pick"].error == error


async def test_a_condition_that_fails_to_evaluate_names_its_route() -> None:
    runtime = Recorder()

    result = await run(spec(router([route("odd", agent("a"), "last.size() > results.x")])), runtime)

    assert result.status == "failed"
    error = result.results["pick"].error or ""
    assert error.startswith("when of route 'odd' failed:")


async def test_rules_read_results_and_artifacts() -> None:
    """The report path of the audit (4.6): the route follows what `findings.json` holds."""
    runtime = Recorder(answers={"triage": json.dumps({"findings": [{"severity": "high"}]})})
    findings = 'artifacts["findings.json"].findings'
    routed = spec(
        agent("triage", output_schema=FINDINGS_SCHEMA, writes="findings.json"),
        router(
            [
                route("clean", agent("clean_report"), f"size({findings}) == 0"),
                route(
                    "fix_first",
                    agent("fix_first_report"),
                    f'{findings}.exists(f, f.severity in ["high", "critical"])',
                ),
            ],
            default=agent("standard_report"),
        ),
        router(
            [route("triaged", agent("done"), 'results.triage.status == "completed"')],
            id="check",
        ),
    )

    result = await run(routed, runtime)

    assert result.status == "completed"
    assert runtime.nodes == ["triage", "fix_first_report", "done"]


async def test_the_router_fixture_routes_each_report_and_its_reader_reads_it() -> None:
    """The routes all write `report.md`, so the step after the router reads it whichever ran."""
    spec = parse_spec(json.loads((FIXTURES / "router-rule.json").read_text()))
    for findings, report in [
        ([], "clean_report"),
        ([{"severity": "critical"}], "fix_first_report"),
        ([{"severity": "low"}], "standard_report"),
    ]:
        runtime = Recorder(answers={"triage": json.dumps({"findings": findings})})

        result = await run(spec, runtime)

        assert result.status == "completed", result.results
        assert runtime.nodes == ["triage", report, "summary"]
        assert (
            runtime.requests[-1].input
            == f"{report}({json.dumps({'findings': findings}, indent=2)})"
        )
        assert result.artifacts["report.md"].node_id == report


async def test_a_classifier_chooses_the_route_and_says_why() -> None:
    runtime = Recorder(answers={"pick": choice("feature", "It asks for something new.")})
    sink = InMemoryEventSink()
    routed = spec(
        router(
            [
                {"id": "bug", "description": "Something is broken.", "then": agent("fix")},
                {"id": "feature", "description": "A new capability.", "then": agent("plan")},
            ],
            default=agent("answer"),
            classifier={"instructions": "Decide what kind of request this is.", "model": "m"},
        ),
        agent("after"),
    )

    result = await run(routed, runtime, sink)

    assert result.status == "completed"
    assert runtime.nodes == ["pick", "plan", "after"]
    asked = runtime.requests[0]
    assert (asked.role, asked.model, asked.input) == (CLASSIFIER_ROLE, "m", "brief")
    assert "- `bug`: Something is broken." in asked.instructions
    assert "- `default`: when no other route fits" in asked.instructions
    assert OUTPUT_SCHEMA_INSTRUCTION in asked.instructions
    assert runtime.requests[1].input == "brief"
    chosen = (
        "route_chosen",
        {"route": "feature", "mode": "classifier", "reason": "It asks for something new."},
    )
    assert chosen in of(sink.events, "pick")
    usage = [e for e in sink.events if e.node_id == "pick" and e.type == "usage"]
    assert len(usage) == 1
    # The classifier, the route and `after`, each one agent.
    assert result.usage is not None and result.usage.input_tokens == 3 * ECHO_USAGE.input_tokens


def test_classifier_instructions_list_the_routes() -> None:
    node = RouterNode.model_validate(
        router(
            [{"id": "bug", "then": agent("fix")}],
            classifier={"instructions": "Choose."},
        )
    )

    assert classifier_instructions(node) == (
        "Choose.\n\nChoose one route for the input. The routes:\n- `bug`: no description\n\n"
        "Answer with the route's id as `route` and why, in one sentence, as `reason`."
    )


@pytest.mark.parametrize(
    ("answer", "pointer"),
    [(choice("refactor"), "/route"), ('{"route": "bug"}', ""), ("I think it is a bug.", "")],
)
async def test_a_classifier_that_answers_off_the_routes_fails_as_a_port(
    answer: str, pointer: str
) -> None:
    """The classifier can only name one of the router's routes: anything else fails the router
    on its typed output, and no route runs."""
    runtime, sink = Recorder(answers={"pick": answer}), InMemoryEventSink()
    routed = spec(
        router([{"id": "bug", "then": agent("fix")}], classifier={"instructions": "Choose."})
    )

    result = await run(routed, runtime, sink)

    assert result.status == "failed"
    assert runtime.nodes == ["pick"]
    [payload] = [p for t, p in of(sink.events, "pick") if t == "node_failed"]
    assert isinstance(payload, dict)
    assert payload["port"]["side"] == "output"  # type: ignore[index]
    assert payload["port"]["errors"][0]["pointer"] == pointer  # type: ignore[index]


async def test_routes_not_taken_never_start() -> None:
    runtime, sink = Recorder(), InMemoryEventSink()
    routed = spec(
        router(
            [
                route(
                    "one",
                    {"type": "sequence", "id": "first", "steps": [agent("a"), agent("b")]},
                    "false",
                ),
                route(
                    "two",
                    {"type": "sequence", "id": "second", "steps": [agent("c"), agent("d")]},
                    "true",
                ),
            ]
        )
    )

    result = await run(routed, runtime, sink)

    assert runtime.nodes == ["c", "d"]
    assert not {"a", "b"} & {e.node_id for e in sink.events}
    assert result.text == "d(c(brief))"


async def test_a_router_in_a_loop_chooses_again_each_iteration() -> None:
    runtime = Recorder()
    looped = parse_spec(
        {
            "spec_version": "0",
            "id": "loop",
            "name": "Loop",
            "root": {
                "type": "loop",
                "id": "again",
                "until": "iteration == 2",
                "max_iterations": 3,
                "body": router([route("first", agent("a"), 'last == "brief"')], default=agent("b")),
            },
        }
    )

    result = await run(looped, runtime)

    assert result.status == "completed"
    assert runtime.nodes == ["a", "b"]
    assert result.text == "b(a(brief))"


async def test_a_router_in_a_map_routes_each_item() -> None:
    runtime, sink = Recorder(), InMemoryEventSink()
    spec = parse_spec(json.loads((FIXTURES / "router-in-map.json").read_text()))

    result = await run(spec, runtime, sink)

    assert result.status == "completed"
    assert sorted(runtime.nodes) == ["code_review", "ui_review"]
    assert result.results["each"].data == {
        "items": ["api", "web"],
        "outputs": ["code_review(api)", "ui_review(web)"],
    }
    chosen = sorted(
        (e.payload["item"], e.payload["route"]) for e in sink.events if e.type == "route_chosen"
    )
    assert chosen == [(0, "default"), (1, "frontend")]
    ends = sorted(
        (e.payload["item"], e.type)
        for e in sink.events
        if e.node_id == "by_kind" and e.type == "node_completed"
    )
    assert ends == [(0, "node_completed"), (1, "node_completed")]


async def test_a_router_in_a_branch_runs_with_the_branch() -> None:
    runtime, sink = Recorder(), InMemoryEventSink()
    routed = spec(
        {
            "type": "parallel",
            "id": "review",
            "join": "all",
            "branches": [
                agent("a"),
                router([route("x", agent("x_review"), "true")], id="choose"),
            ],
        },
        agent("after"),
    )

    result = await run(routed, runtime, sink)

    assert result.status == "completed"
    assert sorted(runtime.nodes[:2]) == ["a", "x_review"]
    assert result.results["review"].data == {
        "outputs": {"a": "a(brief)", "choose": "x_review(brief)"},
        "completed": ["a", "choose"],
        "failed": [],
        "cancelled": [],
    }
    assert {branch_of(e) for e in sink.events if e.node_id in {"choose", "x_review"}} == {1}


async def test_a_failing_route_in_a_branch_ends_the_router_and_names_its_step() -> None:
    runtime, sink = Recorder(), InMemoryEventSink()
    routed = spec(
        {
            "type": "parallel",
            "id": "review",
            "join": "all",
            "branches": [
                agent("a"),
                router(
                    [route("x", agent("x_review", input_schema=FINDINGS_SCHEMA), "true")],
                    id="choose",
                ),
            ],
        }
    )

    result = await run(routed, runtime, sink)

    assert result.status == "failed"
    [end] = [e for e in sink.events if e.node_id == "choose" and e.type == "node_failed"]
    assert end.payload["route"] == "x"
    assert str(end.payload["error"]).startswith("x_review failed: input of 'x_review'")
    assert "branch 'choose' x_review failed" in (result.results["review"].error or "")


async def test_nested_parallel_and_vote_in_a_branch() -> None:
    """The audit's reviewers (4.6): three reviewers in a branch, their findings voted on, beside
    another branch, then merged."""
    finding = {"fingerprint": "f1", "tool": "review", "rule": "r", "severity": "high"}
    finding |= {"category": "lint", "path": "a.py", "line": 1, "message": "m"}
    lone = {**finding, "fingerprint": "f2", "path": "b.py"}

    def report(*findings: object) -> str:
        checks = [{"path": ".", "kind": "repo", "tool": "review", "status": "ran"}]
        counts = {"high": len(findings)}
        return json.dumps(
            {
                "scanner": "lint",
                "checks": checks,
                "findings": list(findings),
                "counts": counts,
                "truncated": False,
            }
        )

    runtime = Recorder(
        answers={
            "r1": report(finding),
            "r2": report(finding, lone),
            "r3": report(),
            "other": report(lone),
        }
    )
    sink = InMemoryEventSink()
    reviewers = [agent(f"r{i}", output_schema=FINDINGS_SCHEMA) for i in (1, 2, 3)]
    routed = spec(
        {
            "type": "parallel",
            "id": "checks",
            "join": "all",
            "branches": [
                agent("other", output_schema=FINDINGS_SCHEMA),
                {
                    "type": "sequence",
                    "id": "voted",
                    "steps": [
                        {"type": "parallel", "id": "inner", "join": "all", "branches": reviewers},
                        {"type": "reduce", "id": "vote", "from": "inner", "strategy": "vote"},
                    ],
                },
            ],
        },
        {
            "type": "reduce",
            "id": "merge",
            "from": "checks",
            "strategy": "dedupe",
            "writes": "findings.json",
        },
    )

    result = await run(routed, runtime, sink)

    assert result.status == "completed", {k: r.error for k, r in result.results.items()}
    voted = result.results["vote"].data or {}
    assert [f["fingerprint"] for f in voted["findings"]] == ["f1"]  # type: ignore[index, union-attr]
    merged = result.results["merge"].data or {}
    assert sorted(f["fingerprint"] for f in merged["findings"]) == ["f1", "f2"]  # type: ignore[union-attr]
    inner_branches = [
        e for e in sink.events if e.node_id == "inner" and e.type == "parallel_branch_completed"
    ]
    assert {branch_of(e) for e in inner_branches} == {1}
    assert {branch_of(e) for e in sink.events if e.node_id in {"r1", "r2", "r3"}} == {
        0,
        1,
        2,
    }
    assert result.usage is not None and result.usage.input_tokens == 4 * ECHO_USAGE.input_tokens


def test_the_nested_vote_fixture_counts_its_agents() -> None:
    nested = parse_spec(json.loads((FIXTURES / "parallel-nested-vote.json").read_text()))
    assert isinstance(nested.root, SequenceNode)

    assert agents_spawned(nested.root.steps[0]) == 3


class Throttled(Recorder):
    """Records the most runs in flight at once."""

    def __init__(self, delays: Mapping[str, float]) -> None:
        super().__init__(delays=delays)
        self.live = 0
        self.peak = 0

    def start(self, request: AgentRequest) -> AgentRun:
        return _Live(super().start(request), self)


class _Live:
    def __init__(self, run: AgentRun, runtime: Throttled) -> None:
        self._run = run
        self._runtime = runtime

    def cancel(self) -> None:
        self._run.cancel()

    def __aiter__(self) -> AsyncIterator[AgentEvent]:
        return self._stream()

    async def _stream(self) -> AsyncIterator[AgentEvent]:
        self._runtime.live += 1
        self._runtime.peak = max(self._runtime.peak, self._runtime.live)
        try:
            async for event in self._run:
                yield event
        finally:
            self._runtime.live -= 1


async def test_nested_branches_above_agents_alive_wait_for_a_slot() -> None:
    """Two parallels of three reviewers inside one: six agents could run at once. Under a
    limit of three they queue instead, and the spec is not refused."""
    runtime = Throttled(delays={f"{p}{i}": 0.02 for p in "rs" for i in range(3)})
    inner = [
        {
            "type": "parallel",
            "id": f"inner_{p}",
            "join": "all",
            "branches": [agent(f"{p}{i}") for i in range(3)],
        }
        for p in "rs"
    ]
    nested = spec({"type": "parallel", "id": "outer", "join": "all", "branches": inner})
    policy = PLATFORM_POLICY.model_copy(update={"agents_alive": 3})

    assert policy_issues(nested.root, policy) == []
    result = await run(nested, runtime, policy=policy)

    assert result.status == "completed"
    assert len(runtime.nodes) == 6
    assert runtime.peak == 3


async def test_a_classifier_counts_as_spawned_and_the_spawn_limit_refuses_it() -> None:
    runtime, sink = Recorder(), InMemoryEventSink()
    routed = spec(
        agent("first"),
        router([{"id": "bug", "then": agent("fix")}], classifier={"instructions": "Choose."}),
    )
    policy = PLATFORM_POLICY.model_copy(update={"agents_spawned": 1})

    result = await run(routed, runtime, sink, policy=policy)

    assert result.status == "failed"
    assert result.stopped_at == "pick"
    assert runtime.nodes == ["first"]
    assert [t for t, _ in of(sink.events, "pick")] == [
        "node_started",
        "policy_limit_exceeded",
        "node_failed",
    ]


def test_routes_are_walked_and_the_longest_counts_toward_the_step_limit() -> None:
    routed = spec(
        router(
            [
                route("one", agent("a"), "true"),
                route(
                    "two",
                    {"type": "sequence", "id": "s", "steps": [agent("b"), agent("c")]},
                    "true",
                ),
            ],
            default=agent("d"),
        )
    )

    assert [n.id for n in step_nodes(routed.root)] == ["a", "b", "c", "d"]
    # The router (entry, done), its longest route and the margin.
    assert recursion_limit(routed) == 2 + 2 + 10


def test_a_classifier_on_an_unpriced_model_cannot_hold_a_budget() -> None:
    raw = {
        "spec_version": "0",
        "id": "r",
        "name": "R",
        "root": router(
            [{"id": "bug", "then": agent("fix", model="priced")}],
            classifier={"instructions": "Choose.", "model": "unknown"},
        ),
    }
    policy = PLATFORM_POLICY.model_copy(update={"budget_usd": 1})

    issues = validate_workflow(
        raw, policy=policy, priced=lambda model: model == "priced", default_model="priced"
    )

    assert [(i.code, i.node_id) for i in issues] == [("budget_unpriced_model", "pick")]


def test_publishing_a_writer_from_inside_a_route_is_refused() -> None:
    """A route may not have run, so a publisher after the router cannot rely on its writer or
    its gate."""
    raw = {
        "spec_version": "0",
        "id": "r",
        "name": "R",
        "root": {
            "type": "sequence",
            "id": "main",
            "steps": [
                router(
                    [
                        route(
                            "write",
                            {
                                "type": "sequence",
                                "id": "edit",
                                "steps": [
                                    agent("writer", tools=["repo.write_file"]),
                                    {"type": "gate", "id": "approve", "title": "OK?"},
                                ],
                            },
                            "true",
                        )
                    ],
                    default=agent("nothing"),
                ),
                {
                    "type": "tool",
                    "id": "publish",
                    "tool": "github.openPR",
                    "args": {"from_node": "writer"},
                },
            ],
        },
    }

    issues = validate_workflow(
        raw, policy=PLATFORM_POLICY, priced=lambda _: True, default_model="m"
    )

    assert [(i.code, i.node_id) for i in issues] == [("reference", "publish")]


class StartedSink(InMemoryEventSink):
    """Flags the start of the node `node_id`."""

    def __init__(self, node_id: str) -> None:
        super().__init__()
        self.node_id = node_id
        self.started = asyncio.Event()

    async def emit(self, event: RunEvent) -> None:
        await super().emit(event)
        if event.type == "node_started" and event.node_id == self.node_id:
            self.started.set()


async def test_a_resumed_run_goes_on_in_the_chosen_route_without_asking_again() -> None:
    """AC-8 inside a route: a run cut off while its route runs resumes in that route, and the
    classifier is not asked again."""
    routed = spec(
        router(
            [
                {"id": "bug", "then": agent("fix")},
                {
                    "id": "feature",
                    "then": {
                        "type": "sequence",
                        "id": "f",
                        "steps": [agent("spec_it"), agent("plan")],
                    },
                },
            ],
            classifier={"instructions": "Choose."},
        ),
        agent("after"),
    )
    checkpointer, run_id, sink = saver(), uuid4(), StartedSink("spec_it")
    first = Recorder(answers={"pick": choice("feature")}, delays={"spec_it": 60})
    task = asyncio.create_task(
        run_workflow(routed, first, "brief", run_id=run_id, sink=sink, checkpointer=checkpointer)
    )
    await asyncio.wait_for(sink.started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    second = Recorder(answers={"pick": choice("bug")})
    result = await resume_workflow(
        routed,
        second,
        "brief",
        run_id=run_id,
        sink=sink,
        checkpointer=checkpointer,
        next_seq=sink.events[-1].seq + 1,
        attempt=2,
    )

    assert result.status == "completed"
    assert second.nodes == ["spec_it", "plan", "after"]
    assert result.text == "after(plan(spec_it(brief)))"
    assert [e.seq for e in sink.events] == list(range(1, len(sink.events) + 1))


async def test_the_router_fixtures_run_end_to_end() -> None:
    classifier = parse_spec(json.loads((FIXTURES / "router-classifier.json").read_text()))
    runtime = Recorder(answers={"kind": choice("default")})

    result = await run(classifier, runtime)

    assert result.status == "completed"
    assert runtime.nodes == ["kind", "answer", "reply"]
