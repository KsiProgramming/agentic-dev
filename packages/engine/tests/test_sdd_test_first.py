# ruff: noqa: E501
"""The SDD templates with `test_first` (13.5): a test writer writes the acceptance criteria's tests
after the task list, a person approves them at `approve_tests`, and `implement` starts from them.
The run tests assert what the test writer, the lead and an engineer receive (lessons, rule 1)."""

from typing import Any, cast
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

from agentic_engine.agent import RunContext
from agentic_engine.artifacts import InMemoryArtifactStore
from agentic_engine.events import InMemoryEventSink
from agentic_engine.gate import GateComment, GateDecision
from agentic_engine.graph import checkpoint_serde, resume_workflow, run_workflow
from agentic_engine.spec import SPEC_INPUT_ARTIFACT, SequenceNode, WorkflowSpec
from agentic_engine.templates import (
    SddFileParams,
    SddParams,
    build_sdd_file_spec,
    build_sdd_spec,
)

from .test_sdd_checks import CRITERIA, Checked, Passes, issues, linked, module, nodes
from .test_sdd_spec_file import FILE_TEXT, SPEC, Review


def _file(**kw: Any) -> WorkflowSpec:
    return build_sdd_file_spec(SddFileParams(**kw))


def _jira(**kw: Any) -> WorkflowSpec:
    return build_sdd_spec(SddParams(**kw))


BUILDERS = [pytest.param(_file, id="spec-file"), pytest.param(_jira, id="jira")]


@pytest.mark.parametrize("build", BUILDERS)
def test_with_test_first_the_tests_come_after_the_tasks_and_before_the_review_loop(
    build: Any,
) -> None:
    spec: WorkflowSpec = build(checks=True, test_first=True)

    assert issues(spec) == []
    top = [s.id for s in cast(SequenceNode, spec.root).steps]
    assert top[top.index("tasker") + 1 : top.index("tasker") + 3] == ["tests_loop", "review_loop"]
    found = nodes(spec)
    loop = found["tests_loop"]
    assert [s["id"] for s in loop["body"]["steps"]] == ["test_writer", "approve_tests"]
    assert loop["until"] == 'results.approve_tests.data.decision != "changes"'
    assert loop["max_iterations"] == 3  # the first pass plus the default two revisions
    gate = found["approve_tests"]
    assert (gate["on_changes"], gate["writes"]) == (2, "test-changes.md")
    assert "freezes" in gate["prompt"]
    assert found["implement"]["start_from"] == "test_writer"


@pytest.mark.parametrize("build", BUILDERS)
def test_the_test_writer_reads_the_spec_plan_and_tasks_and_writes_tests_only(build: Any) -> None:
    writer = nodes(build(checks=True, test_first=True))["test_writer"]

    assert writer["reads"] == ["spec.md", "plan.md", "tasks.md"]
    assert {"repo.write_file", "repo.commit", "artifacts.read"} <= set(writer["tools"])
    text = writer["instructions"]
    assert "test files only" in text and "FAIL on the code as it is now" in text
    assert "test_ac_001_" in text and "test-changes.md" in text


@pytest.mark.parametrize("build", BUILDERS)
def test_every_agent_after_the_gate_is_told_the_tests_are_frozen(build: Any) -> None:
    found = nodes(build(checks=True, test_first=True))

    assert "nobody on your team can change them" in found["implement"]["hub"]["instructions"]
    assert "refused and counted" in found["engineer"]["instructions"]
    assert "frozen" in found["reviewer"]["instructions"]
    assert "do not plan test tasks" in found["tasker"]["instructions"]


@pytest.mark.parametrize("build", BUILDERS)
def test_without_test_first_nothing_changes(build: Any) -> None:
    spec: WorkflowSpec = build(checks=True)
    found = nodes(spec)

    assert "tests_loop" not in found and "test_writer" not in found
    assert "start_from" not in found["implement"]
    assert "frozen" not in found["engineer"]["instructions"]
    assert "do not plan test tasks" not in found["tasker"]["instructions"]


def test_test_first_needs_checks() -> None:
    with pytest.raises(ValidationError, match="test_first needs checks"):
        SddFileParams(test_first=True)
    assert SddFileParams(checks=True, test_first=True).test_first is True
    assert SddFileParams().test_first is False


# --- a run on the fake runtime ------------------------------------------------------------------------


class FirstRun:
    def __init__(self) -> None:
        self.spec = build_sdd_file_spec(SddFileParams(checks=True, test_first=True, max_passes=2))
        self.runtime = Passes(spec_writer=CRITERIA, test_writer="Added test_ac_001_exports.")
        self.tools = Checked([[module(linked())]])
        self.review = Review()
        self.sink = InMemoryEventSink()
        self.common: dict[str, Any] = {
            "run_id": uuid4(),
            "sink": self.sink,
            "checkpointer": InMemorySaver(serde=checkpoint_serde()),
            "tools": self.tools,
            "review": self.review,
            "artifacts": InMemoryArtifactStore(),
            "context": RunContext(repo="acme/shop", spec=SPEC),
            "inputs": {SPEC_INPUT_ARTIFACT: FILE_TEXT},
        }
        self.attempt = 1

    async def start(self) -> Any:
        return await run_workflow(self.spec, self.runtime, SPEC.label, **self.common)

    async def decide(self, decision: GateDecision | None = None) -> Any:
        self.attempt += 1
        return await resume_workflow(
            self.spec,
            self.runtime,
            SPEC.label,
            next_seq=self.sink.events[-1].seq + 1,
            attempt=self.attempt,
            decision=decision or GateDecision(decision="approve", decided_by="ada"),
            **self.common,
        )

    def waits(self) -> list[str | None]:
        return [e.node_id for e in self.sink.events if e.type == "gate_waiting"]

    def started(self) -> list[str | None]:
        return [e.node_id for e in self.sink.events if e.type == "node_started"]


async def test_the_tests_are_approved_before_the_builders_start_and_each_agent_gets_what_it_needs() -> (
    None
):
    run = FirstRun()
    await run.start()
    assert run.waits() == ["approve_spec"]
    await run.decide()  # approve_spec: the test writer writes, then the tests wait

    assert run.waits() == ["approve_spec", "approve_tests"]
    assert "implement" not in run.started()  # nothing is built before the tests are approved
    assert run.started().index("tasker") < run.started().index("test_writer")
    writer = run.runtime.requests["test_writer"]
    assert {"repo.write_file", "repo.commit"} <= set(writer.tools)
    assert "FAIL on the code as it is now" in writer.instructions

    await run.decide()  # approve_tests

    assert run.started().index("test_writer") < run.started().index("implement")
    lead = run.runtime.requests["implement"]
    assert "nobody on your team can change them" in lead.instructions
    assert "refused and counted" in run.runtime.requests["implement.task1"].instructions
    assert run.waits()[-1] == "approve_pr"


async def test_a_request_for_changes_at_approve_tests_sends_the_test_writer_the_comments() -> None:
    run = FirstRun()
    await run.start()
    await run.decide()  # approve_spec

    comments = [GateComment(item="tests", text="Cover empty orders.")]
    result = await run.decide(GateDecision(decision="changes", comments=comments))

    assert result.status == "waiting" and result.waiting_at == "approve_tests"
    stored = await run.common["artifacts"].get("test-changes.md")
    assert stored is not None and "Cover empty orders." in stored.content
    assert run.started().count("test_writer") == 2
    assert "implement" not in run.started()
