"""The engine plans before a gate (13.8, group 2): each gate asks the outward writes it guards for
their plans through the tools' plan mode, in a step of its own, and the pause shows them. The
tools are fakes that answer the plan calls; the real ones are `agentic_tools.jira` and
`agentic_tools.github` (their tests, and the real run in findings.md)."""

from collections.abc import Sequence
from typing import Any, cast
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from pydantic import JsonValue

from agentic_engine.agent import RunContext
from agentic_engine.artifacts import InMemoryArtifactStore
from agentic_engine.events import InMemoryEventSink
from agentic_engine.gate import GateComment, GateDecision
from agentic_engine.graph import checkpoint_serde, resume_workflow, run_workflow
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import Message, ToolDefinition, ToolOutput
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime
from agentic_runtime.plans import PlanAction, WritePlan
from agentic_runtime.testing import is_plan_call, plan_answer

from .test_sdd_template import SddRun

COMMENT = "The limit belongs in `gateway/limits.py`."


class Tools:
    """Jira as a fake executor: each plan call is answered (and counted) apart from the real
    calls. `plans` overrides what a tool answers in plan mode."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, JsonValue], str | None]] = []
        self.plan_calls: list[tuple[str, dict[str, JsonValue], str | None]] = []
        self.plans: dict[str, ToolOutput] = {}

    def definitions(self) -> Sequence[ToolDefinition]:
        return [ToolDefinition(name=name) for name in ("jira.comment", "jira.transition")]

    async def call(
        self, name: str, arguments: dict[str, JsonValue], *, node_id: str | None = None
    ) -> ToolOutput:
        if is_plan_call(arguments):
            self.plan_calls.append((name, arguments, node_id))
            return self.plans.get(name) or plan_answer(name, arguments)
        self.calls.append((name, arguments, node_id))
        return ToolOutput(text="ok", data={"key": "API-1", "created": True})


ANALYST: dict[str, Any] = {
    "type": "agent",
    "id": "analyst",
    "role": "Analyst",
    "instructions": "Write the comment to post.",
    "writes": "comment.md",
}
GATE: dict[str, Any] = {"type": "gate", "id": "review", "title": "Post this?"}
COMMENT_STEP: dict[str, Any] = {
    "type": "tool",
    "id": "post",
    "tool": "jira.comment",
    "args": {"issue_from": "request", "body_from": "comment.md"},
}
MOVE: dict[str, Any] = {
    "type": "tool",
    "id": "move",
    "tool": "jira.transition",
    "args": {"issue_from": "request", "to": "Done"},
}
INPUT: dict[str, Any] = {"label": "Issue", "required": True, "example": "PROJ-12"}


def spec(*steps: dict[str, Any]) -> WorkflowSpec:
    return parse_spec(
        {
            "spec_version": "0",
            "id": "plans",
            "name": "Plans",
            "input": INPUT,
            "root": {"type": "sequence", "id": "main", "steps": list(steps)},
        }
    )


class Run:
    def __init__(self, workflow: WorkflowSpec | None = None) -> None:
        self.spec = workflow or spec(ANALYST, GATE, COMMENT_STEP, MOVE)
        self.tools = Tools()
        self.runtime = FakeRuntime({"analyst": [Message(text=COMMENT), ECHO_USAGE]})
        self.sink = InMemoryEventSink()
        self.common: dict[str, Any] = {
            "run_id": uuid4(),
            "sink": self.sink,
            "checkpointer": InMemorySaver(serde=checkpoint_serde()),
            "tools": self.tools,
            "artifacts": InMemoryArtifactStore(),
            "context": RunContext(request="API-1"),
        }
        self.attempt = 1

    async def start(self) -> str:
        result = await run_workflow(self.spec, self.runtime, "API-1", **self.common)
        return result.status

    async def decide(
        self, decision: str = "approve", comments: list[GateComment] | None = None
    ) -> str:
        self.attempt += 1
        result = await resume_workflow(
            self.spec,
            self.runtime,
            "API-1",
            next_seq=self.sink.events[-1].seq + 1,
            attempt=self.attempt,
            decision=GateDecision(decision=decision, comments=comments or []),  # type: ignore[arg-type]
            **self.common,
        )
        return result.status

    def events(self, kind: str) -> list[Any]:
        return [e for e in self.sink.events if e.type == kind]

    def shown(self) -> list[WritePlan]:
        """The plans the latest pause showed."""
        waiting = self.events("gate_waiting")[-1]
        assert waiting.payload is not None
        return [WritePlan.model_validate(p) for p in waiting.payload.get("plans", [])]


def actions(plans: Sequence[WritePlan]) -> list[PlanAction]:
    return [p.action for p in plans]


async def test_the_gate_shows_a_plan_of_each_write_it_guards_in_run_order() -> None:
    run = Run()

    assert await run.start() == "waiting"

    assert actions(run.shown()) == ["comment", "transition"]
    assert [p.node_id for p in run.shown()] == ["post", "move"]
    assert [(n, node) for n, _, node in run.tools.plan_calls] == [
        ("jira.comment", "post"),
        ("jira.transition", "move"),
    ]
    assert run.tools.calls == []  # nothing is written while the gate waits
    (planned,) = run.events("writes_planned")
    assert planned.node_id == "review"
    assert planned.payload is not None
    assert planned.payload["gate"] == "review"


async def test_the_plan_is_made_from_the_arguments_the_write_will_have() -> None:
    run = Run()

    await run.start()

    comment = run.tools.plan_calls[0][1]
    assert comment == {"issue": "API-1", "body": COMMENT, "plan": True}
    assert run.tools.plan_calls[1][1] == {"issue": "API-1", "to": "Done", "plan": True}


async def test_a_gate_with_no_write_after_it_has_no_plans_and_no_plan_step() -> None:
    run = Run(spec(ANALYST, GATE))

    assert await run.start() == "waiting"

    assert run.shown() == []
    assert run.events("writes_planned") == []
    assert run.tools.plan_calls == []


async def test_a_plan_that_would_fail_still_lets_the_gate_pause_and_show_it() -> None:
    run = Run()
    failing = WritePlan(
        tool="jira.transition",
        action="transition",
        summary="Move API-1 to Done",
        target={"kind": "issue", "label": "API-1"},  # type: ignore[arg-type]
        error={"code": "transition_unavailable", "message": "API-1 is To Do"},  # type: ignore[arg-type]
    )
    run.tools.plans["jira.transition"] = ToolOutput(
        text="plan", data=failing.model_dump(mode="json")
    )

    assert await run.start() == "waiting"

    shown = run.shown()
    assert shown[1].error is not None
    assert shown[1].error.code == "transition_unavailable"
    assert shown[0].error is None


async def test_a_tool_that_refuses_its_plan_is_a_plan_that_would_fail() -> None:
    run = Run()
    run.tools.plans["jira.comment"] = ToolOutput(
        text="Error executing tool comment: project_not_allowed: project DOCS is not picked",
        is_error=True,
    )

    assert await run.start() == "waiting"

    first = run.shown()[0]
    assert first.error is not None
    assert (first.error.code, first.node_id) == ("project_not_allowed", "post")
    assert "not picked" in first.error.message


async def test_a_restart_after_the_plan_plans_nothing_twice() -> None:
    run = Run()
    await run.start()

    assert await run.decide() == "completed"

    assert len(run.events("writes_planned")) == 1
    # The two plans of the gate, and the batch check's two before the first write: once.
    assert len(run.tools.plan_calls) == 4


async def test_the_plans_of_a_gate_in_a_loop_are_made_again_on_each_pass() -> None:
    loop = {
        "type": "loop",
        "id": "revise",
        "max_iterations": 3,
        "until": 'results.review.data.decision != "changes"',
        "body": {"type": "sequence", "id": "pass", "steps": [ANALYST, {**GATE, "on_changes": 2}]},
    }
    static = {**COMMENT_STEP, "args": {"issue": "API-1", "body": "Done."}}
    run = Run(spec(loop, static))

    assert await run.start() == "waiting"
    assert await run.decide("changes", [GateComment(item="comment", text="Shorter")]) == "waiting"

    assert len(run.events("writes_planned")) == 2
    assert len(run.tools.plan_calls) == 2
    assert actions(run.shown()) == ["comment"]


async def test_the_sdd_gate_shows_the_pull_request_and_both_jira_writes() -> None:
    run = SddRun()
    await run.start()
    await run.decide()  # approve_spec
    await run.decide()  # post_questions
    await run.answer()  # wait_for_answers
    await run.decide()  # approve_spec again

    assert run.waiting_at() == "approve_pr"
    waiting = [e for e in run.sink.events if e.type == "gate_waiting"][-1]
    assert waiting.payload is not None
    plans = [WritePlan.model_validate(p) for p in cast(list[Any], waiting.payload["plans"])]
    assert [(p.node_id, p.tool) for p in plans] == [
        ("publish", "github.openPR"),
        ("jira_update", "jira.comment"),
        ("move", "jira.transition"),
    ]
    # The questions gate planned only the comment that asks.
    asked = next(e for e in run.sink.events if e.type == "writes_planned")
    assert asked.payload is not None
    assert [p["node_id"] for p in asked.payload["plans"]] == ["ask_jira"]  # type: ignore[index]
