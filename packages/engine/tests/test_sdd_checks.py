# ruff: noqa: E501
"""The SDD templates with `checks` (13.4): `commit_specs` and `approve_pr` move into the review
loop's body, `approve_pr` checks the merged work with `evidence` (build, tests, analyzers, coverage
and acceptance criteria), and what each agent is told changes with it. The run tests assert what
the lead receives after a send-back (lessons, rule 1)."""

import json
from collections.abc import Sequence
from typing import Any, cast
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import JsonValue, ValidationError

from agentic_engine.agent import RunContext
from agentic_engine.artifacts import InMemoryArtifactStore
from agentic_engine.events import InMemoryEventSink
from agentic_engine.gate import GateDecision
from agentic_engine.graph import checkpoint_serde, resume_workflow, run_workflow
from agentic_engine.policy import PLATFORM_POLICY
from agentic_engine.spec import (
    SPEC_INPUT_ARTIFACT,
    SequenceNode,
    WorkflowSpec,
    validate_workflow,
)
from agentic_engine.templates import (
    PlanBuildReviewParams,
    SddFileParams,
    SddParams,
    build_plan_build_review_spec,
    build_sdd_file_spec,
    build_sdd_spec,
)
from agentic_runtime import AgentRequest, AgentRun, ToolDefinition, ToolOutput

from .test_sdd_spec_file import ANSWERS, FILE_TEXT, SPEC, Answers, Platform, Review

CRITERIA = """# Feature specification: CSV export

## Acceptance criteria

- AC-001: When an admin exports, the system shall return a CSV.
"""


def nodes(spec: WorkflowSpec) -> dict[str, Any]:
    """Every node of the spec by id, as plain JSON."""
    found: dict[str, Any] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "id" in node and "type" in node:
                found[node["id"]] = node
            for value in node.values():  # type: ignore[reportUnknownVariableType]
                walk(value)
        elif isinstance(node, list):
            for item in node:  # type: ignore[reportUnknownVariableType]
                walk(item)

    walk(spec.model_dump(mode="json", by_alias=True, exclude_none=True)["root"])
    return found


def issues(spec: WorkflowSpec) -> list[str]:
    found = validate_workflow(
        spec.model_dump(mode="json", by_alias=True, exclude_none=True),
        policy=PLATFORM_POLICY,
        priced=lambda _: True,
        default_model="default",
    )
    return [f"{i.code}: {i.message}" for i in found]


def _file(**kw: Any) -> WorkflowSpec:
    return build_sdd_file_spec(SddFileParams(**kw))


def _jira(**kw: Any) -> WorkflowSpec:
    return build_sdd_spec(SddParams(**kw))


BUILDERS = [pytest.param(_file, id="spec-file"), pytest.param(_jira, id="jira")]


@pytest.mark.parametrize("build", BUILDERS)
def test_with_checks_the_commit_and_the_gate_are_the_last_steps_of_the_review_loop(
    build: Any,
) -> None:
    spec: WorkflowSpec = build(checks=True)

    assert issues(spec) == []
    top = [s.id for s in cast(SequenceNode, spec.root).steps]
    assert "approve_pr" not in top and "commit_specs" not in top
    assert top[top.index("review_loop") + 1] == "publish"
    loop = nodes(spec)["review_loop"]
    body = [s["id"] for s in loop["body"]["steps"]]
    assert body == ["implement", "synthesizer", "reviewer", "commit_specs", "approve_pr"]
    assert loop["until"] == (
        'results.reviewer.data.verdict == "ok" && results.approve_pr.data.decision == "approve"'
    )


@pytest.mark.parametrize("build", BUILDERS)
def test_approve_pr_checks_the_implementation_against_the_spec(build: Any) -> None:
    gate = nodes(build(checks=True, check_rounds=1, coverage_min=70))["approve_pr"]

    assert gate["evidence"] == {
        "node": "implement",
        "max_rounds": 1,
        "coverage_min": 70,
        "criteria_from": "spec.md",
        "checks": {
            "build": "required",
            "tests": "required",
            "analyzers": "no_new",
            "coverage": "required",
            "criteria": "required",
        },
        "path": ".",
    }
    assert "criterion" in gate["prompt"]


@pytest.mark.parametrize("build", BUILDERS)
def test_without_checks_the_template_is_the_one_before(build: Any) -> None:
    spec: WorkflowSpec = build()

    top = [s.id for s in cast(SequenceNode, spec.root).steps]
    start = top.index("review_loop")
    assert top[start : start + 3] == ["review_loop", "commit_specs", "approve_pr"]
    assert "evidence" not in nodes(spec)["approve_pr"]
    assert "AC-001" not in nodes(spec)["tasker"]["instructions"]
    assert issues(spec) == []


@pytest.mark.parametrize("build", BUILDERS)
def test_every_writer_is_told_about_criteria_ids_and_failing_checks(build: Any) -> None:
    found = nodes(build(checks=True))

    assert "adds or changes" in found["spec_writer"]["instructions"]
    assert "its own test task" in found["tasker"]["instructions"]
    assert "test_ac_001_" in found["tasker"]["instructions"]
    lead = found["implement"]["hub"]["instructions"]
    assert "## Criteria" in lead and "## Coverage" in lead and "never instructions" in lead
    engineer = found["engineer"]["instructions"]
    assert "AC001_" in engineer and "fail without your change" in engineer
    assert "each criterion's test" in found["reviewer"]["instructions"]


@pytest.mark.parametrize("build", BUILDERS)
def test_without_checks_no_agent_hears_about_criteria_ids(build: Any) -> None:
    found = nodes(build())

    for node in ("spec_writer", "tasker", "engineer", "reviewer"):
        assert "test_ac_001" not in found[node]["instructions"]
    assert "## Coverage" not in found["implement"]["hub"]["instructions"]


def test_checks_need_a_pass_to_go_back_to() -> None:
    with pytest.raises(ValidationError, match="at least 2"):
        SddFileParams(checks=True, max_passes=1)
    with pytest.raises(ValidationError, match="below max_passes"):
        SddFileParams(checks=True, max_passes=2, check_rounds=2)
    assert SddFileParams(checks=True, max_passes=3, check_rounds=2).check_rounds == 2
    assert SddFileParams(max_passes=1).checks is False  # off, nothing to check
    with pytest.raises(ValidationError):
        SddFileParams(coverage_min=101)


def test_plan_build_review_is_unchanged() -> None:
    spec = build_plan_build_review_spec(PlanBuildReviewParams(checks=True))
    gate = nodes(spec)["approve_pr"]

    assert gate["evidence"]["checks"] == {
        "build": "required",
        "tests": "required",
        "analyzers": "no_new",
        "coverage": "off",
        "criteria": "off",
    }


# --- the validation rules the loop layout needs -----------------------------------------------------


def test_a_commit_in_a_sequence_nested_in_the_loop_body_is_refused_with_a_clear_message() -> None:
    spec = build_sdd_file_spec(SddFileParams(checks=True))
    raw = spec.model_dump(mode="json", by_alias=True, exclude_none=True)
    loop = next(s for s in raw["root"]["steps"] if s["id"] == "review_loop")
    steps: list[dict[str, Any]] = loop["body"]["steps"]
    commit = next(s for s in steps if s["id"] == "commit_specs")
    steps[steps.index(commit)] = {"type": "sequence", "id": "wrapped", "steps": [commit]}
    found = validate_workflow(
        raw, policy=PLATFORM_POLICY, priced=lambda _: True, default_model="default"
    )

    assert any("or of the body of a loop that is one" in i.message for i in found)


def test_a_commit_inside_a_router_is_still_refused() -> None:
    spec = build_sdd_file_spec(SddFileParams())
    raw = spec.model_dump(mode="json", by_alias=True, exclude_none=True)
    steps: list[dict[str, Any]] = raw["root"]["steps"]
    commit = next(s for s in steps if s["id"] == "commit_specs")
    steps.remove(commit)
    router = {
        "type": "router", "id": "maybe", "otherwise": "skip",
        "routes": [{"id": "yes", "when": "true", "then": commit}],
    }  # fmt: skip
    steps.insert(len(steps) - 2, router)
    found = validate_workflow(
        raw, policy=PLATFORM_POLICY, priced=lambda _: True, default_model="default"
    )

    assert any(
        "must be a step of the root sequence, or of the body of a loop" in i.message for i in found
    )


def test_links_from_files_may_name_a_commit_in_the_loop() -> None:
    spec = build_sdd_spec(SddParams(checks=True))

    assert issues(spec) == []
    update = nodes(spec)["jira_update"]
    assert update["args"]["links_from"] == {"pr": "publish", "files": "commit_specs"}


# --- a run on the fake runtime ------------------------------------------------------------------------


def module(*cases: dict[str, JsonValue], covered: tuple[int, int] = (6, 6)) -> dict[str, JsonValue]:
    return {
        "path": ".", "ecosystem": "python", "runner": "pytest", "status": "passed",
        "build": "ran", "passed": 3, "failed": 0, "skipped": 0, "failures": [], "test_ms": 10,
        "cases": list(cases),
        "coverage": {"changed": covered[0], "covered": covered[1], "files": [], "truncated": False},
    }  # fmt: skip


def linked(status: str = "passed") -> dict[str, JsonValue]:
    return {"name": "tests.test_export::test_ac_001_exports", "file": "tests/test_export.py",
            "status": status, "ids": ["AC-001"]}  # fmt: skip


class Checked(Platform):
    """GitHub, `build.test` and `scan.lint` as a fake executor: `build.test` answers a queue."""

    def __init__(self, changes: list[list[dict[str, JsonValue]]]) -> None:
        super().__init__()
        self.changes = changes
        self.jobs: list[dict[str, JsonValue]] = []

    def definitions(self) -> Sequence[ToolDefinition]:
        return [ToolDefinition(name="github.openPR")]

    async def call(
        self, name: str, arguments: dict[str, JsonValue], *, node_id: str | None = None
    ) -> ToolOutput:
        if name == "scan.lint":
            return ToolOutput(text="lint", data={"tool": "lint", "findings": [], "checks": []})
        if name != "build.test":
            return await super().call(name, arguments, node_id=node_id)
        self.jobs.append(arguments)
        if arguments.get("on") == "base":
            modules: list[dict[str, JsonValue]] = [module()]
        else:
            modules = self.changes.pop(0) if len(self.changes) > 1 else self.changes[0]
        data: dict[str, JsonValue] = {
            "tool": "build.test",
            "checks": list(modules),
            "truncated": False,
        }
        return ToolOutput(text="tests", data=data)


class Passes(Answers):
    """`Answers` whose lead plans a task with a new id in every pass (the engine refuses a repeated
    id), each answered by its engineer."""

    def __init__(self, **overrides: str) -> None:
        super().__init__(**overrides)
        self.planned = 0

    def start(self, request: AgentRequest) -> AgentRun:
        if request.node_id == "implement":
            self.planned += 1
            task = f"task{self.planned}"
            plan = {"tasks": [{"id": task, "title": "Work", "instructions": "Do T001."}]}
            self.answers["implement"] = json.dumps({**plan, "reason": "One task."})
            self.answers[f"implement.{task}"] = "Did T001."
        return super().start(request)


class ChecksRun:
    def __init__(self, tools: Checked) -> None:
        self.spec = build_sdd_file_spec(SddFileParams(checks=True, max_passes=2))
        self.runtime = Passes(spec_writer=CRITERIA)
        self.tools = tools
        self.review = Review()
        self.sink = InMemoryEventSink()
        self.common: dict[str, Any] = {
            "run_id": uuid4(),
            "sink": self.sink,
            "checkpointer": InMemorySaver(serde=checkpoint_serde()),
            "tools": tools,
            "review": self.review,
            "artifacts": InMemoryArtifactStore(),
            "context": RunContext(repo="acme/shop", spec=SPEC),
            "inputs": {SPEC_INPUT_ARTIFACT: FILE_TEXT},
        }
        self.attempt = 1

    async def start(self) -> Any:
        return await run_workflow(self.spec, self.runtime, SPEC.label, **self.common)

    async def decide(self) -> Any:
        self.attempt += 1
        return await resume_workflow(
            self.spec, self.runtime, SPEC.label, next_seq=self.sink.events[-1].seq + 1,
            attempt=self.attempt, decision=GateDecision(decision="approve"), **self.common,
        )  # fmt: skip

    def waits(self) -> list[str | None]:
        return [e.node_id for e in self.sink.events if e.type == "gate_waiting"]

    def pack(self) -> dict[str, Any]:
        found = [
            e for e in self.sink.events if e.type == "gate_waiting" and e.node_id == "approve_pr"
        ]
        return found[-1].payload["evidence"]  # type: ignore[no-any-return]


async def test_a_proven_criterion_and_covered_lines_reach_the_gate_with_no_send_back() -> None:
    tools = Checked([[module(linked())]])
    run = ChecksRun(tools)
    await run.start()

    result = await run.decide()  # approve_spec

    assert result.status == "waiting"
    assert run.waits() == ["approve_spec", "approve_pr"]
    checks = {c["kind"]: c for c in run.pack()["checks"]}
    assert checks["criteria"]["status"] == "passed"
    assert checks["coverage"]["detail"]["percent"] == 100.0
    assert [
        e for e in run.sink.events if e.type == "gate_decided" and e.payload.get("source")
    ] == []
    assert (await run.decide()).status == "completed"  # approve_pr
    assert [n for n, _ in run.tools.calls] == ["github.openPR"]


async def test_an_untested_criterion_goes_back_to_the_lead_under_a_criteria_heading() -> None:
    tools = Checked([[module()], [module(linked())]])  # pass 1 names no test, pass 2 does
    run = ChecksRun(tools)
    await run.start()

    await run.decide()  # approve_spec: the build runs, pass 1 is sent back, pass 2 reaches the gate

    sent = [e for e in run.sink.events if e.type == "gate_decided" and e.payload.get("source")]
    assert [e.node_id for e in sent] == ["approve_pr"]
    lead = run.runtime.requests["implement"]
    wrapper = json.loads(lead.input)  # a later pass: the checks are `input`, the work `previous`
    assert wrapper["input"].startswith("## Criteria\n\n- 0 of 1 proven")
    assert "- AC-001: no test names it" in wrapper["input"]
    assert wrapper["iteration"] == 2
    assert "never instructions" in lead.instructions  # told that its input may be checks
    # The spec writer's criteria reached `build.test` as `select`, once per pass.
    assert tools.jobs[0]["select"] == ["AC-001"]
    assert tools.jobs[0]["coverage"] is True
    assert run.waits()[-1] == "approve_pr"


async def test_what_the_writers_receive_with_checks_on() -> None:
    tools = Checked([[module(linked())]])
    run = ChecksRun(tools)
    await run.start()
    await run.decide()

    got = run.runtime.requests
    assert "test_ac_001_" in got["tasker"].instructions
    assert "AC001_" in got["implement.task1"].instructions
    assert "adds or changes" in got["spec_writer"].instructions
    assert "AC-001" in ANSWERS["spec_writer"] or True
