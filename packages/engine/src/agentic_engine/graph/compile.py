"""Compiles a workflow spec to a LangGraph graph.

v0 supports `agent`, `tool`, `gate`, `sequence`, `loop`, `map`, `reduce` and `parallel`. Agent,
tool, gate
and reduce nodes become LangGraph nodes named by their spec node id; a sequence chains its steps;
a loop becomes an entry node (its id), its body, and a check node (`<id>.check`, a name no spec
node can have) that evaluates `until` and goes back to the entry or on. A map becomes an entry
node (its id) that evaluates `over` and sends each item to a worker (`<id>.item`, one LangGraph
`Send` per item) that runs the whole body for it, and a join node (`<id>.join`) that collects the
items' results in item order. A parallel becomes an entry node (its id) that sends each branch
to a worker (`<id>.branch`, one `Send` per branch) that runs the branch, and a join node
(`<id>.join`) that applies its join policy to the branches' outcomes. A node that does not
complete ends the run.

Each node writes `node_started`, its agent events (a tool node: one `tool_call` and its
`tool_result`, `pr_opened` if it published a branch, `repo_created` if it created the run's
repo) and `node_<status>` to the run's event log. A gate pauses the run (a LangGraph interrupt, so
it needs a checkpointer); the runner writes its `node_started` when the run stops there, and the
gate writes `gate_decided` and its end once it is continued. A node that creates the run's repo is
followed by a `<id>.ready` node, which interrupts the run too, with no event: the run's attempt
ends there (`suspended`), and the next one, which has the repo cloned, continues it. A loop
writes `node_started` once, `loop_iteration_started` before and `loop_condition_evaluated` after
each iteration, then `node_completed` (payload `stop_reason`,
`iterations`) when it stops, or `node_failed` if its condition cannot be evaluated. A map writes
`node_started` (payload `items`), `map_item_started` and `map_item_completed` around each item's
body, whose events carry `item`, then its end; a reduce writes the events of an agent node. A
parallel writes `node_started` (payload `branches`, `join`, `quorum`),
`parallel_branch_started` and `parallel_branch_completed` around each branch, whose events carry
`branch`, then its end (payload `completed`, `failed`, `cancelled`: branch ids). Once its join is
decided, the branches still running end `node_cancelled`.

The run's `Policy` is enforced as it goes: at most `agents_alive` agents run at once across the
whole run, and an agent node (or a map, for all its items' agents) that would take the run past
`agents_spawned` does not start. It writes `node_started`, `policy_limit_exceeded` and
`node_failed` with the reason instead, which ends the run. A run with a budget counts each agent
usage on its `BudgetMeter`: once the budget is spent, the agent that spent it and every other
running node end `node_cancelled`, and `PolicyLimitExceeded` leaves the graph for the runner to
end the run.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import cast
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send, interrupt
from pydantic import JsonValue

from agentic_engine.agent import AgentNodeResult, AgentNodeStatus, run_agent_node, sum_usage
from agentic_engine.budget import BudgetMeter
from agentic_engine.events import (
    LOOP_CONDITION_EVALUATED,
    LOOP_ITERATION_STARTED,
    MAP_ITEM_COMPLETED,
    MAP_ITEM_STARTED,
    NODE_CANCELLED,
    NODE_COMPLETED,
    NODE_FAILED,
    NODE_STARTED,
    PARALLEL_BRANCH_COMPLETED,
    PARALLEL_BRANCH_STARTED,
    POLICY_LIMIT_EXCEEDED,
    PR_OPENED,
    REPO_CREATED,
    NullEventSink,
    RunEventLog,
)
from agentic_engine.expr import CompiledList, ExpressionError, compile_condition, compile_list
from agentic_engine.gate import GateReview, run_gate_node
from agentic_engine.graph.checkpoint import Checkpointer
from agentic_engine.graph.deltas import DeltaBuffer
from agentic_engine.graph.state import MapItem, ParallelBranch, RunState, RunUpdate
from agentic_engine.policy import PLATFORM_POLICY, Policy, PolicyLimitExceeded
from agentic_engine.spec import (
    CREATE_TOOLS,
    PUBLISH_TOOLS,
    AgentNode,
    GateNode,
    LoopNode,
    MapNode,
    Node,
    ParallelNode,
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


@dataclass
class _Limits:
    """A run's policy, the slots of its `agents_alive` limit, its budget meter if it has a
    budget, and the review its gates show and edit branches through, shared by all its nodes for
    one attempt."""

    policy: Policy
    budget: BudgetMeter | None = None
    review: GateReview | None = None
    alive: asyncio.Semaphore = field(init=False)

    def __post_init__(self) -> None:
        self.alive = asyncio.Semaphore(self.policy.agents_alive)


def step_nodes(root: Node) -> list[StepNode]:
    """The agent, tool and gate nodes under `root` in spec order (depth first; a loop's or a
    map's body once, a parallel's branches in branch order)."""
    steps: list[StepNode] = []
    for path, node in iter_nodes(root):
        match node:
            case AgentNode() | ToolNode() | GateNode():
                steps.append(node)
            case SequenceNode() | LoopNode() | MapNode() | ReduceNode() | ParallelNode():
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


def branch_node_id(parallel: ParallelNode) -> str:
    """The LangGraph node that runs one of `parallel`'s branches."""
    return f"{parallel.id}.branch"


def parallel_join_node_id(parallel: ParallelNode) -> str:
    """The LangGraph node that joins `parallel`'s branches."""
    return f"{parallel.id}.join"


def repo_ready_node_id(node: ToolNode) -> str:
    """The LangGraph node after `node`, which creates the run's repo, where the run stops for a
    new attempt to clone the repo."""
    return f"{node.id}.ready"


REPO_READY_KIND = "repo_ready"
"""The `kind` of the interrupt a `<id>.ready` node raises (a gate's has none)."""


def is_repo_ready(request: object) -> bool:
    """Whether an interrupt's value is the stop after a repo was created, not a gate."""
    return (
        isinstance(request, dict)
        and cast(dict[str, object], request).get("kind") == REPO_READY_KIND
    )


def creates_repo(node: Node) -> bool:
    return isinstance(node, ToolNode) and node.tool in CREATE_TOOLS


def recursion_limit(spec: WorkflowSpec) -> int:
    """LangGraph's step limit for `spec`: one step per node run, with every loop run to its
    `max_iterations`, plus a margin. A map takes three steps whatever its item count, and a
    parallel whatever its branches: their workers run in one step. A runtime backstop for the
    spec's own bounds: a run that takes more steps fails (`GraphRecursionError`) instead of going
    on to LangGraph's default."""

    def steps(node: Node) -> int:
        match node:
            case SequenceNode():
                return sum(steps(s) for s in node.steps)
            case LoopNode():
                return node.max_iterations * (steps(node.body) + 2)
            case MapNode() | ParallelNode():
                return 3
            case ToolNode() if creates_repo(node):
                return 2  # and its `<id>.ready` node
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
    policy: Policy = PLATFORM_POLICY,
    budget: BudgetMeter | None = None,
    review: GateReview | None = None,
) -> CompiledWorkflow:
    """Build the graph for `spec`. Agent nodes run on `runtime`, tool nodes call `tools`, gates
    commit their edits through `review`, and all write to `log`, if given. With `checkpointer`,
    the state is saved after each node, in the run's thread; a spec with a gate needs one, since
    a paused run continues from it. The run's agents are held to `policy`'s `agents_alive` and
    `agents_spawned`, and their usage to `budget`; the spec itself is checked against it before
    the run (`policy_errors`)."""
    if log is None:
        log = RunEventLog(uuid4(), NullEventSink())
    steps = step_nodes(spec.root)
    if checkpointer is None and (gate := next((n for n in steps if isinstance(n, GateNode)), None)):
        raise CompileError(f"gate {gate.id!r} needs a checkpointer to pause the run")
    builder = StateGraph(RunState)
    limits = _Limits(policy, budget, review)

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
                builder.add_node(node.id, _map_entry(node, over, log, limits))
                builder.add_conditional_edges(node.id, _fan_out(node, over), [worker, join, END])
                builder.add_node(
                    worker, _map_item(node, runtime, tools, log, limits), input_schema=MapItem
                )
                builder.add_edge(worker, join)
                builder.add_node(join, _map_join(node, log))
                go_on(join, node.id, then)
                return node.id
            case ReduceNode():
                builder.add_node(node.id, _reduce(node, runtime, tools, log, limits))
                go_on(node.id, node.id, then)
                return node.id
            case ParallelNode():
                worker, join = branch_node_id(node), parallel_join_node_id(node)
                builder.add_node(node.id, _parallel_entry(node, log, limits))
                builder.add_conditional_edges(node.id, _fan_out_branches(node), [worker, END])
                builder.add_node(
                    worker,
                    _parallel_branch(node, runtime, tools, log, limits),
                    input_schema=ParallelBranch,
                )
                builder.add_edge(worker, join)
                builder.add_node(join, _parallel_join(node, log))
                go_on(join, node.id, then)
                return node.id
            case ToolNode() if creates_repo(node):
                ready = repo_ready_node_id(node)
                builder.add_node(node.id, _step(node, runtime, tools, log, limits))
                go_on(node.id, node.id, ready)
                builder.add_node(ready, _repo_ready)
                builder.add_edge(ready, then)
                return node.id
            case AgentNode() | ToolNode() | GateNode():
                builder.add_node(node.id, _step(node, runtime, tools, log, limits))
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


async def _repo_ready(state: RunState) -> RunUpdate:
    """Stop the run's attempt once its repo exists: the next attempt clones it and resumes here.
    Changes nothing, so the next node gets the creating node's output."""
    interrupt({"kind": REPO_READY_KIND})
    return {}


def _step(
    node: StepNode,
    runtime: AgentRuntime,
    tools: ToolExecutor | None,
    log: RunEventLog,
    limits: _Limits,
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    async def step(state: RunState) -> RunUpdate:
        def run() -> Awaitable[AgentNodeResult]:
            return _run_step(node, runtime, tools, log, limits, state["last_text"])

        if isinstance(node, AgentNode):
            return await _spawn(node.id, state, limits, log, run)
        return _update(node.id, await run())

    return step


async def _spawn(
    node_id: str,
    state: RunState,
    limits: _Limits,
    log: RunEventLog,
    run: Callable[[], Awaitable[AgentNodeResult]],
) -> RunUpdate:
    """Run the agent node `node_id` and count it as spawned, unless that would take the run past
    its `agents_spawned` limit: then it fails without starting."""
    if (refused := await _refuse_spawn(node_id, state, 1, limits, log)) is not None:
        return _update(node_id, refused)
    return {**_update(node_id, await run()), "spawned": 1}


async def _refuse_spawn(
    node_id: str,
    state: RunState,
    count: int,
    limits: _Limits,
    log: RunEventLog,
    started: dict[str, JsonValue] | None = None,
) -> AgentNodeResult | None:
    """If spawning `count` more agents for `node_id` would take the run past its
    `agents_spawned` limit, log the node's start (payload `started`), the limit and the node's
    failure with the reason, and return its failed result; else `None`."""
    observed = state.get("spawned", 0) + count
    if observed <= limits.policy.agents_spawned:
        return None
    over = PolicyLimitExceeded("agents_spawned", limits.policy.agents_spawned, observed, node_id)
    await log.emit(NODE_STARTED, node_id=node_id, payload=started)
    await log.emit(POLICY_LIMIT_EXCEEDED, node_id=node_id, payload=over.payload())
    await log.emit(NODE_FAILED, node_id=node_id, payload={"error": over.reason})
    return AgentNodeResult(status="failed", text=state["last_text"], usage=None, error=over.reason)


async def _run_step(
    node: StepNode,
    runtime: AgentRuntime,
    tools: ToolExecutor | None,
    log: RunEventLog,
    limits: _Limits,
    input: str,
    item: int | None = None,
    branch: int | None = None,
) -> AgentNodeResult:
    """Run one agent, tool or gate node on `input`, writing its events (tagged with `item` inside
    a map, `branch` inside a parallel). An agent waits for one of the run's `agents_alive` slots
    before it starts, and its usage is counted on the run's budget: once that is spent, the node
    ends `node_cancelled` and `PolicyLimitExceeded` is raised."""

    async def write(event: AgentEvent) -> None:
        await log.agent_event(node.id, event, item, branch)
        if isinstance(event, Usage) and limits.budget is not None:
            limits.budget.add(event, node.id)

    # Streamed text is merged so the log gets at most one `text_delta` per 250 ms.
    buffer = DeltaBuffer(write)
    on_event = buffer.emit

    async def run() -> AgentNodeResult:
        match node:
            case ToolNode():
                return await run_tool_node(node, tools, on_event)
            case GateNode():
                return await run_gate_node(
                    node, input, log, limits.review, limits.policy.approval_ttl_s
                )
            case AgentNode():
                async with limits.alive:
                    return await run_agent_node(node, runtime, input, on_event)

    # A gate runs again from its start when the run continues; the runner logs its start.
    if not isinstance(node, GateNode):
        await log.emit(NODE_STARTED, node_id=node.id, item=item, branch=branch)
    try:
        try:
            result = await run()
        finally:
            await buffer.close()
    except (asyncio.CancelledError, PolicyLimitExceeded):
        await log.emit(NODE_CANCELLED, node_id=node.id, item=item, branch=branch)
        raise
    if (pull := _pull_request(node, result)) is not None:
        await log.emit(PR_OPENED, node_id=node.id, payload=pull, item=item, branch=branch)
    if (repo := _created_repo(node, result)) is not None:
        await log.emit(REPO_CREATED, node_id=node.id, payload=repo, item=item, branch=branch)
    payload: dict[str, JsonValue] = {"error": result.error} if result.error else {}
    await log.emit(
        NODE_END[result.status], node_id=node.id, payload=payload, item=item, branch=branch
    )
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
    """The items `map` runs its body for. Raises `ExpressionError` if `over` fails."""
    return over.evaluate(last=state["last_text"], results=_results_context(state))


def _map_entry(
    map: MapNode, over: CompiledList, log: RunEventLog, limits: _Limits
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Starts the map, counting all its items' agents as spawned, or fails it if its items cannot
    be had or their agents would take the run past its `agents_spawned` limit; `_fan_out` then
    sends them. The items run in one LangGraph step, so they cannot count themselves."""
    agents_per_item = sum(isinstance(n, AgentNode) for n in step_nodes(map.body))

    async def enter(state: RunState) -> RunUpdate:
        try:
            items = _map_items(map, over, state)
        except ExpressionError as e:
            await log.emit(NODE_STARTED, node_id=map.id)
            error = f"over failed: {e}"
            await log.emit(NODE_FAILED, node_id=map.id, payload={"error": error})
            failed = AgentNodeResult(
                status="failed", text=state["last_text"], usage=None, error=error
            )
            return {"results": {map.id: failed}, "order": [map.id]}
        started: dict[str, JsonValue] = {"items": len(items)}
        spawned = agents_per_item * len(items)
        if refused := await _refuse_spawn(map.id, state, spawned, limits, log, started):
            return {"results": {map.id: refused}, "order": [map.id]}
        await log.emit(NODE_STARTED, node_id=map.id, payload=started)
        return {"spawned": spawned}

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
    map: MapNode,
    runtime: AgentRuntime,
    tools: ToolExecutor | None,
    log: RunEventLog,
    limits: _Limits,
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
                result = await _run_step(step, runtime, tools, log, limits, text, index)
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


def join_outcome(parallel: ParallelNode, completed: int, failed: int) -> AgentNodeStatus | None:
    """How `parallel` ends once `completed` of its branches completed and `failed` did not:
    `completed` once enough did for its join, `failed` once enough can no longer, else `None`
    (not decided yet)."""
    needed = _needed(parallel)
    if completed >= needed:
        return "completed"
    if len(parallel.branches) - failed < needed:
        return "failed"
    return None


def _needed(parallel: ParallelNode) -> int:
    """How many branches must complete for `parallel` to complete."""
    match parallel.join:
        case "all":
            return len(parallel.branches)
        case "any":
            return 1
        case "quorum":
            return parallel.quorum or len(parallel.branches)


@dataclass
class _BranchJoin:
    """One attempt's view of a parallel's branches: those still running, and how many of those
    that ended completed or failed. Once they decide the join, it cancels the others. This only
    saves work: the join node decides from the checkpointed outcomes, so a resumed run, which
    does not see the branches an earlier attempt finished, still joins correctly."""

    parallel: ParallelNode
    running: dict[int, "asyncio.Task[AgentNodeResult]"] = field(
        default_factory=dict[int, "asyncio.Task[AgentNodeResult]"]
    )
    completed: int = 0
    failed: int = 0
    decided: bool = False

    def end(self, index: int, status: AgentNodeStatus) -> None:
        """Record how branch `index` ended; cancel the others if that decides the join."""
        self.running.pop(index, None)
        if status == "completed":
            self.completed += 1
        elif status == "failed":
            self.failed += 1
        if self.decided or join_outcome(self.parallel, self.completed, self.failed) is None:
            return
        self.decided = True
        for task in self.running.values():
            task.cancel()


def _parallel_entry(
    parallel: ParallelNode, log: RunEventLog, limits: _Limits
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Starts the parallel, counting all its branches' agents as spawned, or fails it if they
    would take the run past its `agents_spawned` limit; `_fan_out_branches` then sends them. The
    branches run in one LangGraph step, so they cannot count themselves."""
    agents = sum(
        isinstance(n, AgentNode) for branch in parallel.branches for n in step_nodes(branch)
    )
    started: dict[str, JsonValue] = {"branches": len(parallel.branches), "join": parallel.join}
    if parallel.quorum is not None:
        started["quorum"] = parallel.quorum

    async def enter(state: RunState) -> RunUpdate:
        if refused := await _refuse_spawn(parallel.id, state, agents, limits, log, started):
            return {"results": {parallel.id: refused}, "order": [parallel.id]}
        await log.emit(NODE_STARTED, node_id=parallel.id, payload=started)
        return {"spawned": agents}

    return enter


def _fan_out_branches(parallel: ParallelNode) -> Callable[[RunState], Sequence[Send] | str]:
    """One `Send` to the worker per branch, each with the parallel's input; to `END` if the
    parallel could not start."""

    def route(state: RunState) -> Sequence[Send] | str:
        if parallel.id in state["results"]:
            return END
        worker = branch_node_id(parallel)
        return [
            Send(worker, ParallelBranch(index=i, branch_input=state["last_text"]))
            for i in range(len(parallel.branches))
        ]

    return route


def _parallel_branch(
    parallel: ParallelNode,
    runtime: AgentRuntime,
    tools: ToolExecutor | None,
    log: RunEventLog,
    limits: _Limits,
) -> Callable[[ParallelBranch], Awaitable[RunUpdate]]:
    """Runs one of `parallel`'s branches, each step on the previous one's output, stopping at the
    first step that does not complete; or ends it `cancelled` once the other branches decided
    the join. Its nodes' results go into `results` (not `order`, the run's path, which a branch
    that fails under a join that is met does not stop), its outcome into `parallel_results`."""
    join = _BranchJoin(parallel)
    steps = [step_nodes(branch) for branch in parallel.branches]

    async def work(task: ParallelBranch) -> RunUpdate:
        index, text = task["index"], task["branch_input"]
        branch_id = parallel.branches[index].id
        marker: dict[str, JsonValue] = {"index": index, "branch_id": branch_id}
        await log.emit(PARALLEL_BRANCH_STARTED, node_id=parallel.id, payload=marker)
        ran: dict[str, AgentNodeResult] = {}
        error: str | None = None

        async def run() -> AgentNodeResult:
            nonlocal error
            output = text
            result = AgentNodeResult(status="completed", text=output, usage=None)
            for step in steps[index]:
                # Stays `cancelled` if the branch is cancelled while the step runs.
                ran[step.id] = AgentNodeResult(status="cancelled", text=output, usage=None)
                result = await _run_step(step, runtime, tools, log, limits, output, branch=index)
                ran[step.id] = result
                if result.status != "completed":
                    error = f"{step.id} {result.status}: {result.error or 'no error given'}"
                    break
                output = result.text
            return result

        cancelled = AgentNodeResult(status="cancelled", text=text, usage=None)
        if join.decided:
            result = cancelled
        else:
            runner = asyncio.create_task(run())
            join.running[index] = runner
            try:
                result = await runner
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if not runner.cancelled() or (current is not None and current.cancelling()):
                    raise  # the run itself is being stopped
                result = cancelled  # the step that was running logged its end
            join.end(index, result.status)
        if result.status == "cancelled":
            error = "cancelled: the join was decided without it"
        end: dict[str, JsonValue] = {**marker, "status": result.status}
        if error:
            end["error"] = error
        await log.emit(PARALLEL_BRANCH_COMPLETED, node_id=parallel.id, payload=end)
        usage = [r.usage for r in ran.values() if r.usage]
        outcome = AgentNodeResult(
            status=result.status,
            text=result.text,
            usage=sum_usage(usage),
            error=error,
            data={"index": index},
        )
        return {
            "results": ran,
            "usage": usage,
            "parallel_results": {parallel.id: {branch_id: outcome}},
        }

    return work


def _parallel_join(
    parallel: ParallelNode, log: RunEventLog
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Ends the parallel by its join, from its branches' checkpointed outcomes. Its output is the
    completed branches' outputs in branch order (`data`: `outputs` by branch id, and the ids of
    the branches that `completed`, `failed` and were `cancelled`)."""

    async def join(state: RunState) -> RunUpdate:
        by_id = state.get("parallel_results", {}).get(parallel.id, {})
        outcomes = [(b.id, by_id[b.id]) for b in parallel.branches if b.id in by_id]
        ids: dict[str, JsonValue] = {
            status: [i for i, o in outcomes if o.status == status]
            for status in ("completed", "failed", "cancelled")
        }
        done = [(i, o) for i, o in outcomes if o.status == "completed"]
        text = "\n\n".join(o.text for _, o in done)
        outputs: dict[str, JsonValue] = {i: o.text for i, o in done}
        data: dict[str, JsonValue] = {"outputs": outputs, **ids}
        needed = _needed(parallel)
        if len(done) >= needed:
            await log.emit(NODE_COMPLETED, node_id=parallel.id, payload=ids)
            completed = AgentNodeResult(status="completed", text=text, usage=None, data=data)
            return _update(parallel.id, completed)
        error = (
            f"join {parallel.join}: {len(done)} of {len(parallel.branches)} branches completed, "
            f"{needed} needed"
        )
        if failed := next(((i, o) for i, o in outcomes if o.status == "failed"), None):
            error += f"; branch {failed[0]!r} {failed[1].error}"
        await log.emit(NODE_FAILED, node_id=parallel.id, payload={"error": error, **ids})
        stopped = AgentNodeResult(status="failed", text=text, usage=None, error=error, data=data)
        return _update(parallel.id, stopped)

    return join


def _reduce(
    reduce: ReduceNode,
    runtime: AgentRuntime,
    tools: ToolExecutor | None,
    log: RunEventLog,
    limits: _Limits,
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
        return await _spawn(
            reduce.id,
            state,
            limits,
            log,
            lambda: _run_step(agent, runtime, tools, log, limits, input),
        )

    return combine


_PULL_REQUEST_FIELDS = ("url", "number", "head", "base", "commit")


def _pull_request(node: StepNode, result: AgentNodeResult) -> dict[str, JsonValue] | None:
    """The pull request a completed publishing tool node opened, if its result names one."""
    if not (isinstance(node, ToolNode) and node.tool in PUBLISH_TOOLS):
        return None
    if result.status != "completed" or not result.data or "url" not in result.data:
        return None
    return {k: result.data[k] for k in _PULL_REQUEST_FIELDS if k in result.data}


_CREATED_REPO_FIELDS = ("full_name", "url", "default_branch", "private", "created")


def _created_repo(node: StepNode, result: AgentNodeResult) -> dict[str, JsonValue] | None:
    """The repo a completed tool node created, if its result names one."""
    if not creates_repo(node):
        return None
    if result.status != "completed" or not result.data or "full_name" not in result.data:
        return None
    return {k: result.data[k] for k in _CREATED_REPO_FIELDS if k in result.data}


def _continue_if_completed(node_id: str, next_id: str) -> Callable[[RunState], str]:
    def route(state: RunState) -> str:
        return next_id if state["results"][node_id].status == "completed" else END

    return route
