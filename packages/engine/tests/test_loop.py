"""The `loop` primitive: a reviewer loop stops on its condition or at max iterations (phase 1.9)."""

import asyncio
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.graph import (
    WorkflowRunResult,
    checkpoint_serde,
    resume_workflow,
    run_workflow,
)
from agentic_engine.graph.compile import recursion_limit
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import AgentRequest, Failed, Message
from agentic_runtime.fake import ECHO_USAGE, Delay, FakeRun, FakeRuntime, Script

REVIEW_LOOP = Path(__file__).parent / "fixtures" / "specs" / "valid" / "review-loop.json"


class RoundsRuntime(FakeRuntime):
    """A fake runtime whose nodes answer differently on each call: the n-th call of a node runs
    its n-th script; nodes out of scripts echo their input."""

    def __init__(self, rounds: Mapping[str, Sequence[Script]]) -> None:
        super().__init__()
        self._rounds = {node_id: list(scripts) for node_id, scripts in rounds.items()}

    def start(self, request: AgentRequest) -> FakeRun:
        queue = self._rounds.get(request.node_id)
        if not queue:
            return super().start(request)
        self.requests.append(request)
        return FakeRuntime({request.node_id: queue.pop(0)}).start(request)


def says(*texts: str) -> list[Script]:
    return [[Message(text=t), ECHO_USAGE] for t in texts]


def review_loop() -> WorkflowSpec:
    return parse_spec(json.loads(REVIEW_LOOP.read_text(encoding="utf-8")))


def looping(body: list[object], until: str, max_iterations: int = 3) -> WorkflowSpec:
    """`before`, then a loop `revise` over `body`, then `after`."""
    agent = {"type": "agent", "role": "R", "instructions": "Go."}
    return parse_spec(
        {
            "spec_version": "0",
            "id": "looping",
            "name": "Looping",
            "root": {
                "type": "sequence",
                "id": "main",
                "steps": [
                    {**agent, "id": "before"},
                    {
                        "type": "loop",
                        "id": "revise",
                        "body": {"type": "sequence", "id": "round", "steps": body},
                        "until": until,
                        "max_iterations": max_iterations,
                    },
                    {**agent, "id": "after"},
                ],
            },
        }
    )


def agents(*ids: str) -> list[object]:
    return [{"type": "agent", "id": i, "role": "R", "instructions": "Go."} for i in ids]


def lifecycle(events: list[RunEvent]) -> list[tuple[str, str | None, object]]:
    """Run, node and loop events, with the iteration of loop markers."""
    return [
        (e.type, e.node_id, e.payload.get("iteration"))
        for e in events
        if e.type.startswith(("node_", "run_", "loop_"))
    ]


def loop_end(events: list[RunEvent]) -> RunEvent:
    [end] = [e for e in events if e.node_id == "revise" and e.type.startswith("node_")][1:]
    return end


async def run(
    spec: WorkflowSpec, runtime: FakeRuntime, sink: InMemoryEventSink | None = None
) -> WorkflowRunResult:
    return await run_workflow(spec, runtime, "brief", sink=sink, checkpointer=saver())


def saver() -> InMemorySaver:
    return InMemorySaver(serde=checkpoint_serde())


async def test_review_loop_stops_on_its_condition() -> None:
    """Done when (1.9), first half: the reviewer approves in iteration 2, so the loop stops."""
    runtime = RoundsRuntime(
        {
            "draft": says("summary v1", "summary v2"),
            "review": says("too vague", "APPROVED\nsummary v2"),
        }
    )
    sink = InMemoryEventSink()

    result = await run(review_loop(), runtime, sink)

    assert result.status == "completed"
    assert [r.node_id for r in runtime.requests] == [
        "draft",
        "review",
        "draft",
        "review",
        "publish",
    ]
    assert runtime.requests[-1].input == "APPROVED\nsummary v2"
    assert result.order == ["draft", "review", "draft", "review", "revise", "publish"]
    assert result.results["revise"].data == {"stop_reason": "condition", "iterations": 2}
    assert loop_end(sink.events).payload == {"stop_reason": "condition", "iterations": 2}


async def test_review_loop_stops_at_max_iterations() -> None:
    """Done when (1.9), second half: the reviewer never approves, so the loop stops after
    `max_iterations` and the run goes on."""
    runtime = RoundsRuntime({"review": says("no", "still no", "no again")})
    sink = InMemoryEventSink()

    result = await run(review_loop(), runtime, sink)

    assert result.status == "completed"
    assert [r.node_id for r in runtime.requests].count("draft") == 3
    assert result.results["revise"].data == {"stop_reason": "max_iterations", "iterations": 3}
    assert runtime.requests[-1].node_id == "publish"
    assert runtime.requests[-1].input == "no again"
    assert loop_end(sink.events).type == "node_completed"


async def test_each_iteration_gets_the_previous_output() -> None:
    runtime = RoundsRuntime({"review": says("fix the intro", "fix the outro", "APPROVED")})

    await run(review_loop(), runtime)

    drafts = [r.input for r in runtime.requests if r.node_id == "draft"]
    assert drafts == ["brief", "fix the intro", "fix the outro"]


async def test_loop_events_in_order() -> None:
    runtime = RoundsRuntime({"check": says("no", "ok")})
    sink = InMemoryEventSink()

    await run(looping(agents("work", "check"), 'last == "ok"'), runtime, sink)

    assert lifecycle(sink.events) == [
        ("run_started", None, None),
        ("node_started", "before", None),
        ("node_completed", "before", None),
        ("node_started", "revise", None),
        ("loop_iteration_started", "revise", 1),
        ("node_started", "work", None),
        ("node_completed", "work", None),
        ("node_started", "check", None),
        ("node_completed", "check", None),
        ("loop_condition_evaluated", "revise", 1),
        ("loop_iteration_started", "revise", 2),
        ("node_started", "work", None),
        ("node_completed", "work", None),
        ("node_started", "check", None),
        ("node_completed", "check", None),
        ("loop_condition_evaluated", "revise", 2),
        ("node_completed", "revise", None),
        ("node_started", "after", None),
        ("node_completed", "after", None),
        ("run_completed", None, None),
    ]
    evaluated = [e.payload for e in sink.events if e.type == "loop_condition_evaluated"]
    assert evaluated == [{"iteration": 1, "result": False}, {"iteration": 2, "result": True}]
    assert [e.seq for e in sink.events] == list(range(1, len(sink.events) + 1))


async def test_failing_body_node_stops_the_run() -> None:
    runtime = RoundsRuntime({"check": [[Failed(error="boom")]]})
    sink = InMemoryEventSink()

    result = await run(looping(agents("work", "check"), 'last == "ok"'), runtime, sink)

    assert (result.status, result.stopped_at) == ("failed", "check")
    assert [r.node_id for r in runtime.requests] == ["before", "work", "check"]
    assert not [e for e in sink.events if e.type.startswith("loop_condition")]
    assert sink.events[-1].payload == {"stopped_at": "check"}


async def test_condition_error_fails_the_loop() -> None:
    sink = InMemoryEventSink()
    runtime = FakeRuntime()

    result = await run(looping(agents("work"), 'results.missing.text == "x"'), runtime, sink)

    assert (result.status, result.stopped_at) == ("failed", "revise")
    error = result.results["revise"].error
    assert error is not None
    assert "until failed in iteration 1" in error
    assert "no such member in mapping: 'missing'" in error
    assert loop_end(sink.events).type == "node_failed"
    assert [r.node_id for r in runtime.requests] == ["before", "work"]


async def test_condition_reads_results_and_iteration() -> None:
    runtime = FakeRuntime()

    result = await run(
        looping(agents("work"), 'results.work.status == "completed" && iteration == 2'), runtime
    )

    assert result.results["revise"].data == {"stop_reason": "condition", "iterations": 2}


async def test_usage_counts_every_iteration() -> None:
    result = await run(looping(agents("work"), "false", max_iterations=3), FakeRuntime())

    assert result.usage is not None
    assert result.usage.input_tokens == 5 * ECHO_USAGE.input_tokens  # before, 3 x work, after


async def test_five_iterations_fit_the_recursion_limit() -> None:
    """The step limit is a tight backstop: before, 5 x (entry, a, b, c, check), after, + 10."""
    spec = looping(agents("a", "b", "c"), "false", max_iterations=5)

    result = await run(spec, FakeRuntime())

    assert result.status == "completed"
    assert result.results["revise"].data == {"stop_reason": "max_iterations", "iterations": 5}
    assert recursion_limit(spec) == 2 + 5 * 5 + 10


class CrashSink(InMemoryEventSink):
    """Flags the `nth` start of `node_id`."""

    def __init__(self, node_id: str, nth: int) -> None:
        super().__init__()
        self.node_id, self.nth, self.seen = node_id, nth, 0
        self.started = asyncio.Event()

    async def emit(self, event: RunEvent) -> None:
        await super().emit(event)
        if event.type == "node_started" and event.node_id == self.node_id:
            self.seen += 1
            if self.seen == self.nth:
                self.started.set()


async def test_resume_mid_loop_continues_the_same_iteration() -> None:
    """AC-8 inside a loop: a run cut off in iteration 2 resumes in iteration 2, and iteration 1
    is not run again."""
    spec, checkpointer, run_id = looping(agents("work"), 'last == "ok"'), saver(), uuid4()
    first = RoundsRuntime({"work": [[Message(text="nope"), ECHO_USAGE], [Delay(60)]]})
    sink = CrashSink("work", nth=2)
    task = asyncio.create_task(
        run_workflow(spec, first, "brief", run_id=run_id, sink=sink, checkpointer=checkpointer)
    )
    await asyncio.wait_for(sink.started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    second = RoundsRuntime({"work": says("ok")})
    result = await resume(spec, second, run_id, sink, checkpointer)

    assert [r.node_id for r in second.requests] == ["work", "after"]
    assert second.requests[0].input == "nope"
    assert result.results["revise"].data == {"stop_reason": "condition", "iterations": 2}
    starts = [e.payload["iteration"] for e in sink.events if e.type == "loop_iteration_started"]
    assert starts == [1, 2]
    resumed = next(e for e in sink.events if e.type == "run_resumed")
    assert resumed.payload["completed_nodes"] == ["before", "work"]
    assert [e.seq for e in sink.events] == list(range(1, len(sink.events) + 1))


async def resume(
    spec: WorkflowSpec,
    runtime: FakeRuntime,
    run_id: UUID,
    sink: InMemoryEventSink,
    checkpointer: InMemorySaver,
) -> WorkflowRunResult:
    return await resume_workflow(
        spec,
        runtime,
        "brief",
        run_id=run_id,
        sink=sink,
        checkpointer=checkpointer,
        next_seq=sink.events[-1].seq + 1,
        attempt=2,
    )
