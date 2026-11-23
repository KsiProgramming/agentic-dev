"""Circuit breakers (13.7): the repeat breaker pauses a step that calls one tool the same way again
and again, the thresholds come from the policy and the spec, and a pause leaves the run `waiting`
with the reason."""

import asyncio
from collections.abc import Mapping, Sequence
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import JsonValue

from agentic_engine.breakers import (
    BreakerTripped,
    BreakerWatch,
    breaker_reason,
    error_key,
    paused_before_text,
)
from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.gate import GateDecision
from agentic_engine.graph import (
    BREAKER_CANCELLED_REASON,
    BreakerPause,
    WorkflowRunResult,
    checkpoint_serde,
    resume_workflow,
    run_workflow,
)
from agentic_engine.policy import (
    BREAKER_RANGES,
    PLATFORM_POLICY,
    BreakerPolicy,
    Policy,
    with_breakers,
)
from agentic_engine.spec import WorkflowSpec, parse_spec, validate_workflow
from agentic_runtime import Message, ToolCall, ToolOutput, ToolResult, Usage
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


# Resume and cancel


class Paused:
    """A run a breaker paused at step `b` (after `a` completed), and what happens next."""

    def __init__(self, tools: ScriptedToolExecutor | None = None) -> None:
        self.workflow = spec({"type": "sequence", "id": "s", "steps": [agent("a"), agent("b")]})
        self.tools = tools or missing()
        self.sink = InMemoryEventSink()
        self.checkpointer = InMemorySaver(serde=checkpoint_serde())
        self.run_id = uuid4()
        self.first = FakeRuntime({"a": [USAGE], "b": calling(6)}, tools=self.tools)

    async def start(self) -> WorkflowRunResult:
        return await run_workflow(
            self.workflow,
            self.first,
            "the request",
            run_id=self.run_id,
            sink=self.sink,
            checkpointer=self.checkpointer,
            tools=self.tools,
        )

    def pause(self) -> BreakerPause:
        trip = tripped_of(self.sink.events)
        return BreakerPause(
            node_id=str(trip.node_id), trip=trip.payload, decision=GateDecision(decision="approve")
        )

    async def resume(self, runtime: FakeRuntime, decision: str = "approve") -> WorkflowRunResult:
        pause = self.pause()
        pause = BreakerPause(pause.node_id, pause.trip, GateDecision(decision=decision))  # pyright: ignore[reportArgumentType]
        return await resume_workflow(
            self.workflow,
            runtime,
            "the request",
            run_id=self.run_id,
            sink=self.sink,
            checkpointer=self.checkpointer,
            next_seq=len(self.sink.events) + 1,
            attempt=2,
            tools=self.tools,
            breaker=pause,
        )


def after_pause(paused: Paused) -> list[RunEvent]:
    first = max(i for i, e in enumerate(paused.sink.events) if e.type == "gate_waiting")
    return paused.sink.events[first + 1 :]


async def test_resume_runs_the_paused_step_again_and_not_the_ones_that_completed() -> None:
    paused = Paused()
    assert (await paused.start()).status == "waiting"
    second = FakeRuntime({"b": [Message(text="read it another way"), USAGE]}, tools=found())

    result = await paused.resume(second)

    assert result.status == "completed"
    assert [r.node_id for r in second.requests] == ["b"]
    events = after_pause(paused)
    assert [e.type for e in events if e.type.startswith(("run_", "gate_"))] == [
        "run_resumed",
        "gate_decided",
        "run_completed",
    ]
    [decided] = [e for e in events if e.type == "gate_decided"]
    assert decided.node_id == "b"
    assert (decided.payload["decision"], decided.payload["source"]) == ("approve", "breaker")


async def test_the_resumed_agent_is_told_why_and_its_input_is_unchanged() -> None:
    paused = Paused()
    await paused.start()
    [first] = [r for r in paused.first.requests if r.node_id == "b"]
    second = FakeRuntime({"b": [Message(text="done"), USAGE]}, tools=found())

    await paused.resume(second)

    [again] = second.requests
    assert "# Paused before" in again.context
    assert "repo.read_file failed 3 times with the same error in one step" in again.context
    assert "<breaker-details>" in again.context
    assert '"path": "a.md"' in again.context
    assert again.input == first.input
    assert "# Paused before" not in first.context
    [started] = [e for e in after_pause(paused) if e.type == "node_started" and e.node_id == "b"]
    assert started.payload["resumed_after"] == {
        "breaker": "repeat",
        "reason": "repo.read_file failed 3 times with the same error in one step",
    }


async def test_a_step_that_was_not_paused_gets_no_such_section() -> None:
    paused = Paused()
    await paused.start()
    second = FakeRuntime({"b": [USAGE]}, tools=found())

    await paused.resume(second)

    assert all("# Paused before" not in r.context for r in paused.first.requests)
    started = [e for e in paused.sink.events if e.type == "node_started" and e.node_id == "a"]
    assert all("resumed_after" not in e.payload for e in started)


async def test_a_step_that_trips_again_pauses_again_with_fresh_counters() -> None:
    paused = Paused()
    await paused.start()
    again = FakeRuntime({"b": calling(6)}, tools=missing())

    result = await paused.resume(again)

    assert result.status == "waiting"
    assert result.waiting_at == "b"
    assert [e.type for e in paused.sink.events if e.type == "tool_result"] == ["tool_result"] * 6
    assert len([e for e in paused.sink.events if e.type == "gate_waiting"]) == 2


async def test_cancel_ends_the_run_cancelled_and_runs_nothing() -> None:
    paused = Paused()
    await paused.start()
    second = FakeRuntime({"b": [USAGE]}, tools=found())

    result = await paused.resume(second, "reject")

    assert result.status == "cancelled"
    assert second.requests == []
    events = after_pause(paused)
    assert [e.type for e in events] == ["run_resumed", "gate_decided", "run_cancelled"]
    assert events[-1].payload == {"reason": BREAKER_CANCELLED_REASON}


async def test_a_pause_uses_no_loop_pass() -> None:
    sink = InMemoryEventSink()
    workflow = spec(
        {
            "type": "loop",
            "id": "l",
            "until": 'results.w.text == "finished"',
            "max_iterations": 3,
            "body": agent("w"),
        }
    )
    checkpointer = InMemorySaver(serde=checkpoint_serde())
    run_id = uuid4()
    tripping = FakeRuntime({"w": calling(6)}, tools=missing())
    result = await run_workflow(
        workflow, tripping, run_id=run_id, sink=sink, checkpointer=checkpointer, tools=missing()
    )
    assert result.status == "waiting"
    assert [e.payload["iteration"] for e in sink.events if e.type == "loop_iteration_started"] == [
        1
    ]

    pause = BreakerPause("w", tripped_of(sink.events).payload, GateDecision(decision="approve"))
    resumed = FakeRuntime({"w": [Message(text="going on"), USAGE]}, tools=found())
    await resume_workflow(
        workflow,
        resumed,
        run_id=run_id,
        sink=sink,
        checkpointer=checkpointer,
        next_seq=len(sink.events) + 1,
        attempt=2,
        tools=found(),
        breaker=pause,
    )

    # The paused step went on in pass 1, so all three passes were still there to use.
    assert [e.payload["iteration"] for e in sink.events if e.type == "loop_iteration_started"] == [
        1,
        2,
        3,
    ]
    assert len(resumed.requests) == 3


# The cost, paths and flip-flop breakers (group 4)

WRITE = "repo.write_file"


def writing(*files: tuple[str, str]) -> list[Step]:
    return [*(CallTool(WRITE, {"path": p, "content": c}) for p, c in files), USAGE]


def writer(id: str = "a", **extra: object) -> dict[str, object]:
    return {**agent(id, [WRITE, "repo.commit"]), **extra}


def writes_ok() -> ScriptedToolExecutor:
    return ScriptedToolExecutor({WRITE: "wrote it"})


def costing(usd: float) -> list[Step]:
    return [Usage(model="m", input_tokens=1, output_tokens=1, estimated_usd=usd), Message(text="x")]


async def run_with(
    workflow: WorkflowSpec,
    runtime: FakeRuntime,
    sink: InMemoryEventSink,
    baselines: dict[str, JsonValue] | None = None,
):
    return await asyncio.wait_for(
        run_workflow(
            workflow,
            runtime,
            sink=sink,
            checkpointer=InMemorySaver(serde=checkpoint_serde()),
            tools=runtime._tools,  # pyright: ignore[reportPrivateUsage]
            cost_baselines=baselines,
        ),
        5,
    )


def usual(node: str, mean_usd: float, runs: int = 6) -> dict[str, JsonValue]:
    return {node: {"mean_usd": mean_usd, "runs": runs}}


async def test_a_step_costing_three_times_its_average_and_the_floor_pauses_mid_step() -> None:
    sink = InMemoryEventSink()
    # Average $0.20: the line is max(3 x 0.20, 0.20 + 0.50) = $0.70.
    spent = [Usage(model="m", input_tokens=1, output_tokens=1, estimated_usd=u) for u in (0.3, 0.5)]
    runtime = FakeRuntime({"a": [*spent, Message(text="more")]})

    result = await run_with(spec(agent("a", [])), runtime, sink, usual("a", 0.2))

    assert result.status == "waiting"
    trip = tripped_of(sink.events)
    assert (trip.payload["breaker"], trip.payload["trigger"]) == ("cost", "cost")
    assert (trip.payload["threshold"], trip.payload["observed"]) == (0.7, 0.8)
    assert trip.payload["details"] == {"cost_usd": 0.8, "average_usd": 0.2, "multiple": 3.0}
    assert trip.payload["reason"] == (
        "the step has cost $0.80, against a usual $0.20: past its limit of $0.70"
    )
    assert types(sink.events)[-3:] == ["node_cancelled", "breaker_tripped", "gate_waiting"]
    assert "message" not in types(sink.events)  # it did not run to its end


async def test_under_the_floor_or_without_a_baseline_a_step_is_not_paused() -> None:
    # $0.05 is over 3 x $0.01 but under the $0.50 floor.
    small = await run_with(
        spec(agent("a", [])),
        FakeRuntime({"a": costing(0.05)}),
        InMemoryEventSink(),
        usual("a", 0.01),
    )
    # A huge step on a node with no baseline (fewer than 5 past runs leaves none).
    sink = InMemoryEventSink()
    none = await run_with(spec(agent("a", [])), FakeRuntime({"a": costing(50)}), sink, None)
    other = await run_with(
        spec(agent("a", [])), FakeRuntime({"a": costing(50)}), InMemoryEventSink(), usual("b", 0.1)
    )

    assert (small.status, none.status, other.status) == ("completed",) * 3


async def test_the_cost_floor_and_multiple_come_from_the_policy() -> None:
    sink = InMemoryEventSink()
    policy = PLATFORM_POLICY.model_copy(
        update={"breakers": BreakerPolicy(cost_multiple=2, cost_floor_usd=0)}
    )
    runtime = FakeRuntime({"a": costing(0.25)})

    result = await asyncio.wait_for(
        run_workflow(
            spec(agent("a", [])),
            runtime,
            sink=sink,
            checkpointer=InMemorySaver(serde=checkpoint_serde()),
            policy=policy,
            cost_baselines=usual("a", 0.1),
        ),
        5,
    )

    assert result.status == "waiting"
    assert tripped_of(sink.events).payload["threshold"] == 0.2


async def test_a_write_outside_the_declared_paths_pauses_and_the_tool_is_never_called() -> None:
    sink = InMemoryEventSink()
    tools = writes_ok()
    runtime = FakeRuntime({"a": writing(("docs/a.md", "x"), ("README.md", "y"))}, tools=tools)

    result = await run_with(spec(writer(paths=["docs/**"])), runtime, sink)

    assert result.status == "waiting"
    assert [args["path"] for _, args in tools.calls] == ["docs/a.md"]  # README.md never reached it
    trip = tripped_of(sink.events)
    assert (trip.payload["breaker"], trip.payload["trigger"]) == ("paths", "write")
    assert trip.payload["details"] == {"tool": WRITE, "path": "README.md", "paths": ["docs/**"]}
    assert trip.payload["reason"] == (
        "repo.write_file tried to write 'README.md', outside the paths this step may write"
    )


async def test_an_escaping_path_is_outside_and_no_paths_means_anywhere() -> None:
    away = await run_with(
        spec(writer(paths=["docs/**"])),
        FakeRuntime({"a": writing(("../x.md", "x"))}, tools=writes_ok()),
        InMemoryEventSink(),
    )
    free = await run_with(
        spec(writer()),
        FakeRuntime({"a": writing(("README.md", "x"), ("src/a.py", "y"))}, tools=writes_ok()),
        InMemoryEventSink(),
    )

    assert away.status == "waiting"
    assert free.status == "completed"


async def test_a_declared_node_is_told_its_paths() -> None:
    runtime = FakeRuntime({"a": writing(("docs/a.md", "x"))}, tools=writes_ok())

    await run_with(spec(writer(paths=["docs/**"])), runtime, InMemoryEventSink())

    assert "# Declared paths" in runtime.requests[0].context
    assert "`docs/**`" in runtime.requests[0].context


async def test_a_to_b_to_a_to_b_pauses_at_two_flips_and_distinct_rewrites_do_not() -> None:
    sink = InMemoryEventSink()
    flipping = writing(("a.py", "A"), ("a.py", "B"), ("a.py", "A"), ("a.py", "B"), ("a.py", "C"))
    runtime = FakeRuntime({"a": flipping}, tools=writes_ok())

    result = await run_with(spec(writer()), runtime, sink)

    assert result.status == "waiting"
    trip = tripped_of(sink.events)
    assert (trip.payload["breaker"], trip.payload["trigger"]) == ("flip_flop", "rewrites")
    assert (trip.payload["threshold"], trip.payload["observed"]) == (2, 2)
    # Paths and a count: never the contents.
    assert trip.payload["details"] == {"tool": WRITE, "path": "a.py"}
    assert (
        trip.payload["reason"]
        == "'a.py' was rewritten back to an earlier content 2 times in one step"
    )
    distinct = await run_with(
        spec(writer()),
        FakeRuntime(
            {"a": writing(*[("a.py", str(i)) for i in range(8)], ("a.py", "7"))},
            tools=writes_ok(),
        ),
        InMemoryEventSink(),
    )
    assert distinct.status == "completed"


async def test_one_flip_back_is_not_a_trip_and_each_file_has_its_own_history() -> None:
    result = await run_with(
        spec(writer()),
        FakeRuntime(
            {"a": writing(("a", "1"), ("b", "1"), ("a", "2"), ("b", "2"), ("a", "1"))},
            tools=writes_ok(),
        ),
        InMemoryEventSink(),
    )

    assert result.status == "completed"  # two files with one flip back in all, one on `a`


def test_the_reason_is_one_fixed_sentence_per_breaker() -> None:
    cost: dict[str, JsonValue] = {"cost_usd": 1.5, "average_usd": 0.25}
    assert breaker_reason("cost", "cost", 0.75, cost) == (
        "the step has cost $1.50, against a usual $0.25: past its limit of $0.75"
    )
    assert breaker_reason("paths", "write", 1, {"tool": WRITE, "path": "x.md"}) == (
        "repo.write_file tried to write 'x.md', outside the paths this step may write"
    )
    assert breaker_reason("flip_flop", "rewrites", 3, {"path": "x.md"}) == (
        "'x.md' was rewritten back to an earlier content 3 times in one step"
    )


def test_what_the_resumed_agent_is_told_covers_each_breaker() -> None:
    for breaker, trigger, details in (
        ("cost", "cost", {"cost_usd": 1.5, "average_usd": 0.25, "multiple": 3.0}),
        ("paths", "write", {"tool": WRITE, "path": "x.md", "paths": ["docs/**"]}),
        ("flip_flop", "rewrites", {"tool": WRITE, "path": "x.md"}),
    ):
        trip: dict[str, JsonValue] = {
            "breaker": breaker,
            "trigger": trigger,
            "threshold": 2,
            "observed": 2,
            "details": details,
            "reason": breaker_reason(breaker, trigger, 2, details),  # pyright: ignore[reportArgumentType]
        }
        text = paused_before_text(trip)
        assert f"Breaker: {breaker} ({trigger})" in text
        assert "<breaker-details>" in text and "</breaker-details>" in text
        assert str(trip["reason"]) in text


def test_paths_without_a_write_tool_and_a_bad_glob_are_validation_issues() -> None:
    def issues(**node: object) -> list[tuple[str, str]]:
        found = validate_workflow(
            {
                "spec_version": "0",
                "id": "p",
                "name": "P",
                "root": {"type": "agent", "id": "a", "role": "R", "instructions": "Go.", **node},
            },
            policy=PLATFORM_POLICY,
            priced=lambda _: True,
            default_model="m",
        )
        return [(i.code, i.path) for i in found]

    assert issues(paths=["docs/**"], tools=[READ]) == [("paths_without_writes", "root.paths")]
    assert issues(paths=["docs/**"], tools=[WRITE]) == []
    assert issues(paths=["/etc/**"], tools=[WRITE]) == [("invalid_paths", "root.paths[0]")]
    assert issues(tools=[READ]) == []
    with pytest.raises(ValueError, match="paths"):
        parse_spec(
            {
                "spec_version": "0",
                "id": "p",
                "name": "P",
                "root": {
                    "type": "agent",
                    "id": "a",
                    "role": "R",
                    "instructions": "Go.",
                    "paths": ["docs/**"],
                },
            }
        )
