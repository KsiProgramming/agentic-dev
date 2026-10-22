"""Compiles a workflow spec to a LangGraph graph.

v0 supports `agent`, `tool`, `gate`, `sequence`, `loop`, `map` and `reduce`. Agent, tool, gate
and reduce nodes become LangGraph nodes named by their spec node id; a sequence chains its steps;
a loop becomes an entry node (its id), its body, and a check node (`<id>.check`, a name no spec
node can have) that evaluates `until` and goes back to the entry or on. A map becomes an entry
node (its id) that evaluates `over` and sends each item to a worker (`<id>.item`, one LangGraph
`Send` per item) that runs the whole body for it, and a join node (`<id>.join`) that collects the
items' results in item order. A node that does not complete ends the run.

Each node writes `node_started`, its agent events (a tool node: one `tool_call` and its
`tool_result`, and `pr_opened` if it published a branch) and `node_<status>` to the run's event
log. A gate pauses the run (a LangGraph interrupt, so it needs a checkpointer); the runner writes
its `node_started` when the run stops there, and the gate writes `gate_decided` and its end once
it is continued. A loop writes `node_started` once, `loop_iteration_started` before and
`loop_condition_evaluated` after each iteration, then `node_completed` (payload `stop_reason`,
`iterations`) when it stops, or `node_failed` if its condition cannot be evaluated. A map writes
`node_started` (payload `items`), `map_item_started` and `map_item_completed` around each item's
body, whose events carry `item`, then its end; a reduce writes the events of an agent node.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send
from pydantic import JsonValue

from agentic_engine.agent import AgentNodeResult, AgentNodeStatus, run_agent_node, sum_usage
from agentic_engine.events import (
    LOOP_CONDITION_EVALUATED,
    LOOP_ITERATION_STARTED,
    MAP_ITEM_COMPLETED,
    MAP_ITEM_STARTED,
    NODE_CANCELLED,
    NODE_COMPLETED,
    NODE_FAILED,
    NODE_STARTED,
    PR_OPENED,
    NullEventSink,
    RunEventLog,
)
from agentic_engine.expr import CompiledList, ExpressionError, compile_condition, compile_list
from agentic_engine.gate import run_gate_node
from agentic_engine.graph.checkpoint import Checkpointer
from agentic_engine.graph.state import MapItem, RunState, RunUpdate
from agentic_engine.spec import (
    MAX_AGENTS_SPAWNED,
    PUBLISH_TOOLS,
    AgentNode,
    GateNode,
    LoopNode,
    MapNode,
    Node,
    ReduceNode,
    SequenceNode,
    ToolNode,
    WorkflowSpec,
    iter_nodes,
)
from agentic_engine.tool import run_tool_node
from agentic_runtime import AgentEvent, AgentRuntime, ToolExecutor, Usage

type CompiledWorkflow = CompiledStateGraph[RunState]
type StepNode = AgentNode | ToolNode | GateNode


class CompileError(ValueError):
    """The spec uses something this compiler does not support yet."""


def step_nodes(root: Node) -> list[StepNode]:
    """The agent, tool and gate nodes under `root` in spec order (depth first; a loop's or a
    map's body once)."""
    steps: list[StepNode] = []
    for path, node in iter_nodes(root):
        match node:
            case AgentNode() | ToolNode() | GateNode():
                steps.append(node)
            case SequenceNode() | LoopNode() | MapNode() | ReduceNode():
                pass
            case _:
                raise CompileError(f"node type {node.type!r} at {path} is not supported yet")
    return steps


def check_node_id(loop: LoopNode) -> str:
    """The LangGraph node that ends each iteration of `loop`. `NodeId` has no `.`, so no spec
    node can take this name."""
    return f"{loop.id}.check"


def item_node_id(map: MapNode) -> str:
    """The LangGraph node that runs `map`'s body for one item."""
    return f"{map.id}.item"


def join_node_id(map: MapNode) -> str:
    """The LangGraph node that collects `map`'s item results."""
    return f"{map.id}.join"


def recursion_limit(spec: WorkflowSpec) -> int:
    """LangGraph's step limit for `spec`: one step per node run, with every loop run to its
    `max_iterations`, plus a margin. A map takes three steps whatever its item count: its workers
    run in one step. A runtime backstop for the spec's own bounds: a run that takes more steps
    fails (`GraphRecursionError`) instead of going on to LangGraph's default."""

    def steps(node: Node) -> int:
        match node:
            case SequenceNode():
                return sum(steps(s) for s in node.steps)
            case LoopNode():
                return node.max_iterations * (steps(node.body) + 2)
            case MapNode():
                return 3
            case AgentNode() | ToolNode() | GateNode() | ReduceNode():
                return 1

    return steps(spec.root) + 10


NODE_END: dict[AgentNodeStatus, str] = {
    "completed": NODE_COMPLETED,
    "failed": NODE_FAILED,
    "cancelled": NODE_CANCELLED,
}


def compile_workflow(
    spec: WorkflowSpec,
    runtime: AgentRuntime,
    log: RunEventLog | None = None,
    checkpointer: Checkpointer | None = None,
    tools: ToolExecutor | None = None,
) -> CompiledWorkflow:
    """Build the graph for `spec`. Agent nodes run on `runtime`, tool nodes call `tools`, and
    both write to `log`, if given. With `checkpointer`, the state is saved after each node, in
    the run's thread; a spec with a gate needs one, since a paused run continues from it."""
    if log is None:
        log = RunEventLog(uuid4(), NullEventSink())
    steps = step_nodes(spec.root)
    if checkpointer is None and (gate := next((n for n in steps if isinstance(n, GateNode)), None)):
        raise CompileError(f"gate {gate.id!r} needs a checkpointer to pause the run")
    builder = StateGraph(RunState)

    def add(node: Node, then: str) -> str:
        """Add `node`, going on to `then` once it completes (to `END` otherwise), and return the
        LangGraph node it starts at."""
        match node:
            case SequenceNode():
                for step in reversed(node.steps):
                    then = add(step, then)
                return then
            case LoopNode():
                check = check_node_id(node)
                builder.add_node(node.id, _loop_entry(node, log))
                builder.add_edge(node.id, add(node.body, check))
                builder.add_node(check, _loop_check(node, log))
                builder.add_conditional_edges(
                    check, _after_check(node, then), list(dict.fromkeys([node.id, then, END]))
                )
                return node.id
            case MapNode():
                over = compile_list(node.over)
                worker, join = item_node_id(node), join_node_id(node)
                builder.add_node(node.id, _map_entry(node, over, log))
                builder.add_conditional_edges(node.id, _fan_out(node, over), [worker, join, END])
                builder.add_node(worker, _map_item(node, runtime, tools, log), input_schema=MapItem)
                builder.add_edge(worker, join)
                builder.add_node(join, _map_join(node, log))
                go_on(join, node.id, then)
                return node.id
            case ReduceNode():
                builder.add_node(node.id, _reduce(node, runtime, tools, log))
                go_on(node.id, node.id, then)
                return node.id
            case AgentNode() | ToolNode() | GateNode():
                builder.add_node(node.id, _step(node, runtime, tools, log))
                go_on(node.id, node.id, then)
                return node.id

    def go_on(source: str, node_id: str, then: str) -> None:
        """From `source`, go on to `then` if the spec node `node_id` completed (to `END`
        otherwise)."""
        if then == END:
            builder.add_edge(source, END)
        else:
            builder.add_conditional_edges(
                source, _continue_if_completed(node_id, then), [then, END]
            )

    builder.add_edge(START, add(spec.root, END))
    return builder.compile(checkpointer=checkpointer)


def _step(
    node: StepNode, runtime: AgentRuntime, tools: ToolExecutor | None, log: RunEventLog
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    async def step(state: RunState) -> RunUpdate:
        return _update(node.id, await _run_step(node, runtime, tools, log, state["last_text"]))

    return step


async def _run_step(
    node: StepNode,
    runtime: AgentRuntime,
    tools: ToolExecutor | None,
    log: RunEventLog,
    input: str,
    item: int | None = None,
) -> AgentNodeResult:
    """Run one agent, tool or gate node on `input`, writing its events (tagged with `item` inside
    a map)."""

    async def on_event(event: AgentEvent) -> None:
        await log.agent_event(node.id, event, item)

    async def run() -> AgentNodeResult:
        match node:
            case ToolNode():
                return await run_tool_node(node, tools, on_event)
            case GateNode():
                return await run_gate_node(node, input, log)
            case AgentNode():
                return await run_agent_node(node, runtime, input, on_event)

    # A gate runs again from its start when the run continues; the runner logs its start.
    if not isinstance(node, GateNode):
        await log.emit(NODE_STARTED, node_id=node.id, item=item)
    try:
        result = await run()
    except asyncio.CancelledError:
        await log.emit(NODE_CANCELLED, node_id=node.id, item=item)
        raise
    if (pull := _pull_request(node, result)) is not None:
        await log.emit(PR_OPENED, node_id=node.id, payload=pull, item=item)
    payload: dict[str, JsonValue] = {"error": result.error} if result.error else {}
    await log.emit(NODE_END[result.status], node_id=node.id, payload=payload, item=item)
    return result


def _update(node_id: str, result: AgentNodeResult) -> RunUpdate:
    """The state update of a node that ran once and produced `result`."""
    return {
        "last_text": result.text,
        "results": {node_id: result},
        "order": [node_id],
        "usage": [result.usage] if result.usage else [],
    }


def _loop_entry(loop: LoopNode, log: RunEventLog) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Starts an iteration. The text flows on unchanged: iteration 1 gets the loop's input, and
    each later one the previous iteration's output."""

    async def enter(state: RunState) -> RunUpdate:
        iteration = state["iterations"].get(loop.id, 0) + 1
        if iteration == 1:
            await log.emit(NODE_STARTED, node_id=loop.id)
        await log.emit(LOOP_ITERATION_STARTED, node_id=loop.id, payload={"iteration": iteration})
        return {"iterations": {loop.id: iteration}}

    return enter


def _loop_check(loop: LoopNode, log: RunEventLog) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Ends an iteration: evaluates `until`, and records the loop's result once it stops. Until
    then the loop has no result, which sends the run back to the entry."""
    condition = compile_condition(loop.until)

    async def check(state: RunState) -> RunUpdate:
        iteration = state["iterations"][loop.id]
        results = _results_context(state)
        try:
            met = condition.evaluate(last=state["last_text"], iteration=iteration, results=results)
        except ExpressionError as e:
            error = f"until failed in iteration {iteration}: {e}"
            await log.emit(NODE_FAILED, node_id=loop.id, payload={"error": error})
            failed = AgentNodeResult(
                status="failed", text=state["last_text"], usage=None, error=error
            )
            return {"results": {loop.id: failed}, "order": [loop.id]}
        await log.emit(
            LOOP_CONDITION_EVALUATED,
            node_id=loop.id,
            payload={"iteration": iteration, "result": met},
        )
        if not met and iteration < loop.max_iterations:
            return {}
        stop: dict[str, JsonValue] = {
            "stop_reason": "condition" if met else "max_iterations",
            "iterations": iteration,
        }
        await log.emit(NODE_COMPLETED, node_id=loop.id, payload=stop)
        done = AgentNodeResult(status="completed", text=state["last_text"], usage=None, data=stop)
        return {"results": {loop.id: done}, "order": [loop.id]}

    return check


def _after_check(loop: LoopNode, then: str) -> Callable[[RunState], str]:
    """Back to the entry while the loop has no result; on once it completed; to `END` if its
    condition failed."""

    def route(state: RunState) -> str:
        result = state["results"].get(loop.id)
        if result is None:
            return loop.id
        return then if result.status == "completed" else END

    return route


def _results_context(state: RunState) -> dict[str, JsonValue]:
    """`results` as a CEL expression sees it: node id → `{status, text, data}`."""
    return {
        node_id: {"status": r.status, "text": r.text, "data": r.data}
        for node_id, r in state["results"].items()
    }


def _map_items(map: MapNode, over: CompiledList, state: RunState) -> list[JsonValue]:
    """The items `map` runs its body for. Raises `ExpressionError` if `over` fails, and
    `ValueError` if there are more than a run may spawn agents for."""
    items = over.evaluate(last=state["last_text"], results=_results_context(state))
    if len(items) > MAX_AGENTS_SPAWNED:
        raise ValueError(
            f"{len(items)} items is more than the limit of {MAX_AGENTS_SPAWNED} per map"
        )
    return items


def _map_entry(
    map: MapNode, over: CompiledList, log: RunEventLog
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Starts the map, or fails it if its items cannot be had; `_fan_out` then sends them."""

    async def enter(state: RunState) -> RunUpdate:
        try:
            items = _map_items(map, over, state)
        except ValueError as e:  # `ExpressionError` is a `ValueError`
            await log.emit(NODE_STARTED, node_id=map.id)
            error = f"over failed: {e}"
            await log.emit(NODE_FAILED, node_id=map.id, payload={"error": error})
            failed = AgentNodeResult(
                status="failed", text=state["last_text"], usage=None, error=error
            )
            return {"results": {map.id: failed}, "order": [map.id]}
        await log.emit(NODE_STARTED, node_id=map.id, payload={"items": len(items)})
        return {}

    return enter


def _fan_out(map: MapNode, over: CompiledList) -> Callable[[RunState], Sequence[Send] | str]:
    """One `Send` to the worker per item; to the join if there are none; to `END` if the map
    failed. `over` is evaluated again: the entry left the state it reads unchanged."""

    def route(state: RunState) -> Sequence[Send] | str:
        if map.id in state["results"]:
            return END
        items = _map_items(map, over, state)
        if not items:
            return join_node_id(map)
        return [
            Send(item_node_id(map), MapItem(index=i, item=item, item_input=_item_input(item)))
            for i, item in enumerate(items)
        ]

    return route


def _item_input(item: JsonValue) -> str:
    """A map item as its body's input: a string as is, any other value as JSON."""
    return item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)


def _map_item(
    map: MapNode, runtime: AgentRuntime, tools: ToolExecutor | None, log: RunEventLog
) -> Callable[[MapItem], Awaitable[RunUpdate]]:
    """Runs `map`'s body for one item, each step on the previous one's output, stopping at the
    first step that does not complete. At most `max_concurrency` items run at once."""
    steps = step_nodes(map.body)
    slots = asyncio.Semaphore(map.max_concurrency)

    async def work(task: MapItem) -> RunUpdate:
        index = task["index"]
        async with slots:
            await log.emit(
                MAP_ITEM_STARTED, node_id=map.id, payload={"index": index, "item": task["item"]}
            )
            text, usage, error = task["item_input"], list[Usage](), None
            result = AgentNodeResult(status="completed", text=text, usage=None)
            for step in steps:
                result = await _run_step(step, runtime, tools, log, text, index)
                if result.usage:
                    usage.append(result.usage)
                if result.status != "completed":
                    error = f"{step.id} {result.status}: {result.error or 'no error given'}"
                    break
                text = result.text
            end: dict[str, JsonValue] = {"index": index, "status": result.status}
            if error:
                end["error"] = error
            await log.emit(MAP_ITEM_COMPLETED, node_id=map.id, payload=end)
        outcome = AgentNodeResult(
            status=result.status,
            text=result.text,
            usage=sum_usage(usage),
            error=error,
            data={"item": task["item"]},
        )
        return {"map_results": {map.id: {str(index): outcome}}, "usage": usage}

    return work


def _map_join(map: MapNode, log: RunEventLog) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Ends the map. Its output is its items' outputs in item order (`data`: `items`, `outputs`);
    it ends like the first item that did not complete, if any."""

    async def join(state: RunState) -> RunUpdate:
        items = ordered_items(state, map.id)
        outputs: list[JsonValue] = [r.text for r in items]
        data: dict[str, JsonValue] = {
            "items": [r.data["item"] if r.data else None for r in items],
            "outputs": outputs,
        }
        text = "\n\n".join(r.text for r in items)
        bad = next(((i, r) for i, r in enumerate(items) if r.status != "completed"), None)
        if bad is None:
            await log.emit(NODE_COMPLETED, node_id=map.id, payload={"items": len(items)})
            done = AgentNodeResult(status="completed", text=text, usage=None, data=data)
            return _update(map.id, done)
        index, failed = bad
        error = f"item {index} {failed.error}"
        await log.emit(NODE_END[failed.status], node_id=map.id, payload={"error": error})
        stopped = AgentNodeResult(
            status=failed.status, text=text, usage=None, error=error, data=data
        )
        return _update(map.id, stopped)

    return join


def ordered_items(state: RunState, map_id: str) -> list[AgentNodeResult]:
    """The results of `map_id`'s items, in item order."""
    by_index = state["map_results"].get(map_id, {})
    return [by_index[k] for k in sorted(by_index, key=int)]


def _reduce(
    reduce: ReduceNode, runtime: AgentRuntime, tools: ToolExecutor | None, log: RunEventLog
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Combines the outputs of the map `reduce.from_`, in item order: `concat` joins them, and
    `agent` runs an agent turn on them as a JSON array of `{item, output}`."""

    async def combine(state: RunState) -> RunUpdate:
        source = state["results"][reduce.from_].data or {}
        items, outputs = source.get("items"), source.get("outputs")
        assert isinstance(items, list) and isinstance(outputs, list)
        if reduce.agent is None:
            await log.emit(NODE_STARTED, node_id=reduce.id)
            separator = "\n\n" if reduce.separator is None else reduce.separator
            text = separator.join(str(o) for o in outputs)
            await log.emit(NODE_COMPLETED, node_id=reduce.id)
            return _update(reduce.id, AgentNodeResult(status="completed", text=text, usage=None))
        agent = AgentNode(
            type="agent",
            id=reduce.id,
            role=reduce.agent.role,
            instructions=reduce.agent.instructions,
            provider=reduce.agent.provider,
            model=reduce.agent.model,
        )
        pairs: list[JsonValue] = [
            {"item": item, "output": output} for item, output in zip(items, outputs, strict=True)
        ]
        input = json.dumps(pairs, ensure_ascii=False, indent=2)
        return _update(reduce.id, await _run_step(agent, runtime, tools, log, input))

    return combine


_PULL_REQUEST_FIELDS = ("url", "number", "head", "base", "commit")


def _pull_request(node: StepNode, result: AgentNodeResult) -> dict[str, JsonValue] | None:
    """The pull request a completed publishing tool node opened, if its result names one."""
    if not (isinstance(node, ToolNode) and node.tool in PUBLISH_TOOLS):
        return None
    if result.status != "completed" or not result.data or "url" not in result.data:
        return None
    return {k: result.data[k] for k in _PULL_REQUEST_FIELDS if k in result.data}


def _continue_if_completed(node_id: str, next_id: str) -> Callable[[RunState], str]:
    def route(state: RunState) -> str:
        return next_id if state["results"][node_id].status == "completed" else END

    return route
