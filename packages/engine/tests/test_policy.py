"""Policy limits: agents alive and spawned, nesting depth, loop iterations and wall time stop a
run cleanly with a reason (phase 3.2)."""

import asyncio
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.gate import GateDecision
from agentic_engine.graph import checkpoint_serde, resume_workflow, run_workflow
from agentic_engine.policy import (
    PLATFORM_POLICY,
    Policy,
    PolicyLimitExceeded,
    PolicyOverrides,
    effective_policy,
    format_duration,
)
from agentic_engine.spec import LoopNode, MapNode, WorkflowSpec, parse_spec, policy_errors
from agentic_engine.templates.docs import DocsParams, build_docs_spec
from agentic_runtime import Message
from agentic_runtime.fake import ECHO_USAGE, Delay, FakeRuntime


def agent(id: str) -> dict[str, object]:
    return {"type": "agent", "id": id, "role": "R", "instructions": "Go."}


def saver() -> InMemorySaver:
    return InMemorySaver(serde=checkpoint_serde())


def policy(**limits: int) -> Policy:
    return effective_policy(PolicyOverrides.model_validate(limits))


def spec(root: object) -> WorkflowSpec:
    return parse_spec({"spec_version": "0", "id": "limits", "name": "Limits", "root": root})


def looping(max_iterations: int) -> dict[str, object]:
    return {
        "type": "loop",
        "id": "review",
        "body": agent("reviewer"),
        "until": "false",
        "max_iterations": max_iterations,
    }


class StartedSink(InMemoryEventSink):
    """Flags the first `node_started`."""

    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()

    async def emit(self, event: RunEvent) -> None:
        await super().emit(event)
        if event.type == "node_started":
            self.started.set()


def lifecycle(events: list[RunEvent]) -> list[tuple[str, str | None]]:
    return [
        (e.type, e.node_id)
        for e in events
        if e.type.startswith(("node_", "run_", "map_", "policy_"))
    ]


# The policy model


def test_no_overrides_is_the_platform_policy() -> None:
    assert effective_policy() == PLATFORM_POLICY
    assert effective_policy(PolicyOverrides()) == PLATFORM_POLICY
    assert (
        Policy(agents_alive=8, agents_spawned=40, max_depth=2, loop_iterations=5, wall_time_s=7200)
        == PLATFORM_POLICY
    )


def test_a_workspace_can_lower_a_limit_but_never_raise_it() -> None:
    lowered = policy(agents_spawned=10, wall_time_s=60_000)

    assert lowered.agents_spawned == 10
    assert lowered.wall_time_s == PLATFORM_POLICY.wall_time_s
    assert lowered.agents_alive == PLATFORM_POLICY.agents_alive


def test_a_limit_is_at_least_one() -> None:
    with pytest.raises(ValidationError):
        PolicyOverrides(loop_iterations=0)


def test_reasons_name_the_limit_and_what_was_reached() -> None:
    spawned = PolicyLimitExceeded("agents_spawned", 40, 41, "writer")
    wall = PolicyLimitExceeded("wall_time_s", 7200, 7201)

    assert spawned.reason == "policy limit: agents spawned would reach 41, above the limit of 40"
    assert wall.reason == "policy limit: wall time of 2h 0m exceeded"
    assert spawned.payload() == {"limit": "agents_spawned", "value": 40, "observed": 41}
    assert [format_duration(s) for s in (5, 60, 90, 7200, 5400)] == [
        "5s",
        "1m",
        "1m 30s",
        "2h 0m",
        "1h 30m",
    ]


# Checks before the run


def test_a_spec_at_every_limit_passes() -> None:
    at_limits = spec(
        {
            "type": "sequence",
            "id": "main",
            "steps": [
                looping(5),
                {
                    "type": "map",
                    "id": "each",
                    "over": "[]",
                    "body": agent("worker"),
                    "max_concurrency": 8,
                },
            ],
        }
    )

    assert policy_errors(at_limits.root, PLATFORM_POLICY) == []


def test_a_loop_above_the_iteration_limit_is_rejected() -> None:
    errors = policy_errors(spec(looping(4)).root, policy(loop_iterations=3))

    assert errors == [
        "loop 'review' at root: max_iterations 4 is above the workspace limit of 3",
    ]


def test_a_map_above_the_alive_limit_is_rejected() -> None:
    each = {"type": "map", "id": "each", "over": "[]", "body": agent("w"), "max_concurrency": 4}
    root = spec({"type": "sequence", "id": "main", "steps": [agent("first"), each]}).root

    assert policy_errors(root, policy(agents_alive=2)) == [
        "map 'each' at root.steps[1]: max_concurrency 4 is above the workspace limit of 2 "
        "agents alive",
    ]


def test_nesting_deeper_than_the_limit_is_rejected() -> None:
    # A loop around a map cannot be a spec yet (1.9), but the depth check does not rely on that.
    inner = MapNode(type="map", id="each", over="[]", body=agent("worker"), max_concurrency=1)  # type: ignore[arg-type]
    outer = LoopNode(type="loop", id="outer", body=inner, until="true", max_iterations=1)

    assert policy_errors(outer, PLATFORM_POLICY) == []
    assert policy_errors(outer, policy(max_depth=1)) == [
        "map 'each' at root.body: nesting depth 2 is above the workspace limit of 1",
    ]


def test_the_docs_template_fits_the_platform_policy() -> None:
    """The template's map can list up to `agents_spawned - 1` modules, leaving one agent for the
    writer, so a large repo still documents within the limit."""
    docs = build_docs_spec(DocsParams())

    assert policy_errors(docs.root, PLATFORM_POLICY) == []
    list_modules = docs.root.steps[0]  # type: ignore[union-attr]
    assert list_modules.args["limit"] == PLATFORM_POLICY.agents_spawned - 1  # type: ignore[union-attr]


# Agents spawned, at runtime


async def test_every_loop_iteration_counts_as_a_spawned_agent() -> None:
    runtime = FakeRuntime()
    sink = InMemoryEventSink()

    result = await run_workflow(
        spec(looping(5)), runtime, "draft", sink=sink, policy=policy(agents_spawned=3)
    )

    assert result.status == "failed"
    assert result.stopped_at == "reviewer"
    assert len(runtime.requests) == 3
    assert result.results["reviewer"].error == (
        "policy limit: agents spawned would reach 4, above the limit of 3"
    )
    assert lifecycle(sink.events)[-4:] == [
        ("node_started", "reviewer"),
        ("policy_limit_exceeded", "reviewer"),
        ("node_failed", "reviewer"),
        ("run_failed", None),
    ]


async def test_the_spawn_count_survives_a_pause_and_resume() -> None:
    gated = spec(
        {
            "type": "sequence",
            "id": "main",
            "steps": [
                agent("writer"),
                {"type": "gate", "id": "approve", "title": "Go on?"},
                agent("after"),
            ],
        }
    )
    runtime, sink, checkpointer, run_id = FakeRuntime(), InMemoryEventSink(), saver(), uuid4()
    limits = policy(agents_spawned=1)

    paused = await run_workflow(
        gated, runtime, "go", run_id=run_id, sink=sink, checkpointer=checkpointer, policy=limits
    )
    resumed = await resume_workflow(
        gated,
        runtime,
        "go",
        run_id=run_id,
        sink=sink,
        checkpointer=checkpointer,
        next_seq=sink.events[-1].seq + 1,
        attempt=2,
        decision=GateDecision(decision="approve", decided_by="ada"),
        policy=limits,
    )

    assert paused.status == "waiting"
    assert (resumed.status, resumed.stopped_at) == ("failed", "after")
    assert [r.node_id for r in runtime.requests] == ["writer"]


# Wall time: the worker cancels the run with the limit


async def test_a_cancel_with_a_policy_limit_ends_the_run_failed_with_the_reason() -> None:
    runtime = FakeRuntime({"writer": [Delay(60), Message(text="late"), ECHO_USAGE]})
    sink = StartedSink()
    task = asyncio.create_task(run_workflow(spec(agent("writer")), runtime, "go", sink=sink))
    await asyncio.wait_for(sink.started.wait(), 5)

    task.cancel(PolicyLimitExceeded("wall_time_s", 60, 61))  # type: ignore[arg-type]
    with pytest.raises(asyncio.CancelledError):
        await task

    assert lifecycle(sink.events)[-3:] == [
        ("node_cancelled", "writer"),
        ("policy_limit_exceeded", None),
        ("run_failed", None),
    ]
    assert sink.events[-2].payload == {"limit": "wall_time_s", "value": 60, "observed": 61}
    assert sink.events[-1].payload == {"error": "policy limit: wall time of 1m exceeded"}
