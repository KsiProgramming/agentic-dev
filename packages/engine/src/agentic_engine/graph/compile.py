"""Compiles a workflow spec to a LangGraph graph.

v0 supports `agent`, `tool`, `gate`, `sequence`, `loop`, `map`, `reduce`, `parallel` and
`router`. Agent, tool, gate and reduce nodes become LangGraph nodes named by their spec node id;
a sequence chains its steps; a loop becomes an entry node (its id), its body, and a check node
(`<id>.check`, a name no spec node can have) that evaluates `until` and goes back to the entry or
on. A map becomes an entry
node (its id) that evaluates `over` and sends each item to a worker (`<id>.item`, one LangGraph
`Send` per item) that runs the whole body for it, and a join node (`<id>.join`) that collects the
items' results in item order. A parallel becomes an entry node (its id) that sends each branch
to a worker (`<id>.branch`, one `Send` per branch) that runs the branch, and a join node
(`<id>.join`) that applies its join policy to the branches' outcomes. A router becomes an entry
node (its id) that chooses a route and records it in the state (`routes`), each route's nodes,
and a node (`<id>.done`) every route ends at, which ends the router; a resumed run goes on in the
route it chose. An orchestrator (6.1) becomes an entry node (its id) that asks its hub for a
plan and records it in the state (`plans`), a worker (`<id>.task`, one `Send` per task) that runs
its body for one task, and a join node (`<id>.join`) that collects the tasks' results in plan
order. A node that does not complete ends the run.

A map item's body and a parallel's branch run in-process, in one LangGraph task: their routers,
the parallels inside a branch and the reduces of those run there too (`_run_inline`).

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
body, whose events carry `item`, then its end; a reduce writes the events of an agent node (a
`dedupe` or `vote` reduce: `node_started`, then its end, `node_completed` with `merged`). A
parallel writes `node_started` (payload `branches`, `join`, `quorum`),
`parallel_branch_started` and `parallel_branch_completed` around each branch, whose events carry
`branch`, then its end (payload `completed`, `failed`, `cancelled`: branch ids). Once its join is
decided, the branches still running end `node_cancelled`. A router writes `node_started` (payload
`routes`, `mode`), its classifier's agent events if it has one, `route_chosen` (`route`, `mode`,
`reason`), then the route's events and its end (`node_completed` with `route`), or `node_failed`
if no route could be chosen. An orchestrator writes `node_started` (payload `max_workers`), its
hub's agent events, `plan_made` (`tasks`, `reason`), `task_started` and `task_completed` around
each task's body, whose events carry `item` (the task's index), then its end (`node_completed`
with `tasks` and `completed`). One task that does not complete cancels the others.

An agent or tool node with typed ports (4.2) has its input checked before it starts and its
output once it completes: a value that does not match fails the node, whose `node_failed` carries
the `port` that refused it. A typed output becomes the node's `data`, and its text the JSON the
next node receives.

Run artifacts (4.3): a node with `writes` stores its output under that name once it completes
(after its output port check) in the run's `ArtifactStore` and writes `artifact_written` before
its end; one that cannot be written (a `.json` artifact that is not JSON, or one over the size
limits) fails the node. A node with `reads` takes the versions the run had when it started as its
input, instead of the previous output; its `node_started` names them (`reads`), and a name not
written yet fails it before it runs. A map's items and a parallel's branches get the run's
artifacts from when it started; a branch's writes are the run's once it ends. Loop conditions and
a map's `over` read them as `artifacts`.

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
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TypedDict, cast
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send, interrupt
from pydantic import JsonValue

from agentic_engine.agent import AgentNodeResult, AgentNodeStatus, run_agent_node, sum_usage
from agentic_engine.artifacts import (
    ArtifactError,
    ArtifactRef,
    ArtifactStore,
    InMemoryArtifactStore,
    artifact_content,
    artifact_values,
    reader_input,
    write_artifact,
)
from agentic_engine.budget import BudgetMeter
from agentic_engine.events import (
    ARTIFACT_WRITTEN,
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
    PLAN_MADE,
    POLICY_LIMIT_EXCEEDED,
    PR_OPENED,
    REPO_CREATED,
    ROUTE_CHOSEN,
    TASK_COMPLETED,
    TASK_STARTED,
    NullEventSink,
    RunEventLog,
)
from agentic_engine.expr import (
    ROUTE_VARIABLES,
    CompiledList,
    ExpressionError,
    compile_condition,
    compile_list,
)
from agentic_engine.gate import GateReview, run_gate_node
from agentic_engine.graph.checkpoint import Checkpointer
from agentic_engine.graph.deltas import DeltaBuffer
from agentic_engine.graph.state import (
    MapItem,
    OrchestratorTask,
    ParallelBranch,
    RunState,
    RunUpdate,
)
from agentic_engine.policy import PLATFORM_POLICY, Policy, PolicyLimitExceeded
from agentic_engine.ports import PortFailure, check_port
from agentic_engine.spec import (
    CREATE_TOOLS,
    DEFAULT_ROUTE,
    FINDINGS_SCHEMA,
    PUBLISH_TOOLS,
    WRITE_TOOLS,
    AgentNode,
    GateNode,
    LoopNode,
    MapNode,
    Node,
    OrchestratorNode,
    ParallelNode,
    ReduceNode,
    RouterNode,
    SequenceNode,
    ToolNode,
    WorkflowSpec,
    agents_spawned,
    classifier_schema,
    iter_nodes,
    node_tools,
    orchestrator_plan_schema,
    port_edges,
    router_routes,
    task_writer_key,
)
from agentic_engine.tool import run_tool_node
from agentic_runtime import AgentEvent, AgentRuntime, ToolExecutor, Usage
from agentic_runtime.findings import (
    Check,
    FindingsReport,
    VoteError,
    clip_message,
    merge_reports,
)

type CompiledWorkflow = CompiledStateGraph[RunState]
type StepNode = AgentNode | ToolNode | GateNode


class CompileError(ValueError):
    """The spec uses something this compiler does not support yet."""


@dataclass
class _Limits:
    """A run's policy, the slots of its `agents_alive` limit, its budget meter if it has a
    budget, the review its gates show and edit branches through, the node each typed input
    comes from (consumer id → producer id, `port_edges`) and the store of its artifacts, shared
    by all its nodes for one attempt."""

    policy: Policy
    budget: BudgetMeter | None = None
    review: GateReview | None = None
    sources: dict[str, str] = field(default_factory=dict[str, str])
    artifacts: ArtifactStore = field(default_factory=InMemoryArtifactStore)
    alive: asyncio.Semaphore = field(init=False)

    def __post_init__(self) -> None:
        self.alive = asyncio.Semaphore(self.policy.agents_alive)


def step_nodes(root: Node) -> list[StepNode]:
    """The agent, tool and gate nodes under `root` in spec order (depth first; a loop's or a
    map's body once, a parallel's branches in branch order, a router's routes in route order)."""
    steps: list[StepNode] = []
    for path, node in iter_nodes(root):
        match node:
            case AgentNode() | ToolNode() | GateNode():
                steps.append(node)
            case (
                SequenceNode()
                | LoopNode()
                | MapNode()
                | ReduceNode()
                | ParallelNode()
                | RouterNode()
                | OrchestratorNode()
            ):
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


def router_done_node_id(router: RouterNode) -> str:
    """The LangGraph node every route of `router` ends at, which ends the router."""
    return f"{router.id}.done"


def task_node_id(orchestrator: OrchestratorNode) -> str:
    """The LangGraph node that runs `orchestrator`'s body for one task."""
    return f"{orchestrator.id}.task"


def tasks_join_node_id(orchestrator: OrchestratorNode) -> str:
    """The LangGraph node that collects `orchestrator`'s task results."""
    return f"{orchestrator.id}.join"


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
            case MapNode() | ParallelNode() | OrchestratorNode():
                return 3
            case RouterNode():
                return 2 + max(steps(route) for _, _, route in router_routes(node, node.id))
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
    artifacts: ArtifactStore | None = None,
) -> CompiledWorkflow:
    """Build the graph for `spec`. Agent nodes run on `runtime`, tool nodes call `tools`, gates
    commit their edits through `review`, run artifacts go to `artifacts` (kept in memory without
    one), and all write to `log`, if given. With `checkpointer`,
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
    sources = {consumer.id: producer.id for producer, consumer, _ in port_edges(spec.root)}
    limits = _Limits(policy, budget, review, sources, artifacts or InMemoryArtifactStore())

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
                builder.add_node(check, _loop_check(node, log, limits))
                builder.add_conditional_edges(
                    check, _after_check(node, then), list(dict.fromkeys([node.id, then, END]))
                )
                return node.id
            case MapNode():
                over = compile_list(node.over)
                worker, join = item_node_id(node), join_node_id(node)
                items: dict[str, list[JsonValue]] = {}
                builder.add_node(node.id, _map_entry(node, over, log, limits, items))
                builder.add_conditional_edges(
                    node.id, _fan_out(node, over, items), [worker, join, END]
                )
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
            case OrchestratorNode():
                worker, join = task_node_id(node), tasks_join_node_id(node)
                builder.add_node(node.id, _orchestrator_entry(node, runtime, log, limits))
                builder.add_conditional_edges(node.id, _fan_out_tasks(node), [worker, join, END])
                builder.add_node(
                    worker,
                    _orchestrator_task(node, runtime, tools, log, limits),
                    input_schema=OrchestratorTask,
                )
                builder.add_edge(worker, join)
                builder.add_node(join, _orchestrator_join(node, log, limits))
                go_on(join, node.id, then)
                return node.id
            case RouterNode():
                done = router_done_node_id(node)
                builder.add_node(node.id, _router_entry(node, runtime, log, limits))
                starts = {
                    route_id: add(route, done)
                    for route_id, _, route in router_routes(node, node.id)
                }
                builder.add_conditional_edges(
                    node.id, _to_route(node, starts), list(dict.fromkeys([*starts.values(), END]))
                )
                builder.add_node(done, _router_done(node, log))
                go_on(done, node.id, then)
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
            refs = state.get("artifacts", {})
            return _run_step(node, runtime, tools, log, limits, state["last_text"], refs)

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
    refs: Mapping[str, ArtifactRef],
    item: int | None = None,
    branch: int | None = None,
    route_as: str | None = None,
) -> AgentNodeResult:
    """Run one agent, tool or gate node on `input`, writing its events (tagged with `item` inside
    a map or an orchestrator's task, `branch` inside a parallel). `route_as` is what the node is
    known by to the tools and the runtime: a task's writer key inside an orchestrator. A node that
    reads run artifacts runs on the versions in `refs` instead, and one that writes one stores its
    output once it completes. An agent waits for one of the run's `agents_alive` slots before it
    starts, and its usage is counted on the run's budget: once that is spent, the node ends
    `node_cancelled` and `PolicyLimitExceeded` is raised."""

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
                return await run_tool_node(node, tools, on_event, route_as)
            case GateNode():
                return await run_gate_node(
                    node, input, log, limits.review, limits.policy.approval_ttl_s
                )
            case AgentNode():
                async with limits.alive:
                    return await run_agent_node(node, runtime, input, on_event, route_as)

    reads = [] if isinstance(node, GateNode) else node.reads
    # A gate runs again from its start when the run continues; the runner logs its start.
    if not isinstance(node, GateNode):
        started: dict[str, JsonValue] | None = None
        if reads:
            read: list[JsonValue] = [
                {"name": name, "version": refs[name].version} for name in reads if name in refs
            ]
            started = {"reads": read}
        await log.emit(NODE_STARTED, node_id=node.id, payload=started, item=item, branch=branch)
    if reads:
        try:
            input = await reader_input(limits.artifacts, reads, refs)
        except ArtifactError as e:
            missing: dict[str, JsonValue] = {"error": str(e)}
            await log.emit(NODE_FAILED, node_id=node.id, payload=missing, item=item, branch=branch)
            return AgentNodeResult(status="failed", text=input, usage=None, error=str(e))
    if not isinstance(node, GateNode) and node.input_schema is not None:
        source = limits.sources.get(node.id)
        checked = check_port("input", node.id, node.input_schema, input, source)
        if isinstance(checked, PortFailure):
            refused: dict[str, JsonValue] = {"error": checked.error, "port": checked.payload()}
            await log.emit(NODE_FAILED, node_id=node.id, payload=refused, item=item, branch=branch)
            return AgentNodeResult(status="failed", text=input, usage=None, error=checked.error)
    try:
        try:
            result = await run()
        finally:
            await buffer.close()
    except (asyncio.CancelledError, PolicyLimitExceeded):
        await log.emit(NODE_CANCELLED, node_id=node.id, item=item, branch=branch)
        raise
    port: PortFailure | None = None
    if not isinstance(node, GateNode) and node.output_schema is not None:
        result, port = _check_output(node, result)
    if not isinstance(node, GateNode) and node.writes and result.status == "completed":
        result = await _write(node.id, node.writes, node.output_schema, result, limits, log, branch)
    if (pull := _pull_request(node, result)) is not None:
        await log.emit(PR_OPENED, node_id=node.id, payload=pull, item=item, branch=branch)
    if (repo := _created_repo(node, result)) is not None:
        await log.emit(REPO_CREATED, node_id=node.id, payload=repo, item=item, branch=branch)
    payload: dict[str, JsonValue] = {"error": result.error} if result.error else {}
    if port is not None:
        payload["port"] = port.payload()
    await log.emit(
        NODE_END[result.status], node_id=node.id, payload=payload, item=item, branch=branch
    )
    return result


def _check_output(
    node: AgentNode | ToolNode, result: AgentNodeResult
) -> tuple[AgentNodeResult, PortFailure | None]:
    """`result` checked against `node`'s `output_schema`, if it completed: with the matching
    object as its `data` and as its text (pretty JSON, which the next node gets), or failed with
    why it does not match. Its usage is kept either way. A tool's structured result is checked
    when it has one, else its text, as an agent's."""
    if result.status != "completed" or node.output_schema is None:
        return result, None
    value = result.data if isinstance(node, ToolNode) and result.data is not None else result.text
    checked = check_port("output", node.id, node.output_schema, value)
    if isinstance(checked, PortFailure):
        return result.model_copy(update={"status": "failed", "error": checked.error}), checked
    text = json.dumps(checked, indent=2, ensure_ascii=False)
    return result.model_copy(update={"data": checked, "text": text}), None


def _update(node_id: str, result: AgentNodeResult) -> RunUpdate:
    """The state update of a node that ran once and produced `result`."""
    update: RunUpdate = {
        "last_text": result.text,
        "results": {node_id: result},
        "order": [node_id],
        "usage": [result.usage] if result.usage else [],
    }
    if result.artifact is not None:
        update["artifacts"] = {result.artifact.name: result.artifact}
    return update


async def _write(
    node_id: str,
    name: str,
    output_schema: Mapping[str, JsonValue] | None,
    result: AgentNodeResult,
    limits: _Limits,
    log: RunEventLog,
    branch: int | None = None,
) -> AgentNodeResult:
    """Store the completed `result` of `node_id` as the next version of the run artifact `name`
    and log it (`artifact_written`): the result with its `artifact`, or failed with why it could
    not be written."""
    try:
        content = artifact_content(name, node_id, result.text, result.data)
        ref = await write_artifact(limits.artifacts, name, node_id, content, output_schema)
    except ArtifactError as e:
        return result.model_copy(update={"status": "failed", "error": str(e)})
    payload: dict[str, JsonValue] = ref.model_dump(
        mode="json", include={"name", "version", "media_type", "size", "sha256"}
    )
    await log.emit(ARTIFACT_WRITTEN, node_id=node_id, payload=payload, branch=branch)
    return result.model_copy(update={"artifact": ref})


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


def _loop_check(
    loop: LoopNode, log: RunEventLog, limits: _Limits
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Ends an iteration: evaluates `until`, and records the loop's result once it stops. Until
    then the loop has no result, which sends the run back to the entry."""
    condition = compile_condition(loop.until)

    async def check(state: RunState) -> RunUpdate:
        iteration = state["iterations"][loop.id]
        results = _results_context(state)
        artifacts = await _artifacts_context(loop.until, state, limits)
        try:
            met = condition.evaluate(
                last=state["last_text"], iteration=iteration, results=results, artifacts=artifacts
            )
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
    return _results_of(state["results"])


async def _artifacts_context(source: str, state: RunState, limits: _Limits) -> dict[str, JsonValue]:
    """`artifacts` as the CEL expression `source` sees it: name → content (parsed for JSON). Read
    from the store only when the expression names it."""
    if "artifacts" not in source:
        return {}
    return await artifact_values(limits.artifacts, state.get("artifacts", {}))


def _map_entry(
    map: MapNode,
    over: CompiledList,
    log: RunEventLog,
    limits: _Limits,
    evaluated: dict[str, list[JsonValue]],
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Starts the map, counting all its items' agents as spawned, or fails it if its items cannot
    be had or their agents would take the run past its `agents_spawned` limit; `_fan_out` then
    sends them, from `evaluated` (filled here, in the same LangGraph task). The items run in one
    LangGraph step, so they cannot count themselves."""
    agents_per_item = agents_spawned(map.body)

    async def enter(state: RunState) -> RunUpdate:
        try:
            artifacts = await _artifacts_context(map.over, state, limits)
            items = over.evaluate(
                last=state["last_text"], results=_results_context(state), artifacts=artifacts
            )
            evaluated[map.id] = items
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


def _fan_out(
    map: MapNode, over: CompiledList, evaluated: dict[str, list[JsonValue]]
) -> Callable[[RunState], Sequence[Send] | str]:
    """One `Send` to the worker per item, with the run's artifacts; to the join if there are
    none; to `END` if the map failed. The items are those the entry evaluated in the same task
    (`over` is evaluated again if they are missing: the entry left the state it reads
    unchanged)."""

    def route(state: RunState) -> Sequence[Send] | str:
        if map.id in state["results"]:
            return END
        items = evaluated.pop(map.id, None)
        if items is None:
            items = over.evaluate(last=state["last_text"], results=_results_context(state))
        if not items:
            return join_node_id(map)
        refs = state.get("artifacts", {})
        return [
            Send(
                item_node_id(map),
                MapItem(
                    index=i, item=item, item_input=_item_input(item), item_artifacts=dict(refs)
                ),
            )
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
    """Runs `map`'s body for one item (`_run_inline`), stopping at the first step that does not
    complete. At most `max_concurrency` items run at once."""
    slots = asyncio.Semaphore(map.max_concurrency)

    async def work(task: MapItem) -> RunUpdate:
        index = task["index"]
        async with slots:
            await log.emit(
                MAP_ITEM_STARTED, node_id=map.id, payload={"index": index, "item": task["item"]}
            )
            refs = dict(task.get("item_artifacts", {}))
            scope = _Scope(runtime, tools, log, limits, item=index, refs=refs)
            ended, result = await _run_inline(map.body, task["item_input"], scope)
            error = _stop_error(ended, result)
            usage = scope.usage()
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
    (not decided yet). A `settled` join decides only once every branch ended."""
    needed = _needed(parallel)
    if parallel.join == "settled":
        if completed + failed < len(parallel.branches):
            return None
        return "completed" if completed >= needed else "failed"
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
        case "any" | "settled":
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
    agents = sum(agents_spawned(branch) for branch in parallel.branches)
    started = _parallel_started(parallel)

    async def enter(state: RunState) -> RunUpdate:
        if refused := await _refuse_spawn(parallel.id, state, agents, limits, log, started):
            return {"results": {parallel.id: refused}, "order": [parallel.id]}
        await log.emit(NODE_STARTED, node_id=parallel.id, payload=started)
        return {"spawned": agents}

    return enter


def _parallel_started(parallel: ParallelNode) -> dict[str, JsonValue]:
    """The payload of `parallel`'s `node_started`."""
    started: dict[str, JsonValue] = {"branches": len(parallel.branches), "join": parallel.join}
    if parallel.quorum is not None:
        started["quorum"] = parallel.quorum
    return started


def _fan_out_branches(parallel: ParallelNode) -> Callable[[RunState], Sequence[Send] | str]:
    """One `Send` to the worker per branch, each with the parallel's input; to `END` if the
    parallel could not start."""

    def route(state: RunState) -> Sequence[Send] | str:
        if parallel.id in state["results"]:
            return END
        worker = branch_node_id(parallel)
        refs = state.get("artifacts", {})
        return [
            Send(
                worker,
                ParallelBranch(
                    index=i, branch_input=state["last_text"], branch_artifacts=dict(refs)
                ),
            )
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
    """Runs one of `parallel`'s branches (`_run_inline`), stopping at the first step that does
    not complete; or ends it `cancelled` once the other branches decided the join. Its nodes'
    results go into `results` (not `order`, the run's path, which a branch that fails under a join
    that is met does not stop), its outcome into `parallel_results`, and the run artifacts it
    wrote into `artifacts`; its later steps read what its earlier ones wrote."""
    join = _BranchJoin(parallel)

    async def work(task: ParallelBranch) -> RunUpdate:
        index, text = task["index"], task["branch_input"]
        branch_id = parallel.branches[index].id
        marker: dict[str, JsonValue] = {"index": index, "branch_id": branch_id}
        await log.emit(PARALLEL_BRANCH_STARTED, node_id=parallel.id, payload=marker)
        refs = dict(task.get("branch_artifacts", {}))
        scope = _Scope(runtime, tools, log, limits, branch=index, refs=refs)
        result, error = await _run_branch(join, index, parallel.branches[index], text, scope)
        end: dict[str, JsonValue] = {**marker, "status": result.status}
        if error:
            end["error"] = error
        await log.emit(PARALLEL_BRANCH_COMPLETED, node_id=parallel.id, payload=end)
        usage = scope.usage()
        outcome = AgentNodeResult(
            status=result.status,
            text=result.text,
            usage=sum_usage(usage),
            error=error,
            data={"index": index},
        )
        return {
            "results": scope.ran,
            "usage": usage,
            "parallel_results": {parallel.id: {branch_id: outcome}},
            "artifacts": scope.wrote,
        }

    return work


async def _run_branch(
    join: _BranchJoin, index: int, branch: Node, input: str, scope: "_Scope"
) -> tuple[AgentNodeResult, str | None]:
    """Run branch `index` of `join`'s parallel in `scope`, unless the join is already decided,
    and record how it ended: its result, and why it did not complete, if it did not."""
    cancelled = AgentNodeResult(status="cancelled", text=input, usage=None)
    if join.decided:
        return cancelled, "cancelled: the join was decided without it"
    error: str | None = None

    async def run() -> AgentNodeResult:
        nonlocal error
        ended, result = await _run_inline(branch, input, scope)
        error = _stop_error(ended, result)
        return result

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
    return result, error


def _parallel_join(
    parallel: ParallelNode, log: RunEventLog
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Ends the parallel by its join, from its branches' checkpointed outcomes. Its output is the
    completed branches' outputs in branch order (`data`: `outputs` by branch id, and the ids of
    the branches that `completed`, `failed` and were `cancelled`)."""

    async def join(state: RunState) -> RunUpdate:
        by_id = state.get("parallel_results", {}).get(parallel.id, {})
        outcomes = [(b.id, by_id[b.id]) for b in parallel.branches if b.id in by_id]
        result, payload = _joined(parallel, outcomes)
        await log.emit(NODE_END[result.status], node_id=parallel.id, payload=payload)
        return _update(parallel.id, result)

    return join


def _joined(
    parallel: ParallelNode, outcomes: list[tuple[str, AgentNodeResult]]
) -> tuple[AgentNodeResult, dict[str, JsonValue]]:
    """`parallel`'s result from its branches' outcomes (branch id, result; in branch order), and
    the payload of its end."""
    ids: dict[str, JsonValue] = {
        status: [i for i, o in outcomes if o.status == status]
        for status in ("completed", "failed", "cancelled")
    }
    done = [(i, o) for i, o in outcomes if o.status == "completed"]
    text = "\n\n".join(o.text for _, o in done)
    outputs: dict[str, JsonValue] = {i: o.text for i, o in done}
    # Why each branch that did not complete did not, so a merge can say which checks failed.
    errors: dict[str, JsonValue] = {
        i: o.error or o.status for i, o in outcomes if o.status != "completed"
    }
    data: dict[str, JsonValue] = {"outputs": outputs, **ids, "errors": errors}
    needed = _needed(parallel)
    if len(done) >= needed:
        return AgentNodeResult(status="completed", text=text, usage=None, data=data), ids
    error = (
        f"join {parallel.join}: {len(done)} of {len(parallel.branches)} branches completed, "
        f"{needed} needed"
    )
    if failed := next(((i, o) for i, o in outcomes if o.status == "failed"), None):
        error += f"; branch {failed[0]!r} {failed[1].error}"
    stopped = AgentNodeResult(status="failed", text=text, usage=None, error=error, data=data)
    return stopped, {"error": error, **ids}


def _reduce(
    reduce: ReduceNode,
    runtime: AgentRuntime,
    tools: ToolExecutor | None,
    log: RunEventLog,
    limits: _Limits,
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Combines the outputs of the map or parallel `reduce.from_` (a map's items in item order,
    a parallel's completed branches in branch order): `concat` joins them, `agent` runs an agent
    turn on them as a JSON array of `{item, output}` (a branch's item is its id), and `dedupe` and
    `vote` merge them as findings reports."""

    scope = _Scope(runtime, tools, log, limits)

    async def combine(state: RunState) -> RunUpdate:
        data = state["results"][reduce.from_].data or {}
        if reduce.agent is not None:
            return await _spawn(
                reduce.id, state, limits, log, lambda: _combine(reduce, data, scope)
            )
        return _update(reduce.id, await _combine(reduce, data, scope))

    return combine


async def _combine(
    reduce: ReduceNode, data: dict[str, JsonValue], scope: "_Scope"
) -> AgentNodeResult:
    """Run `reduce` on the `data` of its map or parallel, writing its events in `scope`."""
    sources = _reduce_sources(data)
    log, tag = scope.log, scope.tag()
    if reduce.merges:
        errors = data.get("errors")
        missing = [
            (branch, str(why))
            for branch, why in (errors if isinstance(errors, dict) else {}).items()
        ]
        return await _merge(reduce, sources, scope, missing)
    if reduce.agent is None:
        await log.emit(NODE_STARTED, node_id=reduce.id, **tag)
        separator = "\n\n" if reduce.separator is None else reduce.separator
        text = separator.join(str(output) for _, _, output in sources)
        result = AgentNodeResult(status="completed", text=text, usage=None)
        if reduce.writes:
            result = await _write(reduce.id, reduce.writes, None, result, scope.limits, log)
        end: dict[str, JsonValue] = {"error": result.error} if result.error else {}
        await log.emit(NODE_END[result.status], node_id=reduce.id, payload=end, **tag)
        return result
    agent = AgentNode(
        type="agent",
        id=reduce.id,
        role=reduce.agent.role,
        instructions=reduce.agent.instructions,
        provider=reduce.agent.provider,
        model=reduce.agent.model,
        writes=reduce.writes,
    )
    pairs: list[JsonValue] = [{"item": item, "output": output} for _, item, output in sources]
    input = json.dumps(pairs, ensure_ascii=False, indent=2)
    return await _run_step(
        agent, scope.runtime, scope.tools, log, scope.limits, input, {}, scope.item, scope.branch
    )


def _reduce_sources(data: dict[str, JsonValue]) -> list[tuple[str, JsonValue, JsonValue]]:
    """What a reduce combines, from its map's, parallel's or orchestrator's `data`, as `(source
    id, item, output)`: a map item is named by its index, a parallel branch by its id (also its
    item), an orchestrator's task by its id (its item is the task)."""
    match data:
        case {"tasks": list() as tasks, "outputs": list() as outputs}:
            return [
                (str(cast(dict[str, JsonValue], task)["id"]), task, output)
                for task, output in zip(tasks, outputs, strict=True)
            ]
        case {"items": list() as items, "outputs": list() as outputs}:
            return [
                (str(i), item, output)
                for i, (item, output) in enumerate(zip(items, outputs, strict=True))
            ]
        case {"outputs": dict() as outputs}:
            return [(branch, branch, output) for branch, output in outputs.items()]
        case _:
            raise AssertionError(f"not a map's or parallel's output: {sorted(data)}")


async def _merge(
    reduce: ReduceNode,
    sources: list[tuple[str, JsonValue, JsonValue]],
    scope: "_Scope",
    missing: list[tuple[str, str]],
) -> AgentNodeResult:
    """A `dedupe` or `vote` reduce (4.5): each source's output checked as a findings report, then
    merged with no model. A source that is not a report, or too few sources for the vote, fails
    the reduce. Each branch of its parallel that did not complete (`missing`: id, why) is a failed
    check of the merged report (4.6), so what was not checked is said."""
    log, limits, tag = scope.log, scope.limits, scope.tag()
    await log.emit(NODE_STARTED, node_id=reduce.id, **tag)
    reports: list[tuple[str, FindingsReport]] = []
    port: PortFailure | None = None
    error: str | None = None
    for source_id, _, output in sources:
        text = output if isinstance(output, str) else json.dumps(output)
        checked = check_port("input", reduce.id, FINDINGS_SCHEMA, text, source_id)
        if isinstance(checked, PortFailure):
            port, error = checked, checked.error
            break
        reports.append((source_id, FindingsReport.model_validate(checked)))
    merged = None
    if error is None:
        votes = (reduce.min_votes or len(reports) // 2 + 1) if reduce.strategy == "vote" else None
        try:
            merged = merge_reports(reports, min_votes=votes)
        except VoteError as e:
            error = f"vote {reduce.id!r} {e}"
    if merged is None:
        result = AgentNodeResult(status="failed", text="", usage=None, error=error)
    else:
        failed = [
            Check(path=".", kind="branch", tool=branch, status="failed", reason=clip_message(why))
            for branch, why in missing
        ]
        report = merged.report.model_copy(update={"checks": [*merged.report.checks, *failed]})
        data: dict[str, JsonValue] = report.model_dump(mode="json")
        text = json.dumps(data, indent=2, ensure_ascii=False)
        result = AgentNodeResult(status="completed", text=text, usage=None, data=data)
        if reduce.writes:
            result = await _write(reduce.id, reduce.writes, FINDINGS_SCHEMA, result, limits, log)
    end: dict[str, JsonValue] = {"error": result.error} if result.error else {}
    if port is not None:
        end["port"] = port.payload()
    if merged is not None and result.status == "completed":
        end["merged"] = {
            "sources": len(reports),
            "findings_in": merged.findings_in,
            "findings_out": len(merged.report.findings),
        }
    await log.emit(NODE_END[result.status], node_id=reduce.id, payload=end, **tag)
    return result


class _Tag(TypedDict):
    """The `item` and `branch` an in-process node's events carry."""

    item: int | None
    branch: int | None


@dataclass
class _Scope:
    """Where nodes run in-process (`_run_inline`): a map item or an orchestrator's task
    (`item`; a task also `task`: the orchestrator's id and the task's) or a parallel branch
    (`branch`, the innermost), with the run artifacts it sees (`refs`), every node it ran (`ran`,
    shared with the parallels inside it) and the artifacts it wrote (`wrote`)."""

    runtime: AgentRuntime
    tools: ToolExecutor | None
    log: RunEventLog
    limits: _Limits
    item: int | None = None
    branch: int | None = None
    refs: dict[str, ArtifactRef] = field(default_factory=dict[str, ArtifactRef])
    ran: dict[str, AgentNodeResult] = field(default_factory=dict[str, AgentNodeResult])
    wrote: dict[str, ArtifactRef] = field(default_factory=dict[str, ArtifactRef])
    task: tuple[str, str] | None = None

    def route_as(self, node: Node) -> str | None:
        """What `node` is known by to the tools: inside an orchestrator's task, a writer works as
        the task (`task_writer_key`), on the task's own branch; else as itself."""
        if self.task is None or not WRITE_TOOLS.intersection(node_tools(node)):
            return None
        return task_writer_key(*self.task)

    def tag(self) -> _Tag:
        """The `item` and `branch` its events carry."""
        return _Tag(item=self.item, branch=self.branch)

    def usage(self) -> list[Usage]:
        """The usage of every node it ran."""
        return [r.usage for r in self.ran.values() if r.usage]

    def inner(self, branch: int) -> "_Scope":
        """Branch `branch` of a parallel that runs in this scope: it sees this scope's artifacts
        and writes its own, which the parallel adds to this scope once it ends."""
        return replace(self, branch=branch, refs=dict(self.refs), wrote={})


async def _run_inline(node: Node, input: str, scope: _Scope) -> tuple[str, AgentNodeResult]:
    """Run `node` on `input` in-process, in `scope`: a sequence's steps each on the previous
    one's output, stopping at the first that does not complete. Returns the id of the node that
    ended it (the step that did not complete, else `node`) and its result."""
    match node:
        case AgentNode() | ToolNode() | GateNode():
            # Stays `cancelled` if the branch is cancelled while the step runs.
            scope.ran[node.id] = AgentNodeResult(status="cancelled", text=input, usage=None)
            result = await _run_step(
                node,
                scope.runtime,
                scope.tools,
                scope.log,
                scope.limits,
                input,
                scope.refs,
                scope.item,
                scope.branch,
                scope.route_as(node),
            )
            scope.ran[node.id] = result
            if result.artifact is not None:
                scope.refs[result.artifact.name] = result.artifact
                scope.wrote[result.artifact.name] = result.artifact
            return node.id, result
        case SequenceNode():
            ended, result = node.id, AgentNodeResult(status="completed", text=input, usage=None)
            for step in node.steps:
                ended, result = await _run_inline(step, input, scope)
                if result.status != "completed":
                    break
                input = result.text
            return ended, result
        case RouterNode():
            return await _router_inline(node, input, scope)
        case ParallelNode():
            return await _parallel_inline(node, input, scope)
        case ReduceNode():
            result = await _combine(node, scope.ran[node.from_].data or {}, scope)
            scope.ran[node.id] = result
            return node.id, result
        case LoopNode() | MapNode() | OrchestratorNode():
            raise CompileError(f"{node.type} {node.id!r} cannot run inside a map or a parallel")


def _stop_error(ended: str, result: AgentNodeResult) -> str | None:
    """Why a map item or a branch did not complete: the node that ended it, and its error."""
    if result.status == "completed":
        return None
    return f"{ended} {result.status}: {result.error or 'no error given'}"


async def _parallel_inline(
    parallel: ParallelNode, input: str, scope: _Scope
) -> tuple[str, AgentNodeResult]:
    """Run a parallel inside a branch: its branches at once, each in its own scope, joined as at
    the top of the run. What its branches wrote is the outer scope's once it ends."""
    log, tag = scope.log, scope.tag()
    await log.emit(NODE_STARTED, node_id=parallel.id, payload=_parallel_started(parallel), **tag)
    join = _BranchJoin(parallel)
    inners = [scope.inner(i) for i in range(len(parallel.branches))]

    async def one(index: int) -> tuple[str, AgentNodeResult]:
        branch = parallel.branches[index]
        marker: dict[str, JsonValue] = {"index": index, "branch_id": branch.id}
        await log.emit(PARALLEL_BRANCH_STARTED, node_id=parallel.id, payload=marker, **tag)
        result, error = await _run_branch(join, index, branch, input, inners[index])
        end: dict[str, JsonValue] = {**marker, "status": result.status}
        if error:
            end["error"] = error
        await log.emit(PARALLEL_BRANCH_COMPLETED, node_id=parallel.id, payload=end, **tag)
        return branch.id, result.model_copy(update={"error": error})

    outcomes = await asyncio.gather(*(one(i) for i in range(len(parallel.branches))))
    for inner in inners:
        scope.refs.update(inner.wrote)
        scope.wrote.update(inner.wrote)
    result, payload = _joined(parallel, list(outcomes))
    await log.emit(NODE_END[result.status], node_id=parallel.id, payload=payload, **tag)
    scope.ran[parallel.id] = result
    return parallel.id, result


def _router_started(router: RouterNode) -> dict[str, JsonValue]:
    """The payload of `router`'s `node_started`."""
    routes: list[JsonValue] = list(router.route_ids)
    return {"routes": routes, "mode": "classifier" if router.classifier else "rule"}


def _router_entry(
    router: RouterNode, runtime: AgentRuntime, log: RunEventLog, limits: _Limits
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Starts `router` and chooses its route, which `_to_route` then takes. The choice is in the
    state (`routes`; `None` if none could be made), so a resumed run does not choose again. A
    classifier counts as one agent spawned."""
    spawned = 1 if router.classifier is not None else 0
    scope = _Scope(runtime, None, log, limits)

    async def enter(state: RunState) -> RunUpdate:
        if spawned and (
            refused := await _refuse_spawn(
                router.id, state, 1, limits, log, _router_started(router)
            )
        ):
            return {
                "results": {router.id: refused},
                "order": [router.id],
                "routes": {router.id: None},
            }
        results = _results_of(state["results"])
        choice = await _choose(
            router, state["last_text"], results, state.get("artifacts", {}), scope
        )
        update: RunUpdate = {
            "spawned": spawned,
            "usage": [choice.usage] if choice.usage else [],
            "routes": {router.id: _chosen(choice)},
        }
        if choice.status != "completed":
            update["results"] = {router.id: choice}
            update["order"] = [router.id]
        return update

    return enter


def _chosen(choice: AgentNodeResult) -> str | None:
    """The route a router's choice names, if it made one."""
    route = (choice.data or {}).get("route") if choice.status == "completed" else None
    return route if isinstance(route, str) else None


def _to_route(router: RouterNode, starts: Mapping[str, str]) -> Callable[[RunState], str]:
    """To the first node of the route `router` chose; to `END` if it chose none."""

    def route(state: RunState) -> str:
        chosen = state.get("routes", {}).get(router.id)
        return starts[chosen] if chosen is not None else END

    return route


def _router_done(
    router: RouterNode, log: RunEventLog
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Ends `router` once its route completed. Its output is the route's, and its `data` the
    route's last node's."""
    outputs = {route_id: _output_id(route) for route_id, _, route in router_routes(router, "")}

    async def done(state: RunState) -> RunUpdate:
        chosen = state.get("routes", {}).get(router.id) or DEFAULT_ROUTE
        source = state["results"].get(outputs[chosen])
        await log.emit(NODE_COMPLETED, node_id=router.id, payload={"route": chosen})
        data = source.data if source is not None else None
        result = AgentNodeResult(status="completed", text=state["last_text"], usage=None, data=data)
        return _update(router.id, result)

    return done


def _output_id(node: Node) -> str:
    """The node whose result is `node`'s output: a sequence's last step's."""
    return _output_id(node.steps[-1]) if isinstance(node, SequenceNode) else node.id


async def _router_inline(
    router: RouterNode, input: str, scope: _Scope
) -> tuple[str, AgentNodeResult]:
    """Run a router inside a map item or a branch: choose, then run the route in `scope`. Its
    classifier was counted as spawned with the rest of the item or branch."""
    choice = await _choose(router, input, _results_of(scope.ran), scope.refs, scope)
    route_id = _chosen(choice)
    if route_id is None:
        scope.ran[router.id] = choice
        return router.id, choice
    ended, result = await _run_inline(router.route(route_id), input, scope)
    log, tag = scope.log, scope.tag()
    end: dict[str, JsonValue] = {"route": route_id}
    if (error := _stop_error(ended, result)) is not None:
        end["error"] = error
    await log.emit(NODE_END[result.status], node_id=router.id, payload=end, **tag)
    if result.status != "completed":
        scope.ran[router.id] = result.model_copy(update={"usage": choice.usage, "error": error})
        return ended, result
    done = AgentNodeResult(
        status="completed", text=result.text, usage=choice.usage, data=result.data
    )
    scope.ran[router.id] = done
    return router.id, done


async def _choose(
    router: RouterNode,
    input: str,
    results: dict[str, JsonValue],
    refs: Mapping[str, ArtifactRef],
    scope: _Scope,
) -> AgentNodeResult:
    """Start `router` and choose its route: by its rules, or by asking its classifier. Logs
    `route_chosen`, and returns a completed result whose `data` is `{route, mode, reason}` and
    whose usage is the classifier's; or logs `node_failed` and returns the failure."""
    log, tag = scope.log, scope.tag()
    mode = "classifier" if router.classifier is not None else "rule"
    await log.emit(NODE_STARTED, node_id=router.id, payload=_router_started(router), **tag)
    usage: Usage | None = None
    port: PortFailure | None = None
    route: str | None = None
    if router.classifier is not None:
        answer, port = await _classify(router, input, scope)
        usage = answer.usage
        if answer.status != "completed":
            error = answer.error or "the classifier did not answer"
            return await _not_routed(router, answer.status, error, input, usage, port, scope)
        route = cast(str, (answer.data or {})["route"])
        reason = cast(str, (answer.data or {})["reason"])
    else:
        try:
            route, reason = await _rule(router, input, results, refs, scope.limits)
        except ExpressionError as e:
            return await _not_routed(router, "failed", str(e), input, None, None, scope)
        if route is None:
            error = f"no route of {router.id!r} matched, and it has no default"
            return await _not_routed(router, "failed", error, input, None, None, scope)
    chosen: dict[str, JsonValue] = {"route": route, "mode": mode, "reason": reason}
    await log.emit(ROUTE_CHOSEN, node_id=router.id, payload=chosen, **tag)
    return AgentNodeResult(status="completed", text=input, usage=usage, data=chosen)


async def _not_routed(
    router: RouterNode,
    status: AgentNodeStatus,
    error: str,
    input: str,
    usage: Usage | None,
    port: PortFailure | None,
    scope: _Scope,
) -> AgentNodeResult:
    """End `router` without a route: log its end with `error` (and the classifier's refused
    `port`), and return the result."""
    end: dict[str, JsonValue] = {"error": error}
    if port is not None:
        end["port"] = port.payload()
    await scope.log.emit(NODE_END[status], node_id=router.id, payload=end, **scope.tag())
    return AgentNodeResult(status=status, text=input, usage=usage, error=error)


async def _rule(
    router: RouterNode,
    input: str,
    results: dict[str, JsonValue],
    refs: Mapping[str, ArtifactRef],
    limits: _Limits,
) -> tuple[str | None, str]:
    """The first route of `router` whose `when` holds and that condition, else its default (or
    `None` if it has none). Raises `ExpressionError` naming the route whose condition failed."""
    reads = any("artifacts" in (route.when or "") for route in router.routes)
    artifacts = await artifact_values(limits.artifacts, refs) if reads else {}
    for route in router.routes:
        when = route.when or "false"
        try:
            met = compile_condition(when, ROUTE_VARIABLES).evaluate(
                last=input, iteration=0, results=results, artifacts=artifacts
            )
        except ExpressionError as e:
            raise ExpressionError(when, f"when of route {route.id!r} failed: {e.message}") from e
        if met:
            return route.id, when
    if router.default is None:
        return None, ""
    return DEFAULT_ROUTE, "no route matched"


CLASSIFIER_ROLE = "router"
"""The role a router's classifier runs as."""


def classifier_instructions(router: RouterNode) -> str:
    """What `router`'s classifier is asked: its own instructions, then each route it may choose,
    with its description."""
    assert router.classifier is not None
    lines = [f"- `{route.id}`: {route.description or 'no description'}" for route in router.routes]
    if router.default is not None:
        lines.append(f"- `{DEFAULT_ROUTE}`: when no other route fits")
    return (
        f"{router.classifier.instructions}\n\nChoose one route for the input. The routes:\n"
        + "\n".join(lines)
        + "\n\nAnswer with the route's id as `route` and why, in one sentence, as `reason`."
    )


async def _classify(
    router: RouterNode, input: str, scope: _Scope
) -> tuple[AgentNodeResult, PortFailure | None]:
    """Ask `router`'s classifier to choose, as one agent turn whose events are the router's: its
    answer checked against `classifier_schema`, so it can only name one of the router's routes.
    It waits for an `agents_alive` slot, and its usage counts on the run's budget."""
    assert router.classifier is not None
    agent = AgentNode(
        type="agent",
        id=router.id,
        role=CLASSIFIER_ROLE,
        instructions=classifier_instructions(router),
        provider=router.classifier.provider,
        model=router.classifier.model,
        output_schema=classifier_schema(router),
    )
    log, limits = scope.log, scope.limits

    async def write(event: AgentEvent) -> None:
        await log.agent_event(router.id, event, scope.item, scope.branch)
        if isinstance(event, Usage) and limits.budget is not None:
            limits.budget.add(event, router.id)

    buffer = DeltaBuffer(write)
    try:
        try:
            async with limits.alive:
                result = await run_agent_node(agent, scope.runtime, input, buffer.emit)
        finally:
            await buffer.close()
    except (asyncio.CancelledError, PolicyLimitExceeded):
        await log.emit(NODE_CANCELLED, node_id=router.id, **scope.tag())
        raise
    return _check_output(agent, result)


def hub_instructions(orchestrator: OrchestratorNode) -> str:
    """What `orchestrator`'s hub is asked: its own instructions, then how to plan."""
    return (
        f"{orchestrator.hub.instructions}\n\nPlan the tasks for the workers, at most "
        f"{orchestrator.max_workers}. Give each task an `id` (a short slug: lower case letters, "
        "digits, `_` and `-`, unique in the plan), a `title` (one line) and `instructions` (what "
        "its worker must do, on its own: a worker sees only its task and your input). Say why you "
        "split the work so, in one sentence, as `reason`. Plan no task if there is nothing to do."
    )


async def _plan(
    orchestrator: OrchestratorNode, input: str, scope: _Scope
) -> tuple[AgentNodeResult, PortFailure | None]:
    """Ask `orchestrator`'s hub for its plan, as one agent turn whose events are the
    orchestrator's: its answer checked against `orchestrator_plan_schema`, so it cannot plan more
    than `max_workers` tasks or an off-shape one. It waits for an `agents_alive` slot, and its
    usage counts on the run's budget."""
    hub = orchestrator.hub
    agent = AgentNode(
        type="agent",
        id=orchestrator.id,
        role=hub.role,
        instructions=hub_instructions(orchestrator),
        provider=hub.provider,
        model=hub.model,
        output_schema=orchestrator_plan_schema(orchestrator),
    )
    log, limits = scope.log, scope.limits

    async def write(event: AgentEvent) -> None:
        await log.agent_event(orchestrator.id, event)
        if isinstance(event, Usage) and limits.budget is not None:
            limits.budget.add(event, orchestrator.id)

    buffer = DeltaBuffer(write)
    try:
        try:
            async with limits.alive:
                result = await run_agent_node(agent, scope.runtime, input, buffer.emit)
        finally:
            await buffer.close()
    except (asyncio.CancelledError, PolicyLimitExceeded):
        await log.emit(NODE_CANCELLED, node_id=orchestrator.id)
        raise
    return _check_output(agent, result)


def _orchestrator_entry(
    orchestrator: OrchestratorNode, runtime: AgentRuntime, log: RunEventLog, limits: _Limits
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Starts `orchestrator`: asks its hub for a plan and records it in the state (`plans`), so a
    resumed run runs the same tasks; `_fan_out_tasks` then sends them. The hub counts as one agent
    spawned, and once the plan is made every task's agents count too, all at once (the tasks run
    in one LangGraph step, so they cannot count themselves): over `agents_spawned`, the
    orchestrator fails without running a task. A plan that does not match its schema, or names a
    task twice, fails it."""
    per_task = agents_spawned(orchestrator.body)
    started: dict[str, JsonValue] = {"max_workers": orchestrator.max_workers}
    scope = _Scope(runtime, None, log, limits)
    node_id = orchestrator.id

    def stop(result: AgentNodeResult, spawned: int, usage: list[Usage]) -> RunUpdate:
        return {
            "results": {node_id: result},
            "order": [node_id],
            "spawned": spawned,
            "usage": usage,
        }

    async def enter(state: RunState) -> RunUpdate:
        if refused := await _refuse_spawn(node_id, state, 1, limits, log, started):
            return stop(refused, 0, [])
        await log.emit(NODE_STARTED, node_id=node_id, payload=started)
        input = state["last_text"]
        answer, port = await _plan(orchestrator, input, scope)
        usage = [answer.usage] if answer.usage else []
        error = answer.error
        tasks: list[JsonValue] = []
        if answer.status == "completed":
            tasks = cast(list[JsonValue], (answer.data or {}).get("tasks", []))
            ids = [cast(dict[str, JsonValue], t)["id"] for t in tasks]
            if twice := next((i for i in ids if ids.count(i) > 1), None):
                error = f"the hub of {node_id!r} planned task {twice!r} twice"
        if answer.status != "completed" or error is not None:
            status: AgentNodeStatus = "failed" if answer.status == "completed" else answer.status
            why = error or "the hub did not plan"
            end: dict[str, JsonValue] = {"error": why}
            if port is not None:
                end["port"] = port.payload()
            await log.emit(NODE_END[status], node_id=node_id, payload=end)
            failed = AgentNodeResult(status=status, text=input, usage=None, error=why)
            return stop(failed, 1, usage)
        observed = state.get("spawned", 0) + 1 + per_task * len(tasks)
        if observed > limits.policy.agents_spawned:
            over = PolicyLimitExceeded(
                "agents_spawned", limits.policy.agents_spawned, observed, node_id
            )
            await log.emit(POLICY_LIMIT_EXCEEDED, node_id=node_id, payload=over.payload())
            await log.emit(NODE_FAILED, node_id=node_id, payload={"error": over.reason})
            failed = AgentNodeResult(status="failed", text=input, usage=None, error=over.reason)
            return stop(failed, 1, usage)
        planned: list[JsonValue] = [
            {"id": t["id"], "title": t["title"]} for t in cast(list[dict[str, JsonValue]], tasks)
        ]
        reason = (answer.data or {}).get("reason", "")
        await log.emit(PLAN_MADE, node_id=node_id, payload={"tasks": planned, "reason": reason})
        return {
            "spawned": 1 + per_task * len(tasks),
            "usage": usage,
            "plans": {node_id: tasks},
        }

    return enter


def _fan_out_tasks(orchestrator: OrchestratorNode) -> Callable[[RunState], Sequence[Send] | str]:
    """One `Send` to the worker per planned task, with the run's artifacts; to the join if the
    plan has none; to `END` if the orchestrator failed. Each worker's input is `{"task", "input"}`
    as JSON: the task is data, and its worker's instructions stay the spec's."""

    def route(state: RunState) -> Sequence[Send] | str:
        if orchestrator.id in state["results"]:
            return END
        tasks = state.get("plans", {}).get(orchestrator.id) or []
        if not tasks:
            return tasks_join_node_id(orchestrator)
        refs = state.get("artifacts", {})
        return [
            Send(
                task_node_id(orchestrator),
                OrchestratorTask(
                    index=i,
                    task=task,
                    task_input=json.dumps(
                        {"task": task, "input": state["last_text"]}, ensure_ascii=False, indent=2
                    ),
                    task_artifacts=dict(refs),
                ),
            )
            for i, task in enumerate(tasks)
        ]

    return route


@dataclass
class _Workers:
    """One attempt's view of an orchestrator's tasks: those running, and whether one has not
    completed, which cancels the others; tasks that have not started then end `cancelled` without
    running. The join decides from the checkpointed outcomes, so a resumed run joins correctly."""

    running: dict[int, "asyncio.Task[tuple[str, AgentNodeResult]]"] = field(
        default_factory=dict[int, "asyncio.Task[tuple[str, AgentNodeResult]]"]
    )
    stopped: bool = False

    def end(self, index: int, status: AgentNodeStatus) -> None:
        """Record how task `index` ended; cancel the others if it did not complete."""
        self.running.pop(index, None)
        if status == "completed" or self.stopped:
            return
        self.stopped = True
        for task in self.running.values():
            task.cancel()


_CANCELLED_BY_ANOTHER = "cancelled: another task did not complete"


def _orchestrator_task(
    orchestrator: OrchestratorNode,
    runtime: AgentRuntime,
    tools: ToolExecutor | None,
    log: RunEventLog,
    limits: _Limits,
) -> Callable[[OrchestratorTask], Awaitable[RunUpdate]]:
    """Runs `orchestrator`'s body for one task (`_run_inline`), at most `max_concurrency` at once;
    its writers work on the task's own branch (`task_writer_key`). Once a task does not complete,
    the others are cancelled."""
    slots = asyncio.Semaphore(orchestrator.max_concurrency)
    workers = _Workers()

    async def work(sent: OrchestratorTask) -> RunUpdate:
        index, task = sent["index"], cast(dict[str, JsonValue], sent["task"])
        task_id = str(task["id"])
        marker: dict[str, JsonValue] = {"index": index, "task_id": task_id, "title": task["title"]}
        refs = dict(sent.get("task_artifacts", {}))
        scope = _Scope(
            runtime, tools, log, limits, item=index, refs=refs, task=(orchestrator.id, task_id)
        )
        cancelled = AgentNodeResult(status="cancelled", text=sent["task_input"], usage=None)
        async with slots:
            if workers.stopped:
                result, error = cancelled, _CANCELLED_BY_ANOTHER
            else:
                await log.emit(TASK_STARTED, node_id=orchestrator.id, payload=marker)
                runner = asyncio.create_task(
                    _run_inline(orchestrator.body, sent["task_input"], scope)
                )
                workers.running[index] = runner
                try:
                    ended, result = await runner
                    error = _stop_error(ended, result)
                except asyncio.CancelledError:
                    current = asyncio.current_task()
                    if not runner.cancelled() or (current is not None and current.cancelling()):
                        raise  # the run itself is being stopped
                    result, error = cancelled, _CANCELLED_BY_ANOTHER
                workers.end(index, result.status)
        end: dict[str, JsonValue] = {**marker, "status": result.status}
        if error:
            end["error"] = error
        await log.emit(TASK_COMPLETED, node_id=orchestrator.id, payload=end)
        usage = scope.usage()
        outcome = AgentNodeResult(
            status=result.status,
            text=result.text,
            usage=sum_usage(usage),
            error=error,
            data={"task": task},
        )
        return {"map_results": {orchestrator.id: {str(index): outcome}}, "usage": usage}

    return work


def _orchestrator_join(
    orchestrator: OrchestratorNode, log: RunEventLog, limits: _Limits
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Ends `orchestrator`. Its output is its tasks' outputs in plan order (`data`: `tasks`, the
    plan; `outputs`; `writers`, the writer keys of the tasks that completed, when its body writes,
    for a gate after it to show). It ends like the first task that failed (else the first that
    did not complete), naming the task. With `writes`, the output is stored as that artifact."""
    writes = any(WRITE_TOOLS.intersection(node_tools(n)) for _, n in iter_nodes(orchestrator.body))

    async def join(state: RunState) -> RunUpdate:
        tasks = state.get("plans", {}).get(orchestrator.id) or []
        items = ordered_items(state, orchestrator.id)
        outputs: list[JsonValue] = [r.text for r in items]
        ids = [str(cast(dict[str, JsonValue], t)["id"]) for t in tasks]
        done = [i for i, r in zip(ids, items, strict=True) if r.status == "completed"]
        writers: list[JsonValue] = (
            [task_writer_key(orchestrator.id, i) for i in done] if writes else []
        )
        data: dict[str, JsonValue] = {"tasks": tasks, "outputs": outputs, "writers": writers}
        text = "\n\n".join(r.text for r in items)
        bad = next(((i, r) for i, r in zip(ids, items, strict=True) if r.status == "failed"), None)
        bad = bad or next(
            ((i, r) for i, r in zip(ids, items, strict=True) if r.status != "completed"), None
        )
        if bad is not None:
            task_id, stopped = bad
            error = f"task {task_id!r} {stopped.error}"
            await log.emit(
                NODE_END[stopped.status], node_id=orchestrator.id, payload={"error": error}
            )
            failed = AgentNodeResult(
                status=stopped.status, text=text, usage=None, error=error, data=data
            )
            return _update(orchestrator.id, failed)
        result = AgentNodeResult(status="completed", text=text, usage=None, data=data)
        if orchestrator.writes:
            result = await _write(orchestrator.id, orchestrator.writes, None, result, limits, log)
        end: dict[str, JsonValue] = (
            {"error": result.error}
            if result.error
            else {"tasks": len(items), "completed": len(done)}
        )
        await log.emit(NODE_END[result.status], node_id=orchestrator.id, payload=end)
        return _update(orchestrator.id, result)

    return join


def _results_of(results: Mapping[str, AgentNodeResult]) -> dict[str, JsonValue]:
    """`results` as a CEL expression sees it: node id → `{status, text, data}`."""
    return {
        node_id: {"status": r.status, "text": r.text, "data": r.data}
        for node_id, r in results.items()
    }


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
