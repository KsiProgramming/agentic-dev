"""The `parallel` primitive: three branches run concurrently and join correctly, by all, any or
quorum (phase 4.1)."""

import asyncio
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.graph import WorkflowRunResult, checkpoint_serde, resume_workflow, run_workflow
from agentic_engine.graph.compile import recursion_limit, step_nodes
from agentic_engine.policy import PLATFORM_POLICY, Policy, with_budget
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import AgentEvent, AgentRequest, AgentRun, Failed, Message, Usage
from agentic_runtime.fake import ECHO_USAGE, Delay, FakeRuntime, Script

FIXTURES = Path(__file__).parent / "fixtures" / "specs" / "valid"
BRANCHES = ["a", "b", "c"]


class CountingRuntime:
    """A fake runtime that records how many runs are in flight at once. Each node answers
    `<node>(<input>)` after waiting `delays[node]` seconds, or fails if it is in `fail`."""

    def __init__(
        self, delays: Mapping[str, float] | None = None, fail: frozenset[str] = frozenset()
    ) -> None:
        self._delays = dict(delays or {})
        self._fail = fail
        self.requests: list[AgentRequest] = []
        self.live = 0
        self.peak = 0

    def start(self, request: AgentRequest) -> AgentRun:
        self.requests.append(request)
        script: Script = [Delay(self._delays.get(request.node_id, 0.01))]
        if request.node_id in self._fail:
            script = [*script, Failed(error="model refused")]
        else:
            script = [*script, Message(text=f"{request.node_id}({request.input})"), ECHO_USAGE]
        return _Counted(FakeRuntime({request.node_id: script}).start(request), self)


class _Counted:
    def __init__(self, run: AgentRun, runtime: CountingRuntime) -> None:
        self._run = run
        self._runtime = runtime

    def cancel(self) -> None:
        self._run.cancel()

    def __aiter__(self) -> AsyncIterator[AgentEvent]:
        return self._stream()

    async def _stream(self) -> AsyncIterator[AgentEvent]:
        self._runtime.live += 1
        self._runtime.peak = max(self._runtime.peak, self._runtime.live)
        try:
            async for event in self._run:
                yield event
        finally:
            self._runtime.live -= 1


def agent(id: str) -> dict[str, object]:
    return {"type": "agent", "id": id, "role": "R", "instructions": "Go."}


def parallel(
    branches: Sequence[Mapping[str, object]] | None = None,
    join: str = "all",
    quorum: int | None = None,
) -> WorkflowSpec:
    """A parallel `review` of `branches` (agents a, b and c by default), then an agent `after`."""
    node: dict[str, object] = {
        "type": "parallel",
        "id": "review",
        "branches": branches or [agent(b) for b in BRANCHES],
        "join": join,
    }
    if quorum is not None:
        node["quorum"] = quorum
    return parse_spec(
        {
            "spec_version": "0",
            "id": "parallel",
            "name": "Parallel",
            "root": {"type": "sequence", "id": "main", "steps": [node, agent("after")]},
        }
    )


def saver() -> InMemorySaver:
    return InMemorySaver(serde=checkpoint_serde())


async def run(
    spec: WorkflowSpec,
    runtime: CountingRuntime,
    sink: InMemoryEventSink | None = None,
    policy: Policy = PLATFORM_POLICY,
) -> WorkflowRunResult:
    return await run_workflow(
        spec, runtime, "brief", sink=sink, checkpointer=saver(), policy=policy
    )


def branch_ends(events: list[RunEvent]) -> dict[str, object]:
    return {
        str(e.payload["branch_id"]): e.payload["status"]
        for e in events
        if e.type == "parallel_branch_completed"
    }


def node_ends(events: list[RunEvent], node_id: str) -> list[str]:
    return [
        e.type
        for e in events
        if e.node_id == node_id and e.type.startswith("node_") and e.type != "node_started"
    ]


async def test_three_branches_run_concurrently_and_join_all() -> None:
    """Done when (4.1): three branches run at once, and the join waits for all of them; the
    output keeps branch order although they finish in reverse."""
    runtime = CountingRuntime(delays={"a": 0.15, "b": 0.08, "c": 0.01})
    sink = InMemoryEventSink()

    result = await run(parallel(), runtime, sink)

    assert result.status == "completed"
    assert runtime.peak == 3
    finished = [e.payload["index"] for e in sink.events if e.type == "parallel_branch_completed"]
    assert finished == [2, 1, 0]
    joined = "\n\n".join(f"{b}(brief)" for b in BRANCHES)
    assert result.results["review"].text == joined
    assert result.results["review"].data == {
        "outputs": {b: f"{b}(brief)" for b in BRANCHES},
        "completed": BRANCHES,
        "failed": [],
        "cancelled": [],
    }
    assert runtime.requests[-1].node_id == "after"
    assert runtime.requests[-1].input == joined
    assert result.order == ["review", "after"]
    assert result.results["a"].text == "a(brief)"


async def test_every_branch_gets_the_parallels_input_and_a_sequence_runs_in_order() -> None:
    branches = [agent("a"), {"type": "sequence", "id": "s", "steps": [agent("b1"), agent("b2")]}]
    runtime = CountingRuntime()

    result = await run(parallel(branches), runtime)

    inputs = {r.node_id: r.input for r in runtime.requests}
    assert inputs["a"] == inputs["b1"] == "brief"
    assert inputs["b2"] == "b1(brief)"
    assert result.results["review"].data is not None
    assert result.results["review"].data["outputs"] == {"a": "a(brief)", "s": "b2(b1(brief))"}


async def test_branch_results_are_visible_to_later_nodes() -> None:
    spec = parse_spec(
        {
            "spec_version": "0",
            "id": "p",
            "name": "P",
            "root": {
                "type": "sequence",
                "id": "main",
                "steps": [
                    {
                        "type": "parallel",
                        "id": "review",
                        "join": "all",
                        "branches": [agent("a"), agent("b")],
                    },
                    {
                        "type": "loop",
                        "id": "check",
                        "until": 'results.a.text == "a(brief)"',
                        "max_iterations": 2,
                        "body": agent("after"),
                    },
                ],
            },
        }
    )

    result = await run(spec, CountingRuntime())

    assert result.status == "completed"
    assert result.results["a"].text == "a(brief)"
    assert result.results["check"].data == {"stop_reason": "condition", "iterations": 1}


async def test_join_any_completes_on_the_first_branch_and_cancels_the_others() -> None:
    runtime = CountingRuntime(delays={"a": 5, "b": 0.01, "c": 5})
    sink = InMemoryEventSink()

    result = await asyncio.wait_for(run(parallel(join="any"), runtime, sink), 2)

    assert result.status == "completed"
    assert result.results["review"].text == "b(brief)"
    assert branch_ends(sink.events) == {"a": "cancelled", "b": "completed", "c": "cancelled"}
    assert node_ends(sink.events, "a") == ["node_cancelled"]
    assert node_ends(sink.events, "c") == ["node_cancelled"]
    assert result.results["review"].data is not None
    assert result.results["review"].data["cancelled"] == ["a", "c"]
    assert result.results["a"].status == "cancelled"


async def test_join_any_fails_only_when_every_branch_fails() -> None:
    one_left = await run(parallel(join="any"), CountingRuntime(fail=frozenset({"a", "b"})))
    none_left = await run(parallel(join="any"), CountingRuntime(fail=frozenset(BRANCHES)))

    assert one_left.status == "completed"
    assert one_left.results["review"].text == "c(brief)"
    assert none_left.status == "failed"
    assert none_left.stopped_at == "review"
    assert none_left.results["review"].error == (
        "join any: 0 of 3 branches completed, 1 needed; branch 'a' a failed: model refused"
    )


async def test_join_quorum_completes_at_the_quorum_and_cancels_the_rest() -> None:
    runtime = CountingRuntime(delays={"a": 0.01, "b": 0.02, "c": 5})
    sink = InMemoryEventSink()

    result = await asyncio.wait_for(run(parallel(join="quorum", quorum=2), runtime, sink), 2)

    assert result.status == "completed"
    assert result.results["review"].text == "a(brief)\n\nb(brief)"
    assert branch_ends(sink.events) == {"a": "completed", "b": "completed", "c": "cancelled"}


async def test_join_quorum_fails_as_soon_as_it_is_out_of_reach() -> None:
    runtime = CountingRuntime(delays={"a": 0.01, "b": 0.02, "c": 5}, fail=frozenset({"a", "b"}))
    sink = InMemoryEventSink()

    result = await asyncio.wait_for(run(parallel(join="quorum", quorum=2), runtime, sink), 2)

    assert result.status == "failed"
    assert branch_ends(sink.events) == {"a": "failed", "b": "failed", "c": "cancelled"}
    assert [r.node_id for r in runtime.requests] == ["a", "b", "c"]


async def test_join_all_fails_fast_naming_the_branch() -> None:
    runtime = CountingRuntime(delays={"a": 5, "b": 0.01, "c": 5}, fail=frozenset({"b"}))
    sink = InMemoryEventSink()

    result = await asyncio.wait_for(run(parallel(), runtime, sink), 2)

    assert result.status == "failed"
    assert result.stopped_at == "review"
    assert result.results["review"].error == (
        "join all: 0 of 3 branches completed, 3 needed; branch 'b' b failed: model refused"
    )
    assert branch_ends(sink.events) == {"a": "cancelled", "b": "failed", "c": "cancelled"}
    failed = next(e for e in sink.events if e.type == "node_failed" and e.node_id == "review")
    assert failed.payload["cancelled"] == ["a", "c"]
    assert "after" not in [r.node_id for r in runtime.requests]


async def test_a_parallel_that_would_pass_the_spawn_limit_fails_before_its_branches() -> None:
    sink = InMemoryEventSink()
    runtime = CountingRuntime()
    policy = PLATFORM_POLICY.model_copy(update={"agents_spawned": 2})

    result = await run(parallel(), runtime, sink, policy)

    assert result.status == "failed"
    assert result.stopped_at == "review"
    assert runtime.requests == []
    limit = next(e for e in sink.events if e.type == "policy_limit_exceeded")
    assert limit.payload == {"limit": "agents_spawned", "value": 2, "observed": 3}
    assert not [e for e in sink.events if e.type.startswith("parallel_branch")]


async def test_agents_alive_throttles_the_branches_instead_of_failing_them() -> None:
    runtime = CountingRuntime()

    result = await run(
        parallel(), runtime, policy=PLATFORM_POLICY.model_copy(update={"agents_alive": 2})
    )

    assert result.status == "completed"
    assert runtime.peak == 2


async def test_a_budget_stop_in_a_branch_ends_the_run_not_the_join() -> None:
    def costing() -> Script:
        return [Usage(model="m", input_tokens=1, output_tokens=1, estimated_usd=0.5), Delay(5)]

    runtime = FakeRuntime({b: costing() for b in BRANCHES})
    sink = InMemoryEventSink()
    before = asyncio.all_tasks()

    result = await asyncio.wait_for(
        run_workflow(
            parallel(join="any"),
            runtime,
            sink=sink,
            checkpointer=saver(),
            policy=with_budget(PLATFORM_POLICY, Decimal("1.2")),
        ),
        2,
    )

    assert result.status == "failed"
    assert [e.type for e in sink.events[-2:]] == ["policy_limit_exceeded", "run_failed"]
    assert sink.events[-2].payload["limit"] == "budget_usd"
    assert not [e for e in sink.events if e.type == "parallel_branch_completed"]
    assert asyncio.all_tasks() <= before


async def test_events_tag_each_branch_and_keep_seq_order() -> None:
    sink = InMemoryEventSink()

    await run(parallel(join="quorum", quorum=2), CountingRuntime(), sink)

    assert [e.seq for e in sink.events] == list(range(1, len(sink.events) + 1))
    own = [(e.type, e.payload) for e in sink.events if e.node_id == "review"]
    assert own[0] == ("node_started", {"branches": 3, "join": "quorum", "quorum": 2})
    assert own[-1][0] == "node_completed"
    starts = [p["index"] for t, p in own if t == "parallel_branch_started"]
    assert sorted(i for i in starts if isinstance(i, int)) == [0, 1, 2]
    for branch, index in zip(BRANCHES, range(3), strict=True):
        tagged = [e for e in sink.events if e.node_id == branch]
        assert tagged and all(e.payload["branch"] == index for e in tagged)
    message = next(e for e in sink.events if e.type == "message" and e.node_id == "a")
    assert message.agent_event() == Message(text="a(brief)")


async def test_usage_adds_up_every_branch() -> None:
    result = await run(parallel(), CountingRuntime())

    assert result.usage is not None
    assert result.usage.input_tokens == 4 * ECHO_USAGE.input_tokens


async def test_the_fixtures_run_end_to_end() -> None:
    for name in ["parallel-three-reviewers.json", "parallel-quorum.json"]:
        spec = parse_spec(json.loads((FIXTURES / name).read_text(encoding="utf-8")))
        runtime = CountingRuntime()

        result = await run(spec, runtime)

        assert result.status == "completed", name
        assert runtime.peak == 3, name


def test_branches_are_walked_in_order_and_take_three_steps() -> None:
    spec = parallel(
        [agent("a"), {"type": "sequence", "id": "s", "steps": [agent("b"), agent("c")]}]
    )

    assert [n.id for n in step_nodes(spec.root)] == ["a", "b", "c", "after"]
    # The parallel (entry, branches, join), after, and the margin.
    assert recursion_limit(spec) == 3 + 1 + 10


class BranchDoneSink(InMemoryEventSink):
    """Flags the end of the branch `index`."""

    def __init__(self, index: int) -> None:
        super().__init__()
        self.index = index
        self.done = asyncio.Event()

    async def emit(self, event: RunEvent) -> None:
        await super().emit(event)
        if event.type == "parallel_branch_completed" and event.payload["index"] == self.index:
            self.done.set()


async def test_resume_mid_parallel_runs_only_the_unfinished_branches() -> None:
    """AC-8 inside a parallel: a run cut off after branch 0 finished runs branches 1 and 2 again,
    not 0, and joins all three."""
    spec, checkpointer, run_id = parallel(), saver(), uuid4()
    first = CountingRuntime(delays={"b": 60, "c": 60})
    sink = BranchDoneSink(0)
    task = asyncio.create_task(
        run_workflow(spec, first, "brief", run_id=run_id, sink=sink, checkpointer=checkpointer)
    )
    await asyncio.wait_for(sink.done.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    second = CountingRuntime()
    result = await resume_workflow(
        spec,
        second,
        "brief",
        run_id=run_id,
        sink=sink,
        checkpointer=checkpointer,
        next_seq=sink.events[-1].seq + 1,
        attempt=2,
    )

    assert result.status == "completed"
    assert sorted(r.node_id for r in second.requests) == ["after", "b", "c"]
    assert result.results["review"].text == "\n\n".join(f"{b}(brief)" for b in BRANCHES)
    assert [e.seq for e in sink.events] == list(range(1, len(sink.events) + 1))
