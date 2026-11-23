"""Circuit breakers (13.7): the repeat breaker pauses a step that calls one tool the same way again
and again, the thresholds come from the policy and the spec, and a pause leaves the run `waiting`
with the reason."""

import asyncio
from collections.abc import Mapping, Sequence

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import JsonValue

from agentic_engine.breakers import BreakerTripped, BreakerWatch, breaker_reason, error_key
from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.graph import checkpoint_serde, run_workflow
from agentic_engine.policy import (
    BREAKER_RANGES,
    PLATFORM_POLICY,
    BreakerPolicy,
    Policy,
    with_breakers,
)
from agentic_engine.spec import WorkflowSpec, parse_spec, validate_workflow
from agentic_runtime import ToolCall, ToolOutput, ToolResult, Usage
from agentic_runtime.fake import CallTool, Delay, FakeRuntime, Step
from agentic_runtime.testing import ScriptedToolExecutor

READ = "repo.read_file"


def agent(id: str, tools: Sequence[str] = (READ,)) -> dict[str, object]:
    return {"type": "agent", "id": id, "role": "R", "instructions": "Go.", "tools": list(tools)}


def spec(root: object, **extra: object) -> WorkflowSpec:
    return parse_spec(
        {"spec_version": "0", "id": "breakers", "name": "Breakers", "root": root, **extra}
    )


def missing() -> ScriptedToolExecutor:
    return ScriptedToolExecutor({READ: ToolOutput(text="no such file: a.md", is_error=True)})


def found() -> ScriptedToolExecutor:
    return ScriptedToolExecutor({READ: ToolOutput(text="contents")})


USAGE = Usage(model="m", input_tokens=1, output_tokens=1, estimated_usd=0.0)


def calling(times: int, path: str = "a.md") -> list[Step]:
    return [*(CallTool(READ, {"path": path}) for _ in range(times)), USAGE]


def types(events: list[RunEvent], node_id: str | None = None) -> list[str]:
    return [e.type for e in events if node_id is None or e.node_id == node_id]


def tripped_of(events: list[RunEvent]) -> RunEvent:
    [event] = [e for e in events if e.type == "breaker_tripped"]
    return event


def waiting_of(events: list[RunEvent]) -> RunEvent:
    [event] = [e for e in events if e.type == "gate_waiting"]
    return event


# The watch


def call(id: str, arguments: Mapping[str, JsonValue]) -> ToolCall:
    return ToolCall(call_id=id, name=READ, arguments=dict(arguments))


def failure(id: str, text: str) -> ToolResult:
    return ToolResult(call_id=id, output=text, is_error=True)


def test_a_call_that_differs_only_in_its_description_is_the_same_call() -> None:
    watch = BreakerWatch("a", BreakerPolicy(repeat_calls=3))

    watch.see(call("1", {"path": "a.md", "description": "look"}))
    watch.see(call("2", {"description": "look again", "path": "a.md"}))
    with pytest.raises(BreakerTripped) as trip:
        watch.see(call("3", {"path": "a.md"}))

    assert trip.value.breaker == "repeat"
    assert trip.value.trigger == "calls"
    assert (trip.value.threshold, trip.value.observed) == (3, 3)


def test_calls_with_other_arguments_are_not_repeats() -> None:
    watch = BreakerWatch("a", BreakerPolicy(repeat_calls=3))

    for i in range(20):
        watch.see(call(str(i), {"path": f"{i}.md"}))


def test_errors_with_the_same_text_count_whatever_the_whitespace() -> None:
    watch = BreakerWatch("a", BreakerPolicy(repeat_calls=50, repeat_errors=3))
    texts = ["no   such file", "no such\nfile", "no such file"]

    with pytest.raises(BreakerTripped) as trip:
        for i, text in enumerate(texts):
            watch.see(call(str(i), {"path": f"{i}.md"}))
            watch.see(failure(str(i), text))

    assert trip.value.trigger == "errors"
    assert trip.value.observed == 3
    assert trip.value.details["error"] == "no such file"


def test_errors_that_differ_do_not_add_up_and_successes_do_not_count() -> None:
    watch = BreakerWatch("a", BreakerPolicy(repeat_calls=50, repeat_errors=2))

    for i in range(5):
        watch.see(call(str(i), {"path": f"{i}.md"}))
        watch.see(failure(str(i), f"error {i}"))
        watch.see(ToolResult(call_id=str(i), output="no such file", is_error=False))


def test_an_error_is_cut_and_long_arguments_are_shortened() -> None:
    watch = BreakerWatch("a", BreakerPolicy(repeat_calls=50, repeat_errors=2))
    arguments = {"path": "a.md", "content": "x" * 5000}
    with pytest.raises(BreakerTripped) as trip:
        for i in range(2):
            watch.see(call(str(i), arguments))
            watch.see(failure(str(i), "e" * 2000))

    assert len(str(trip.value.details["error"])) == 500
    shown = trip.value.details["arguments"]
    assert isinstance(shown, dict)
    assert len(str(shown["content"])) <= 201


def test_the_reason_is_one_fixed_sentence_per_trigger() -> None:
    tool: dict[str, JsonValue] = {"tool": READ}
    assert breaker_reason("repeat", "calls", 5, tool) == (
        "repo.read_file was called 5 times with the same arguments in one step"
    )
    assert breaker_reason("repeat", "errors", 3, tool) == (
        "repo.read_file failed 3 times with the same error in one step"
    )
    assert error_key("  a \n b  ") == "a b"


# The pause


async def paused(
    workflow: WorkflowSpec,
    runtime: FakeRuntime,
    sink: InMemoryEventSink,
    policy: Policy = PLATFORM_POLICY,
):
    return await asyncio.wait_for(
        run_workflow(
            workflow,
            runtime,
            sink=sink,
            checkpointer=InMemorySaver(serde=checkpoint_serde()),
            policy=policy,
            tools=runtime._tools,  # pyright: ignore[reportPrivateUsage]
        ),
        5,
    )


async def test_an_agent_repeating_a_failing_call_pauses_at_three_errors() -> None:
    sink = InMemoryEventSink()
    runtime = FakeRuntime({"a": calling(6)}, tools=missing())

    result = await paused(spec(agent("a")), runtime, sink)

    assert result.status == "waiting"
    assert result.waiting_at == "a"
    assert [e.type for e in sink.events if e.type == "tool_result"] == ["tool_result"] * 3
    assert types(sink.events)[-4:] == [
        "tool_result",
        "node_cancelled",
        "breaker_tripped",
        "gate_waiting",
    ]
    trip = tripped_of(sink.events)
    assert trip.node_id == "a"
    assert trip.payload["breaker"] == "repeat"
    assert trip.payload["trigger"] == "errors"
    assert (trip.payload["threshold"], trip.payload["observed"]) == (3, 3)
    assert trip.payload["details"] == {
        "tool": READ,
        "arguments": {"path": "a.md"},
        "error": "no such file: a.md",
    }
    assert trip.payload["reason"] == "repo.read_file failed 3 times with the same error in one step"
    assert "run_failed" not in types(sink.events)
    assert "run_cancelled" not in types(sink.events)


async def test_the_pause_is_announced_like_a_gate_with_its_breaker_and_time_to_live() -> None:
    sink = InMemoryEventSink()
    policy = PLATFORM_POLICY.model_copy(update={"approval_ttl_s": 600})

    await paused(spec(agent("a")), FakeRuntime({"a": calling(6)}, tools=missing()), sink, policy)

    gate = waiting_of(sink.events)
    assert gate.node_id == "a"
    assert gate.payload["breaker"] == "repeat"
    assert gate.payload["ttl_s"] == 600
    assert isinstance(gate.payload["expires_at"], str)
    assert gate.payload["reason"] == tripped_of(sink.events).payload["reason"]


async def test_an_agent_repeating_a_successful_call_pauses_at_five_calls() -> None:
    sink = InMemoryEventSink()
    runtime = FakeRuntime({"a": calling(9)}, tools=found())

    result = await paused(spec(agent("a")), runtime, sink)

    assert result.status == "waiting"
    assert [e.type for e in sink.events if e.type == "tool_call"] == ["tool_call"] * 5
    trip = tripped_of(sink.events)
    assert trip.payload["trigger"] == "calls"
    assert (trip.payload["threshold"], trip.payload["observed"]) == (5, 5)
    assert trip.payload["reason"] == (
        "repo.read_file was called 5 times with the same arguments in one step"
    )


async def test_calls_that_move_on_do_not_pause_the_step() -> None:
    runtime = FakeRuntime(
        {"a": [*(CallTool(READ, {"path": f"{i}.md"}) for i in range(12)), USAGE]}, tools=found()
    )

    result = await paused(spec(agent("a")), runtime, InMemoryEventSink())

    assert result.status == "completed"


async def test_the_thresholds_come_from_the_runs_policy() -> None:
    sink = InMemoryEventSink()
    policy = PLATFORM_POLICY.model_copy(update={"breakers": BreakerPolicy(repeat_errors=2)})

    await paused(spec(agent("a")), FakeRuntime({"a": calling(6)}, tools=missing()), sink, policy)

    assert [e.type for e in sink.events if e.type == "tool_result"] == ["tool_result"] * 2
    assert tripped_of(sink.events).payload["threshold"] == 2


async def test_steps_that_completed_stay_done_when_a_later_step_trips() -> None:
    sink = InMemoryEventSink()
    workflow = spec({"type": "sequence", "id": "s", "steps": [agent("a"), agent("b")]})
    runtime = FakeRuntime({"a": [USAGE], "b": calling(6)}, tools=missing())

    result = await paused(workflow, runtime, sink)

    assert result.status == "waiting"
    assert result.waiting_at == "b"
    assert result.results["a"].status == "completed"
    assert types(sink.events, "a")[-1] == "node_completed"


async def test_a_trip_in_one_parallel_branch_cancels_the_other() -> None:
    sink = InMemoryEventSink()
    workflow = spec(
        {"type": "parallel", "id": "p", "join": "all", "branches": [agent("a"), agent("b")]}
    )
    runtime = FakeRuntime({"a": calling(6), "b": [Delay(5), USAGE]}, tools=missing())
    before = asyncio.all_tasks()

    result = await paused(workflow, runtime, sink)

    assert result.status == "waiting"
    assert result.waiting_at == "a"
    assert types(sink.events, "b")[-1] == "node_cancelled"
    assert types(sink.events)[-3:] == ["node_cancelled", "breaker_tripped", "gate_waiting"]
    assert asyncio.all_tasks() <= before


async def test_each_map_item_has_its_own_counters() -> None:
    sink = InMemoryEventSink()
    workflow = spec(
        {
            "type": "map",
            "id": "m",
            "over": "['x', 'y', 'z']",
            "max_concurrency": 3,
            "body": agent("w"),
        }
    )
    # Two failures of one call in each of three items: six in all, never three in one step.
    runtime = FakeRuntime({"w": calling(2)}, tools=missing())

    result = await paused(workflow, runtime, sink)

    assert result.status == "completed"
    assert "breaker_tripped" not in types(sink.events)


# Thresholds


def test_a_policy_frozen_before_13_7_loads_with_the_defaults() -> None:
    frozen = {k: v for k, v in PLATFORM_POLICY.model_dump(mode="json").items() if k != "breakers"}

    assert Policy.model_validate(frozen).breakers == BreakerPolicy()
    assert BreakerPolicy() == BreakerPolicy(
        repeat_calls=5, repeat_errors=3, cost_multiple=3, cost_floor_usd=0.5, flip_flops=2
    )


def test_the_workflow_overrides_the_workspace_and_both_are_held_to_the_ranges() -> None:
    workspace = PLATFORM_POLICY.model_copy(
        update={"breakers": BreakerPolicy(repeat_calls=8, repeat_errors=4)}
    )

    resolved = with_breakers(workspace, {"repeat_errors": 7, "cost_multiple": 999, "flip_flops": 0})

    assert resolved.breakers.repeat_calls == 8  # the workspace's
    assert resolved.breakers.repeat_errors == 7  # the workflow's
    assert resolved.breakers.cost_multiple == BREAKER_RANGES["cost_multiple"][1]  # clamped
    assert resolved.breakers.flip_flops == BREAKER_RANGES["flip_flops"][0]
    assert with_breakers(workspace, None) == workspace
    # Frozen on the run as JSON.
    assert Policy.model_validate(resolved.model_dump(mode="json")) == resolved


def document(**breakers: float) -> dict[str, object]:
    return {
        "spec_version": "0",
        "id": "b",
        "name": "B",
        "breakers": breakers,
        "root": {"type": "agent", "id": "a", "role": "R", "instructions": "Go."},
    }


def test_a_threshold_outside_its_range_is_a_validation_issue() -> None:
    issues = validate_workflow(
        document(repeat_calls=1, cost_multiple=50, flip_flops=3),
        policy=PLATFORM_POLICY,
        priced=lambda _: True,
        default_model="m",
    )

    assert [(i.code, i.path) for i in issues] == [
        ("breakers_out_of_range", "breakers.repeat_calls"),
        ("breakers_out_of_range", "breakers.cost_multiple"),
    ]
    assert "between 2 and 50" in issues[0].message


def test_a_spec_with_thresholds_in_range_is_valid_and_one_outside_cannot_be_parsed() -> None:
    assert parse_spec(document(repeat_calls=10)).breakers is not None
    with pytest.raises(ValueError, match="breakers"):
        parse_spec(document(repeat_calls=1))
