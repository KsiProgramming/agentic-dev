"""Writers' commits saved outside the sandbox (12.2): every step that may commit asks the run's
`BranchSaver` to save its branches before the step is checkpointed, and each save is an event."""

from uuid import uuid4

from agentic_engine.artifacts import InMemoryArtifactStore
from agentic_engine.branches import BranchSaved, BranchSaveFailed, BranchSaves
from agentic_engine.events import InMemoryEventSink
from agentic_engine.gate import GateDecision
from agentic_engine.graph import compile_workflow, resume_workflow, run_workflow, thread_config
from agentic_engine.spec import parse_spec
from agentic_runtime.fake import FakeRuntime

from .test_orchestrator import HUB, Desk, Team, agent, orchestrator, plan, saver, spec
from .test_orchestrator_integrate import WRITER, Merger, writing

RUN = uuid4()


class Recorder:
    """A fake `BranchSaver`: each call records the last event written before it, and answers
    the next of `answers` (nothing saved once they run out)."""

    def __init__(self, sink: InMemoryEventSink, *answers: BranchSaves | Exception) -> None:
        self._sink = sink
        self._answers = list(answers)
        self.after: list[tuple[str, str | None]] = []

    async def save(self, *, step: str | None = None) -> BranchSaves:
        last = self._sink.events[-1]
        self.after.append((last.type, last.node_id))
        answer = self._answers.pop(0) if self._answers else BranchSaves()
        if isinstance(answer, Exception):
            raise answer
        return answer


def saved(key: str, version: int = 1) -> BranchSaved:
    return BranchSaved(
        key=key,
        branch=f"agent/run/{key}",
        kind="integration" if key == HUB else "writer",
        version=version,
        head="1" * 40,
        commits=1,
        size=120,
    )


async def test_each_step_saves_after_it_ends_and_each_save_is_logged() -> None:
    sink = InMemoryEventSink()
    recorder = Recorder(
        sink,
        BranchSaves(saved=[saved("writer")]),
        BranchSaves(failed=[BranchSaveFailed(key="writer", branch="b", error="too large")]),
    )
    flow = spec(agent("writer", tools=["repo.write_file"]), agent("reviewer"))

    result = await run_workflow(flow, FakeRuntime(), "go", sink=sink, saver=recorder)

    assert result.status == "completed"
    assert recorder.after == [("node_completed", "writer"), ("node_completed", "reviewer")]
    logged = [(e.type, e.node_id, e.payload) for e in sink.events if e.type.startswith("branch_")]
    assert logged == [
        ("branch_saved", "writer", saved("writer").model_dump(mode="json")),
        ("branch_save_failed", "writer", {"key": "writer", "branch": "b", "error": "too large"}),
    ]


async def test_a_step_s_branches_are_saved_before_it_is_checkpointed() -> None:
    """A crash between the two cannot leave a step checkpointed with its commits unsaved."""
    checkpointer, sink = saver(), InMemoryEventSink()
    flow = spec(agent("writer", tools=["repo.write_file"]), agent("reviewer"))
    reader = compile_workflow(flow, FakeRuntime(), checkpointer=checkpointer)
    seen: list[list[str]] = []

    class Checking(Recorder):
        async def save(self, *, step: str | None = None) -> BranchSaves:
            state = await reader.aget_state(thread_config(RUN))
            seen.append(list(state.values.get("order", [])))
            return await super().save(step=step)

    await run_workflow(
        flow, FakeRuntime(), "go", run_id=RUN, sink=sink, checkpointer=checkpointer,
        saver=Checking(sink),
    )  # fmt: skip

    assert seen == [[], ["writer"]]


async def test_a_saver_that_breaks_does_not_fail_the_step() -> None:
    sink = InMemoryEventSink()
    recorder = Recorder(sink, RuntimeError("database gone"))

    result = await run_workflow(
        spec(agent("writer")), FakeRuntime(), "go", sink=sink, saver=recorder
    )

    assert result.status == "completed"
    assert not [e for e in sink.events if e.type.startswith("branch_")]


async def test_map_items_and_parallel_branches_save_as_they_end() -> None:
    sink = InMemoryEventSink()
    recorder = Recorder(sink)
    flow = parse_spec(
        {
            "spec_version": "0",
            "id": "fan",
            "name": "Fan",
            "root": {
                "type": "sequence",
                "id": "main",
                "steps": [
                    {
                        "type": "map",
                        "id": "each",
                        "over": '["a", "b"]',
                        "body": agent("item"),
                        "max_concurrency": 2,
                    },
                    {
                        "type": "parallel",
                        "id": "both",
                        "join": "all",
                        "branches": [agent("left"), agent("right")],
                    },
                ],
            },
        }
    )

    result = await run_workflow(
        flow, FakeRuntime(), "go", sink=sink, artifacts=InMemoryArtifactStore(), saver=recorder
    )

    assert result.status == "completed"
    assert sorted(recorder.after) == sorted(
        [
            ("map_item_completed", "each"),
            ("map_item_completed", "each"),
            ("parallel_branch_completed", "both"),
            ("parallel_branch_completed", "both"),
        ]
    )


async def test_an_orchestrator_saves_after_each_task_and_after_merging() -> None:
    desk, merger, sink = Desk(), Merger(), InMemoryEventSink()
    team = Team(plan("a", "b"), scripts=writing("a", "b"), tools=desk)
    recorder = Recorder(
        sink,
        BranchSaves(saved=[saved(f"{HUB}.a")]),
        BranchSaves(saved=[saved(f"{HUB}.b")]),
        BranchSaves(saved=[saved(HUB)]),
    )

    result = await run_workflow(
        spec(orchestrator(WRITER)),
        team,
        "the repo",
        sink=sink,
        checkpointer=saver(),
        artifacts=InMemoryArtifactStore(),
        tools=desk,
        integrator=merger,
        saver=recorder,
    )

    assert result.status == "completed", result.results[HUB].error
    assert [t for t, _ in recorder.after] == [
        "task_completed",
        "task_completed",
        "branch_integrated",
    ]
    logged = [
        (e.node_id, e.payload["key"], e.payload["kind"])
        for e in sink.events
        if e.type == "branch_saved"
    ]
    assert logged == [
        (HUB, f"{HUB}.a", "writer"),
        (HUB, f"{HUB}.b", "writer"),
        (HUB, HUB, "integration"),
    ]


async def test_a_gate_saves_after_it_is_decided_not_when_it_pauses() -> None:
    """An approval's edits are committed by the gate step; they are saved once it ends."""
    checkpointer, sink = saver(), InMemoryEventSink()
    recorder = Recorder(sink)
    flow = spec(agent("writer"), {"type": "gate", "id": "approve", "title": "Go on?"})

    paused = await run_workflow(
        flow, FakeRuntime(), "go", run_id=RUN, sink=sink, checkpointer=checkpointer, saver=recorder
    )
    assert paused.status == "waiting"
    assert recorder.after == [("node_completed", "writer")]

    done = await resume_workflow(
        flow,
        FakeRuntime(),
        "go",
        run_id=RUN,
        sink=sink,
        checkpointer=checkpointer,
        next_seq=len(sink.events) + 1,
        attempt=2,
        decision=GateDecision(decision="approve"),
        saver=recorder,
    )

    assert done.status == "completed"
    assert recorder.after == [("node_completed", "writer"), ("node_completed", "approve")]
