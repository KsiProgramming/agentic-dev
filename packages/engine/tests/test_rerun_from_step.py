"""Rerun from a step (12.4): a new run starts from another run's checkpoint taken before one of
its top-level steps, so the steps before it are neither run nor charged again, and the step
itself receives what it would have (its edited instructions, the previous step's output, the
run's context)."""

from typing import Any
from uuid import UUID, uuid4

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from agentic_engine.agent import RunContext
from agentic_engine.branches import BranchSaves
from agentic_engine.events import InMemoryEventSink
from agentic_engine.gate import GateDecision
from agentic_engine.graph import (
    StepNotFoundError,
    StepNotReachedError,
    checkpoint_serde,
    rerun_workflow,
    resume_workflow,
    run_workflow,
    steps_before,
    thread_config,
    top_level_steps,
    top_step_of,
)
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import Failed, Message
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime

from .test_orchestrator import Team, orchestrator, plan


def saver() -> InMemorySaver:
    return InMemorySaver(serde=checkpoint_serde())


def agent(id: str, instructions: str = "Go.", **fields: object) -> dict[str, object]:
    return {"type": "agent", "id": id, "role": "R", "instructions": instructions, **fields}


def spec(*steps: object) -> WorkflowSpec:
    return parse_spec(
        {
            "spec_version": "0",
            "id": "three",
            "name": "Three",
            "root": {"type": "sequence", "id": "main", "steps": list(steps)},
        }
    )


THREE = spec(agent("outline"), agent("write"), agent("review", "Fail on purpose."))
EDITED = spec(agent("outline"), agent("write"), agent("review", "Review the answer."))
FAILING = {"review": [Failed(error="the reviewer gave up")]}


async def original(flow: WorkflowSpec, checkpointer: InMemorySaver, **kw: Any) -> UUID:
    """Run `flow` once (its last step fails with `FAILING`) and return its id."""
    run_id = uuid4()
    runtime = kw.pop("runtime", FakeRuntime(FAILING))
    await run_workflow(
        flow, runtime, "go", run_id=run_id, sink=InMemoryEventSink(), checkpointer=checkpointer,
        **kw,
    )  # fmt: skip
    return run_id


def test_top_level_steps_flatten_nested_sequences() -> None:
    nested = parse_spec(
        {
            "spec_version": "0",
            "id": "n",
            "name": "N",
            "root": {
                "type": "sequence",
                "id": "main",
                "steps": [
                    agent("a"),
                    {"type": "sequence", "id": "inner", "steps": [agent("b"), agent("c")]},
                    {
                        "type": "loop",
                        "id": "again",
                        "max_iterations": 2,
                        "until": "true",
                        "body": agent("d"),
                    },
                ],
            },
        }
    )
    assert [s.id for s in top_level_steps(nested)] == ["a", "b", "c", "again"]
    assert top_step_of(nested)["d"] == "again"
    assert steps_before(nested, "c") == ["a", "b"]
    with pytest.raises(StepNotFoundError):
        steps_before(nested, "d")  # inside a loop: not a top-level step


async def test_done_when_rerun_from_the_last_step_runs_only_it() -> None:
    """Done when (12.4): a run that failed at its last step is rerun from it with changed
    instructions; the earlier steps do not run again and are not charged again."""
    checkpointer = saver()
    source = await original(THREE, checkpointer)

    runtime, sink, run_id = FakeRuntime(), InMemoryEventSink(), uuid4()
    result = await rerun_workflow(
        EDITED, runtime, "go", run_id=run_id, source_run=source, from_node="review",
        sink=sink, checkpointer=checkpointer,
    )  # fmt: skip

    assert result.status == "completed"
    assert [r.node_id for r in runtime.requests] == ["review"]
    started = [e.node_id for e in sink.events if e.type == "node_started"]
    assert started == ["review"]
    usage_nodes = {e.node_id for e in sink.events if e.type == "usage"}
    assert usage_nodes <= {"review"}
    first = sink.events[0]
    assert first.type == "run_started"
    assert first.payload["rerun_from"] == {"run_id": str(source), "node_id": "review"}
    assert first.payload["carried"] == ["outline", "write"]


async def test_the_rerun_step_receives_its_edits_and_the_previous_output() -> None:
    """Lessons rule 1: assert what the rerun agent receives, not only the outcome."""
    checkpointer = saver()
    source = await original(
        THREE,
        checkpointer,
        runtime=FakeRuntime({**FAILING, "write": [Message(text="draft"), ECHO_USAGE]}),
    )
    runtime = FakeRuntime()
    context = RunContext(repo="acme/web", request="Write the README")

    await rerun_workflow(
        EDITED, runtime, "go", run_id=uuid4(), source_run=source, from_node="review",
        sink=InMemoryEventSink(), checkpointer=checkpointer, context=context,
    )  # fmt: skip

    (request,) = runtime.requests
    assert request.instructions.startswith("Review the answer.")
    assert request.input == "draft"
    assert "acme/web" in request.context
    assert "Write the README" in request.context


async def test_the_new_run_carries_results_but_no_usage() -> None:
    checkpointer = saver()
    source = await original(THREE, checkpointer)
    run_id = uuid4()

    result = await rerun_workflow(
        EDITED, FakeRuntime(), "go", run_id=run_id, source_run=source, from_node="review",
        sink=InMemoryEventSink(), checkpointer=checkpointer,
    )  # fmt: skip

    assert result.order == ["outline", "write", "review"]
    assert result.results["outline"].status == "completed"
    graph_state = await checkpointer.aget_tuple(config(run_id))
    assert graph_state is not None
    usage = graph_state.checkpoint["channel_values"]["usage"]
    assert [u for u in usage if u == ECHO_USAGE] == [ECHO_USAGE]  # only the review's


async def test_the_original_run_is_unchanged() -> None:
    checkpointer = saver()
    source = await original(THREE, checkpointer)
    before = [c.checkpoint["id"] async for c in checkpointer.alist(config(source))]

    await rerun_workflow(
        EDITED, FakeRuntime(), "go", run_id=uuid4(), source_run=source, from_node="review",
        sink=InMemoryEventSink(), checkpointer=checkpointer,
    )  # fmt: skip

    assert [c.checkpoint["id"] async for c in checkpointer.alist(config(source))] == before


async def test_rerun_from_the_first_step_starts_from_the_input() -> None:
    checkpointer = saver()
    source = await original(THREE, checkpointer)
    runtime, sink = FakeRuntime(), InMemoryEventSink()

    await rerun_workflow(
        EDITED, runtime, "go", run_id=uuid4(), source_run=source, from_node="outline",
        sink=sink, checkpointer=checkpointer,
    )  # fmt: skip

    assert [r.node_id for r in runtime.requests] == ["outline", "write", "review"]
    assert runtime.requests[0].input == "go"
    assert sink.events[0].payload["carried"] == []


async def test_a_step_that_was_never_reached_is_refused() -> None:
    checkpointer = saver()
    source = await original(
        THREE, checkpointer, runtime=FakeRuntime({"write": [Failed(error="no")]})
    )
    sink = InMemoryEventSink()

    with pytest.raises(StepNotReachedError):
        await rerun_workflow(
            THREE, FakeRuntime(), "go", run_id=uuid4(), source_run=source, from_node="review",
            sink=sink, checkpointer=checkpointer,
        )  # fmt: skip
    assert sink.events == []


async def test_a_step_that_is_not_top_level_is_refused() -> None:
    checkpointer = saver()
    looped = spec(
        agent("a"),
        {"type": "loop", "id": "again", "max_iterations": 1, "until": "true", "body": agent("b")},
    )
    source = await original(looped, checkpointer, runtime=FakeRuntime())

    with pytest.raises(StepNotFoundError):
        await rerun_workflow(
            looped, FakeRuntime(), "go", run_id=uuid4(), source_run=source, from_node="b",
            sink=InMemoryEventSink(), checkpointer=checkpointer,
        )  # fmt: skip


async def test_a_container_step_reruns_whole() -> None:
    """An orchestrator is one step: its hub plans again and its tasks run again."""
    checkpointer = saver()
    flow = spec(agent("scout"), orchestrator(agent("worker")), agent("report"))
    first = Team(plan("a", "b"))
    source = await original(flow, checkpointer, runtime=first)

    second = Team(plan("a", "b", "c"))
    result = await rerun_workflow(
        flow, second, "go", run_id=uuid4(), source_run=source, from_node="fix",
        sink=InMemoryEventSink(), checkpointer=checkpointer,
    )  # fmt: skip

    assert result.status == "completed"
    nodes = [r.node_id for r in second.requests]
    assert "scout" not in nodes
    assert nodes.count("worker") == 3
    assert nodes[-1] == "report"


async def test_a_gate_step_pauses_again() -> None:
    checkpointer = saver()
    gated = spec(
        agent("write"),
        {"type": "gate", "id": "approve", "title": "Approve?", "prompt": "OK?"},
        agent("after"),
    )
    source = uuid4()
    await run_workflow(
        gated, FakeRuntime(), "go", run_id=source, sink=InMemoryEventSink(),
        checkpointer=checkpointer,
    )  # fmt: skip
    await resume_workflow(
        gated, FakeRuntime(), "go", run_id=source, sink=InMemoryEventSink(),
        checkpointer=checkpointer, next_seq=50, attempt=2,
        decision=GateDecision(decision="approve"),
    )  # fmt: skip

    runtime, run_id = FakeRuntime(), uuid4()
    result = await rerun_workflow(
        gated, runtime, "go", run_id=run_id, source_run=source, from_node="approve",
        sink=InMemoryEventSink(), checkpointer=checkpointer,
    )  # fmt: skip

    assert result.status == "waiting"
    assert result.waiting_at == "approve"
    assert runtime.requests == []


async def test_a_seeded_rerun_cut_off_resumes_from_its_own_checkpoint() -> None:
    """A second attempt does not seed again: it carries on from the new run's thread."""
    checkpointer = saver()
    source = await original(THREE, checkpointer)
    run_id = uuid4()
    await rerun_workflow(
        EDITED, FakeRuntime(FAILING), "go", run_id=run_id, source_run=source,
        from_node="review", sink=InMemoryEventSink(), checkpointer=checkpointer,
    )  # fmt: skip

    runtime = FakeRuntime()
    result = await resume_workflow(
        EDITED, runtime, "go", run_id=run_id, sink=InMemoryEventSink(),
        checkpointer=checkpointer, next_seq=50, attempt=2,
    )  # fmt: skip
    assert [r.node_id for r in runtime.requests] == []  # its review failed: the run ended
    assert result.status == "failed"


async def test_branch_saves_record_the_top_level_step() -> None:
    checkpointer, steps = saver(), list[str | None]()

    class Saver:
        async def save(self, *, step: str | None = None) -> BranchSaves:
            steps.append(step)
            return BranchSaves()

    flow = spec(agent("scout"), orchestrator(agent("worker")), agent("report"))
    await original(flow, checkpointer, runtime=Team(plan("a")), saver=Saver())

    assert steps == ["scout", "fix", "report"]


def config(run_id: UUID) -> RunnableConfig:
    return thread_config(run_id)
