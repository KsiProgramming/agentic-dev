"""The orchestrator's integration branch at runtime (6.3): the completed tasks' branches merged
into one, in plan order, before the join decides; on the fake runtime with a fake integrator."""

import asyncio
import json
from collections.abc import Collection, Mapping, Sequence
from typing import cast
from uuid import uuid4

import pytest
from pydantic import JsonValue

from agentic_engine.artifacts import InMemoryArtifactStore
from agentic_engine.events import InMemoryEventSink
from agentic_engine.gate import FileChange, FileEdit, GateDecision
from agentic_engine.graph import WorkflowRunResult, resume_workflow, run_workflow
from agentic_engine.graph.compile import recursion_limit
from agentic_engine.integrate import (
    Integration,
    IntegrationError,
    MergeRequest,
    conflict_error,
)
from agentic_engine.spec import WorkflowSpec
from agentic_runtime import AgentRequest, AgentRun, Message
from agentic_runtime.fake import ECHO_USAGE, CallTool, Delay, FakeRuntime, Script

from .test_orchestrator import HUB, Desk, TaskDoneSink, Team, agent, orchestrator, plan, saver, spec
from .test_orchestrator_replan import Replanner, ends, replanning

WRITER = agent("fixer", tools=["repo.write_file"])
BRANCH = f"agent/run/{HUB}"


class Merger:
    """A fake `BranchIntegrator`: a source merges unless its task is in `conflicts` (with those
    paths) or `empty`; it records each call's keys and messages, what it merged, and the tasks it
    was asked to start from the integration branch (6.9)."""

    def __init__(
        self,
        conflicts: Mapping[str, list[str]] | None = None,
        empty: Collection[str] = (),
        error: str | None = None,
    ) -> None:
        self._conflicts = dict(conflicts or {})
        self._empty = set(empty)
        self._error = error
        self.calls: list[list[MergeRequest]] = []
        self.merged: list[str] = []
        self.started: list[list[str]] = []

    async def integrate(self, orchestrator_id: str, sources: Sequence[MergeRequest]) -> Integration:
        self.calls.append(list(sources))
        if self._error is not None:
            raise IntegrationError(self._error)
        merged: list[str] = []
        empty: list[str] = []
        conflicts: dict[str, list[str]] = {}
        for source in sources:
            task = source.key.partition(".")[2]
            if task in self._conflicts:
                conflicts[source.key] = self._conflicts[task]
            elif task in self._empty:
                empty.append(source.key)
            else:
                merged.append(source.key)
                if source.key not in self.merged:
                    self.merged.append(source.key)
        return Integration(
            branch=f"agent/run/{orchestrator_id}",
            head=f"{len(self.merged):040d}",
            merged=merged,
            empty=empty,
            conflicts=conflicts,
        )

    async def start_tasks(self, orchestrator_id: str, keys: Sequence[str]) -> None:
        self.started.append(list(keys))

    @property
    def keys(self) -> list[list[str]]:
        return [[s.key for s in call] for call in self.calls]


def writing(*tasks: str) -> dict[str, Script]:
    """Scripts for writer tasks that each write one file."""
    return {
        f"{HUB}.{t}": [CallTool("repo.write_file", {"path": f"{t}.py"}), Message(text=f"fixed {t}")]
        for t in tasks
    }


async def run(
    flow: WorkflowSpec,
    team: Team,
    merger: Merger | None,
    sink: InMemoryEventSink | None = None,
    desk: Desk | None = None,
) -> WorkflowRunResult:
    return await run_workflow(
        flow,
        team,
        "the repo",
        sink=sink,
        checkpointer=saver(),
        artifacts=InMemoryArtifactStore(),
        tools=desk,
        integrator=merger,
    )


def integrations(sink: InMemoryEventSink) -> list[dict[str, JsonValue]]:
    return [e.payload for e in sink.events if e.type == "branch_integrated"]


async def test_completed_tasks_merge_in_plan_order_into_one_branch() -> None:
    """Done when (6.3): parallel writers produce one branch, which a PR then publishes."""
    desk, merger, sink = Desk(), Merger(), InMemoryEventSink()
    team = Team(plan("a", "b", "c"), scripts=writing("a", "b", "c"), delays={"a": 0.05}, tools=desk)

    result = await run(spec(orchestrator(WRITER)), team, merger, sink, desk)

    assert result.status == "completed", result.results[HUB].error
    assert merger.keys == [["fix.a", "fix.b", "fix.c"]]
    assert [s.message for s in merger.calls[0]] == [
        "Merge task 'a': Fix a",
        "Merge task 'b': Fix b",
        "Merge task 'c': Fix c",
    ]
    [integrated] = integrations(sink)
    assert integrated == {
        "round": 1,
        "branch": BRANCH,
        "head": f"{3:040d}",
        "merged": ["a", "b", "c"],
        "empty": [],
        "conflicts": [],
    }
    data = result.results[HUB].data
    assert data is not None
    assert data["writers"] == [HUB]
    assert data["branch"] == BRANCH and data["merged"] == ["a", "b", "c"]
    [end] = [e.payload for e in sink.events if e.type == "node_completed" and e.node_id == HUB]
    assert end == {
        "tasks": 3,
        "completed": 3,
        "rounds": 1,
        "branch": BRANCH,
        "merged": ["a", "b", "c"],
    }
    # Merged before the join decided.
    types = [e.type for e in sink.events if e.node_id == HUB]
    assert types.index("branch_integrated") < types.index("node_completed")


async def test_a_body_that_does_not_write_has_no_integration() -> None:
    merger, sink = Merger(), InMemoryEventSink()

    result = await run(spec(orchestrator(agent("worker"))), Team(plan("a", "b")), merger, sink)

    assert result.status == "completed"
    assert merger.calls == [] and integrations(sink) == []
    data = result.results[HUB].data
    assert data is not None and data["writers"] == [] and "branch" not in data


async def test_tasks_with_nothing_to_merge_are_empty_not_failed() -> None:
    desk, merger, sink = Desk(), Merger(empty=["b"]), InMemoryEventSink()
    team = Team(plan("a", "b"), scripts=writing("a", "b"), tools=desk)

    result = await run(spec(orchestrator(WRITER)), team, merger, sink, desk)

    assert result.status == "completed"
    [integrated] = integrations(sink)
    assert integrated["merged"] == ["a"] and integrated["empty"] == ["b"]
    assert ends(sink)["b"] == ("completed", None)
    data = result.results[HUB].data
    assert data is not None and data["writers"] == [HUB]


async def test_with_nothing_merged_there_is_no_writer_for_a_gate() -> None:
    desk, merger = Desk(), Merger(empty=["a"])
    team = Team(plan("a"), scripts=writing("a"), tools=desk)

    result = await run(spec(orchestrator(WRITER)), team, merger, desk=desk)

    data = result.results[HUB].data
    assert data is not None and data["writers"] == [] and data["merged"] == []


async def test_an_empty_plan_merges_nothing() -> None:
    merger, sink = Merger(), InMemoryEventSink()

    result = await run(spec(orchestrator(WRITER)), Team(plan()), merger, sink)

    assert result.status == "completed"
    assert merger.calls == [] and integrations(sink) == []


async def test_a_conflict_fails_its_task_and_a_replan_retries_it() -> None:
    desk = Desk()
    merger = Merger(conflicts={"b": ["README.md", "src/app.py"]})
    team = Replanner(
        [plan("a", "b", "c"), plan("b2")], scripts=writing("a", "b", "c", "b2"), tools=desk
    )
    sink = InMemoryEventSink()

    result = await run(spec(replanning(WRITER)), team, merger, sink, desk)

    assert result.status == "completed", result.results[HUB].error
    error = "conflicts with earlier tasks on README.md, src/app.py"
    first, second = integrations(sink)
    assert first["merged"] == ["a", "c"]
    assert first["conflicts"] == [{"id": "b", "paths": ["README.md", "src/app.py"]}]
    # The worker itself completed: the conflict is the integration's, not a second end.
    assert ends(sink)["b"] == ("completed", None)
    replan = next(e.payload for e in sink.events if e.type == "replan_started")
    assert replan["failed"] == [{"id": "b", "error": error}]
    told = json.loads(team.hubs[1].input)
    assert [(t["id"], t["status"], t.get("error")) for t in told["tasks"]] == [
        ("a", "completed", None),
        ("b", "failed", error),
        ("c", "completed", None),
    ]
    # Round 2 merges on top; the conflicting task is not offered again.
    assert merger.keys[1] == ["fix.a", "fix.c", "fix.b2"]
    # The retry starts from the integration branch, so it builds on what merged (6.9).
    assert merger.started == [["fix.b2"]]
    assert second["round"] == 2 and second["merged"] == ["a", "c", "b2"]
    data = result.results[HUB].data
    assert data is not None and data["merged"] == ["a", "c", "b2"]
    plan_status = [(p["id"], p["status"]) for p in cast(list[dict[str, JsonValue]], data["plan"])]
    assert plan_status == [
        ("a", "completed"),
        ("b", "failed"),
        ("c", "completed"),
        ("b2", "completed"),
    ]
    assert result.results[HUB].text == "fixed a\n\nfixed c\n\nfixed b2"


async def test_a_conflict_with_no_replan_left_fails_the_orchestrator() -> None:
    desk, merger, sink = Desk(), Merger(conflicts={"b": ["README.md"]}), InMemoryEventSink()
    team = Team(plan("a", "b"), scripts=writing("a", "b"), tools=desk)

    result = await run(spec(orchestrator(WRITER)), team, merger, sink, desk)

    assert result.status == "failed"
    assert result.results[HUB].error == "task 'b' conflicts with earlier tasks on README.md"
    [failed] = [e.payload for e in sink.events if e.type == "node_failed" and e.node_id == HUB]
    assert failed == {"error": "task 'b' conflicts with earlier tasks on README.md"}


async def test_an_integration_that_cannot_be_built_fails_the_orchestrator() -> None:
    desk, merger, sink = Desk(), Merger(error="git could not merge"), InMemoryEventSink()
    team = Team(plan("a"), scripts=writing("a"), tools=desk)

    result = await run(spec(orchestrator(WRITER), agent("after")), team, merger, sink, desk)

    assert result.status == "failed"
    why = "cannot build the integration branch: git could not merge"
    assert result.results[HUB].error == why
    assert "after" not in result.results
    assert [e.type for e in sink.events if e.node_id == HUB][-1] == "node_failed"


class Review:
    """A gate review that shows one file per writer it is asked about."""

    def __init__(self) -> None:
        self.asked: list[list[str]] = []
        self.applied: list[list[FileEdit]] = []

    async def changes(self, ran: Sequence[str]) -> list[FileChange]:
        self.asked.append(list(ran))
        return [
            FileChange(node_id=n, path="a.py", status="added", editable=True, after="x")
            for n in ran
            if n == HUB
        ]

    async def apply(self, gate_id: str, edits: Sequence[FileEdit]) -> dict[str, str]:
        self.applied.append(list(edits))
        return {e.node_id: "abc123" for e in edits}


async def test_a_gate_after_it_shows_and_edits_the_integration_branch() -> None:
    desk, merger, review = Desk(), Merger(), Review()
    team = Team(plan("a", "b"), scripts=writing("a", "b"), tools=desk)
    flow = spec(orchestrator(WRITER), {"type": "gate", "id": "approve", "title": "OK?"})
    checkpointer, run_id, sink = saver(), uuid4(), InMemoryEventSink()
    common = {"tools": desk, "review": review, "integrator": merger, "checkpointer": checkpointer}

    paused = await run_workflow(flow, team, "go", run_id=run_id, sink=sink, **common)  # type: ignore[arg-type]

    assert paused.status == "waiting"
    assert review.asked == [[HUB]]
    [waiting] = [e for e in sink.events if e.type == "gate_waiting"]
    changes = cast(list[dict[str, JsonValue]], waiting.payload["changes"])
    assert [c["node_id"] for c in changes] == [HUB]

    edit = FileEdit(node_id=HUB, path="a.py", content="y")
    done = await resume_workflow(
        flow,
        team,
        "go",
        run_id=run_id,
        sink=sink,
        next_seq=sink.events[-1].seq + 1,
        attempt=2,
        decision=GateDecision(decision="approve", edits=[edit]),
        **common,  # type: ignore[arg-type]
    )

    assert done.status == "completed"
    assert review.applied == [[edit]]
    assert len(merger.calls) == 1  # the continued run does not merge again


async def test_a_resumed_run_merges_every_task_once() -> None:
    """AC-8 with an integration branch: a run cut off after task `a` finished runs `b` and
    merges both; the integrator is asked for every completed task and merges none twice."""
    desk, merger = Desk(), Merger()
    flow, checkpointer, run_id = spec(orchestrator(WRITER)), saver(), uuid4()
    slow_b = {**writing("a"), f"{HUB}.b": [Delay(60), *writing("b")[f"{HUB}.b"]]}
    first = Team(plan("a", "b"), scripts=slow_b, tools=desk)
    sink = TaskDoneSink(0)
    task = asyncio.create_task(
        run_workflow(
            flow,
            first,
            "go",
            run_id=run_id,
            sink=sink,
            checkpointer=checkpointer,
            tools=desk,
            integrator=merger,
        )
    )
    await asyncio.wait_for(sink.done.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    second = Team(plan("x"), scripts=writing("b"), tools=desk)
    result = await resume_workflow(
        flow,
        second,
        "go",
        run_id=run_id,
        sink=sink,
        checkpointer=checkpointer,
        next_seq=sink.events[-1].seq + 1,
        attempt=2,
        tools=desk,
        integrator=merger,
    )

    assert result.status == "completed", result.results[HUB].error
    assert merger.keys == [["fix.a", "fix.b"]]
    assert merger.merged == ["fix.a", "fix.b"]


def test_a_conflict_error_names_at_most_ten_paths() -> None:
    paths = [f"f{i}.py" for i in range(12)]

    assert conflict_error(paths) == (
        "conflicts with earlier tasks on " + ", ".join(paths[:10]) + " and 2 more"
    )
    assert conflict_error(["a.py"]) == "conflicts with earlier tasks on a.py"


def test_a_writing_body_takes_one_more_step_per_round() -> None:
    assert recursion_limit(spec(orchestrator(WRITER))) == 4 + 10
    assert recursion_limit(spec(replanning(WRITER, max_rounds=2))) == 12 + 10
    assert recursion_limit(spec(orchestrator(agent("worker")))) == 3 + 10


class ReadingTeam(Team):
    """A `Team` whose `Reviewer`, whatever id it calls as, reads one file and says OK."""

    def start(self, request: AgentRequest) -> AgentRun:
        if request.role != "Reviewer":
            return super().start(request)
        self.requests.append(request)
        script = [CallTool("repo.read_file", {"path": "a.py"}), Message(text="OK"), ECHO_USAGE]
        return FakeRuntime({request.node_id: script}, tools=self._tools).start(request)


async def test_a_reader_after_the_orchestrator_reads_its_integration_branch() -> None:
    """6.9: once the orchestrator merged a task, a node that only reads the repo calls its tools
    as the orchestrator, so they read the integration branch (the work merged), not the run's
    checkout; one before it calls as itself."""
    desk, merger = Desk(), Merger()
    before = agent("survey", role="Reviewer", tools=["repo.read_file"])
    after = agent("reviewer", role="Reviewer", tools=["repo.read_file"])
    team = ReadingTeam(plan("a"), scripts=writing("a"), tools=desk)

    result = await run(spec(before, orchestrator(WRITER), after), team, merger, desk=desk)

    assert result.status == "completed", result.results[HUB].error
    reads = [node for name, node in desk.calls if name == "repo.read_file"]
    assert reads == ["survey", HUB]


async def test_a_reader_after_an_orchestrator_that_merged_nothing_reads_the_checkout() -> None:
    desk, merger = Desk(), Merger(empty=["a"])
    after = agent("reviewer", role="Reviewer", tools=["repo.read_file"])
    team = ReadingTeam(plan("a"), scripts=writing("a"), tools=desk)

    await run(spec(orchestrator(WRITER), after), team, merger, desk=desk)

    assert [node for name, node in desk.calls if name == "repo.read_file"] == ["reviewer"]
