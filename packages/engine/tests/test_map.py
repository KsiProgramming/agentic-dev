"""The `map` and `reduce` primitives: map over 3 modules with max concurrency, then reduce (phase
1.10)."""

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import JsonValue

from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.graph import (
    WorkflowRunResult,
    checkpoint_serde,
    resume_workflow,
    run_workflow,
)
from agentic_engine.graph.compile import recursion_limit, step_nodes
from agentic_engine.spec import MAX_AGENTS_SPAWNED, WorkflowSpec, parse_spec
from agentic_runtime import (
    AgentEvent,
    AgentRequest,
    AgentRun,
    Failed,
    Message,
    ToolExecutor,
    ToolOutput,
    Usage,
)
from agentic_runtime.fake import ECHO_USAGE, Delay, FakeRuntime, Script
from agentic_runtime.testing import ScriptedToolExecutor

FIXTURES = Path(__file__).parent / "fixtures" / "specs" / "valid"
MODULES = ["packages/api", "packages/engine", "web"]


class CountingRuntime:
    """A fake runtime that records how many runs are in flight at once. Each node answers
    `<node>(<input>)` after waiting `delays[input]` seconds, or fails on an input in `fail`."""

    def __init__(self, delays: Mapping[str, float] | None = None, fail: str | None = None) -> None:
        self._delays = dict(delays or {})
        self._fail = fail
        self.requests: list[AgentRequest] = []
        self.live = 0
        self.peak = 0

    def start(self, request: AgentRequest) -> AgentRun:
        self.requests.append(request)
        text = request.input
        script: Script = [Delay(self._delays.get(text, 0.01))]
        if text == self._fail:
            script = [*script, Failed(error="model refused")]
        else:
            script = [*script, Message(text=f"{request.node_id}({text})"), ECHO_USAGE]
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


def module_tools(modules: list[str] | None = None) -> ScriptedToolExecutor:
    """A `list_modules` tool that returns the modules as structured data."""
    modules = MODULES if modules is None else modules
    data: dict[str, JsonValue] = {"modules": list[JsonValue](modules)}
    return ScriptedToolExecutor(
        {"repo.list_modules": ToolOutput(text="\n".join(modules), data=data)}
    )


def mapping(
    body: object,
    *,
    over: str = "results.list_modules.data.modules",
    max_concurrency: int = 2,
    reduce: Mapping[str, object] | None = None,
) -> WorkflowSpec:
    """`list_modules` (a tool), then a map `describe` over `over`, then `reduce` if given (a
    concat by default) and an agent `after`."""
    reduce_node = {"type": "reduce", "id": "join", "from": "describe", "strategy": "concat"}
    return parse_spec(
        {
            "spec_version": "0",
            "id": "mapping",
            "name": "Mapping",
            "root": {
                "type": "sequence",
                "id": "main",
                "steps": [
                    {"type": "tool", "id": "list_modules", "tool": "repo.list_modules"},
                    {
                        "type": "map",
                        "id": "describe",
                        "over": over,
                        "body": body,
                        "max_concurrency": max_concurrency,
                    },
                    {**reduce_node, **(reduce or {})},
                    agent("after"),
                ],
            },
        }
    )


def agent(id: str) -> dict[str, object]:
    return {"type": "agent", "id": id, "role": "R", "instructions": "Go."}


def saver() -> InMemorySaver:
    return InMemorySaver(serde=checkpoint_serde())


async def run(
    spec: WorkflowSpec,
    runtime: CountingRuntime,
    sink: InMemoryEventSink | None = None,
    tools: ToolExecutor | None = None,
) -> WorkflowRunResult:
    return await run_workflow(
        spec,
        runtime,
        "brief",
        sink=sink,
        checkpointer=saver(),
        tools=module_tools() if tools is None else tools,
    )


def lifecycle(events: list[RunEvent]) -> list[tuple[str, str | None, object]]:
    """Run, node and map events, with the item index of each."""
    return [
        (e.type, e.node_id, e.payload.get("index", e.payload.get("item")))
        for e in events
        if e.type.startswith(("node_", "run_", "map_"))
    ]


async def test_map_over_three_modules_with_max_concurrency_then_reduce() -> None:
    """Done when (1.10): a tool lists 3 modules, a map describes them 2 at a time, and a concat
    reduce joins the descriptions in module order."""
    runtime = CountingRuntime()

    result = await run(mapping(agent("writer")), runtime)

    assert result.status == "completed"
    assert runtime.peak == 2
    assert sorted(r.input for r in runtime.requests if r.node_id == "writer") == sorted(MODULES)
    joined = "\n\n".join(f"writer({m})" for m in MODULES)
    assert result.results["join"].text == joined
    assert runtime.requests[-1].node_id == "after"
    assert runtime.requests[-1].input == joined
    assert result.order == ["list_modules", "describe", "join", "after"]
    assert result.results["describe"].data == {
        "items": list[object](MODULES),
        "outputs": [f"writer({m})" for m in MODULES],
    }


async def test_concurrency_is_the_maps_own_limit() -> None:
    one = CountingRuntime()
    three = CountingRuntime()

    await run(mapping(agent("writer"), max_concurrency=1), one)
    await run(mapping(agent("writer"), max_concurrency=3), three)

    assert (one.peak, three.peak) == (1, 3)


async def test_outputs_keep_item_order_when_items_finish_out_of_order() -> None:
    runtime = CountingRuntime(delays={"packages/api": 0.15, "packages/engine": 0.08, "web": 0.01})
    sink = InMemoryEventSink()

    result = await run(mapping(agent("writer"), max_concurrency=3), runtime, sink)

    finished = [e.payload["index"] for e in sink.events if e.type == "map_item_completed"]
    assert finished == [2, 1, 0]
    assert result.results["describe"].data == {
        "items": list[object](MODULES),
        "outputs": [f"writer({m})" for m in MODULES],
    }


async def test_a_sequence_body_runs_in_order_for_each_item() -> None:
    body = {"type": "sequence", "id": "per-item", "steps": [agent("reader"), agent("writer")]}
    runtime = CountingRuntime()

    result = await run(mapping(body), runtime)

    writes = sorted(r.input for r in runtime.requests if r.node_id == "writer")
    assert writes == sorted(f"reader({m})" for m in MODULES)
    assert result.results["describe"].data is not None
    assert result.results["describe"].data["outputs"] == [f"writer(reader({m}))" for m in MODULES]
    assert "reader" not in result.results and "writer" not in result.results


async def test_items_that_are_not_strings_reach_the_body_as_json() -> None:
    runtime = CountingRuntime()

    result = await run(mapping(agent("writer"), over='[{"path": "api"}, 7]'), runtime)

    assert result.status == "completed"
    assert sorted(r.input for r in runtime.requests if r.node_id == "writer") == [
        "7",
        '{"path": "api"}',
    ]


async def test_a_map_with_no_items_completes_and_the_run_goes_on() -> None:
    runtime = CountingRuntime()
    sink = InMemoryEventSink()

    result = await run(mapping(agent("writer")), runtime, sink, module_tools([]))

    assert result.status == "completed"
    assert result.results["describe"].data == {"items": [], "outputs": []}
    assert result.results["join"].text == ""
    assert [r.node_id for r in runtime.requests] == ["after"]
    assert ("node_started", "describe", None) in lifecycle(sink.events)


async def test_over_that_is_not_a_list_fails_the_map() -> None:
    runtime = CountingRuntime()
    sink = InMemoryEventSink()

    result = await run(mapping(agent("writer"), over="results.list_modules.text"), runtime, sink)

    assert result.status == "failed"
    assert result.stopped_at == "describe"
    error = result.results["describe"].error
    assert error is not None and "must be a list, got StringType" in error
    assert runtime.requests == []
    assert lifecycle(sink.events)[-3:] == [
        ("node_started", "describe", None),
        ("node_failed", "describe", None),
        ("run_failed", None, None),
    ]


async def test_too_many_items_fail_the_map_with_the_limit() -> None:
    runtime = CountingRuntime()
    modules = [f"m{i}" for i in range(MAX_AGENTS_SPAWNED + 1)]

    result = await run(mapping(agent("writer")), runtime, tools=module_tools(modules))

    assert result.status == "failed"
    assert result.stopped_at == "describe"
    error = result.results["describe"].error
    assert error is not None and f"limit of {MAX_AGENTS_SPAWNED}" in error
    assert runtime.requests == []


async def test_a_failing_item_fails_the_map_and_stops_the_run() -> None:
    runtime = CountingRuntime(fail="packages/engine")
    sink = InMemoryEventSink()

    result = await run(mapping(agent("writer")), runtime, sink)

    assert result.status == "failed"
    assert result.stopped_at == "describe"
    assert result.results["describe"].error == "item 1 writer failed: model refused"
    # The other items ran to their end; nothing after the map did.
    assert sorted(r.input for r in runtime.requests) == sorted(MODULES)
    ends = {
        e.payload["index"]: e.payload["status"]
        for e in sink.events
        if e.type.startswith("map_item_c")
    }
    assert ends == {0: "completed", 1: "failed", 2: "completed"}


async def test_events_tag_each_item_and_keep_seq_order() -> None:
    sink = InMemoryEventSink()

    await run(mapping(agent("writer"), max_concurrency=1), CountingRuntime(), sink)

    assert [e.seq for e in sink.events] == list(range(1, len(sink.events) + 1))
    events = lifecycle(sink.events)
    map_events = events[events.index(("node_started", "describe", None)) :]
    assert map_events[:9] == [
        ("node_started", "describe", None),
        ("map_item_started", "describe", 0),
        ("node_started", "writer", 0),
        ("node_completed", "writer", 0),
        ("map_item_completed", "describe", 0),
        ("map_item_started", "describe", 1),
        ("node_started", "writer", 1),
        ("node_completed", "writer", 1),
        ("map_item_completed", "describe", 1),
    ]
    assert [e for e in events if e[1] == "describe" and e[0].startswith("node_")] == [
        ("node_started", "describe", None),
        ("node_completed", "describe", None),
    ]
    started = next(e for e in sink.events if e.type == "node_started" and e.node_id == "describe")
    assert started.payload == {"items": 3}
    message = next(e for e in sink.events if e.type == "message" and e.node_id == "writer")
    assert message.payload["item"] == 0
    assert message.agent_event() == Message(text="writer(packages/api)")


async def test_concat_separator_is_configurable() -> None:
    result = await run(mapping(agent("writer"), reduce={"separator": " | "}), CountingRuntime())

    assert result.results["join"].text == " | ".join(f"writer({m})" for m in MODULES)


async def test_reduce_agent_gets_items_and_outputs_as_json() -> None:
    runtime = CountingRuntime()
    reduce = {"strategy": "agent", "agent": {"role": "Architect", "instructions": "Overview."}}
    sink = InMemoryEventSink()

    result = await run(mapping(agent("writer"), reduce=reduce), runtime, sink)

    [request] = [r for r in runtime.requests if r.node_id == "join"]
    assert (request.role, request.instructions) == ("Architect", "Overview.")
    assert json.loads(request.input) == [{"item": m, "output": f"writer({m})"} for m in MODULES]
    assert result.results["join"].text == f"join({request.input})"
    assert ("node_completed", "join", None) in lifecycle(sink.events)


async def test_usage_adds_up_every_item_and_the_reduce_agent() -> None:
    reduce = {"strategy": "agent", "agent": {"role": "Architect", "instructions": "Overview."}}

    result = await run(mapping(agent("writer"), reduce=reduce), CountingRuntime())

    # 3 items, the reduce agent and `after`, each with ECHO_USAGE.
    assert result.usage == Usage(input_tokens=50, output_tokens=50)


async def test_the_fixtures_run_end_to_end() -> None:
    for name, peak in [("map-modules.json", 2), ("map-reduce-agent.json", 3)]:
        spec = parse_spec(json.loads((FIXTURES / name).read_text(encoding="utf-8")))
        runtime = CountingRuntime()

        result = await run(spec, runtime)

        assert result.status == "completed", name
        assert runtime.peak == peak, name


def test_a_map_body_is_walked_once_and_takes_three_steps() -> None:
    spec = mapping({"type": "sequence", "id": "per-item", "steps": [agent("a"), agent("b")]})

    assert [n.id for n in step_nodes(spec.root)] == ["list_modules", "a", "b", "after"]
    # list_modules, the map (entry, items, join), join, after, and the margin.
    assert recursion_limit(spec) == 1 + 3 + 1 + 1 + 10


class ItemDoneSink(InMemoryEventSink):
    """Flags the end of the map item `index`."""

    def __init__(self, index: int) -> None:
        super().__init__()
        self.index = index
        self.done = asyncio.Event()

    async def emit(self, event: RunEvent) -> None:
        await super().emit(event)
        if event.type == "map_item_completed" and event.payload["index"] == self.index:
            self.done.set()


async def test_resume_mid_map_runs_only_the_unfinished_items() -> None:
    """AC-8 inside a map: a run cut off after item 0 finished runs items 1 and 2 again, not 0."""
    spec, checkpointer, run_id = mapping(agent("writer"), max_concurrency=3), saver(), uuid4()
    first = CountingRuntime(delays={"packages/engine": 60, "web": 60})
    sink = ItemDoneSink(0)
    task = asyncio.create_task(
        run_workflow(
            spec,
            first,
            "brief",
            run_id=run_id,
            sink=sink,
            checkpointer=checkpointer,
            tools=module_tools(),
        )
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
        tools=module_tools(),
    )

    assert result.status == "completed"
    assert sorted(r.input for r in second.requests if r.node_id == "writer") == [
        "packages/engine",
        "web",
    ]
    assert result.results["join"].text == "\n\n".join(f"writer({m})" for m in MODULES)
    assert [e.seq for e in sink.events] == list(range(1, len(sink.events) + 1))
