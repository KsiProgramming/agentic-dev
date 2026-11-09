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
with `tasks`, `completed` and `rounds`). One task that does not complete cancels the others,
unless its `replan` (6.2) lets the hub plan again: then the round settles (running tasks finish,
those not started end `dropped`), `<id>.join` goes to `<id>.replan`, which writes
`replan_started` and the hub's new `plan_made` (with `round`), and the new tasks run. An
orchestrator whose body writes merges its completed tasks' branches into its integration branch
after each round (6.3, `<id>.integrate`): `branch_integrated`; a task that conflicts counts as
failed.

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
    BRANCH_INTEGRATED,
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
    REPLAN_STARTED,
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
from agentic_engine.integrate import (
    BranchIntegrator,
    IntegrationError,
    MergeRequest,
    conflict_error,
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
    comes from (consumer id → producer id, `port_edges`), the store of its artifacts and what
    merges its orchestrators' task branches (6.3), shared by all its nodes for one attempt."""

    policy: Policy
    budget: BudgetMeter | None = None
    review: GateReview | None = None
    sources: dict[str, str] = field(default_factory=dict[str, str])
    artifacts: ArtifactStore = field(default_factory=InMemoryArtifactStore)
    integrator: BranchIntegrator | None = None
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


def integrate_node_id(orchestrator: OrchestratorNode) -> str:
    """The LangGraph node that merges `orchestrator`'s completed task branches (6.3)."""
    return f"{orchestrator.id}.integrate"


def body_writes(orchestrator: OrchestratorNode) -> bool:
    """Whether a node in `orchestrator`'s body may write to the repo: then each task writes on
    its own branch, and the completed ones are merged into the orchestrator's (6.3)."""
    return any(WRITE_TOOLS.intersection(node_tools(n)) for _, n in iter_nodes(orchestrator.body))


def replan_node_id(orchestrator: OrchestratorNode) -> str:
    """The LangGraph node where `orchestrator`'s hub plans again once a task failed (6.2)."""
    return f"{orchestrator.id}.replan"


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
            case OrchestratorNode():
                # Entry, tasks and join, then per replan the replan, tasks and join; and an
                # integrate step per round when the body writes (6.3).
                rounds = 1 + (0 if node.replan is None else node.replan.max_rounds)
                return 3 * rounds + (rounds if body_writes(node) else 0)
            case MapNode() | ParallelNode():
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
    integrator: BranchIntegrator | None = None,
) -> CompiledWorkflow:
    """Build the graph for `spec`. Agent nodes run on `runtime`, tool nodes call `tools`, gates
    commit their edits through `review`, run artifacts go to `artifacts` (kept in memory without
    one), orchestrators merge their tasks' branches through `integrator` (6.3; none are merged
    without one), and all write to `log`, if given. With `checkpointer`,
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
    limits = _Limits(
        policy, budget, review, sources, artifacts or InMemoryArtifactStore(), integrator
    )

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
                if body_writes(node):
                    merge = integrate_node_id(node)
                    builder.add_node(merge, _orchestrator_integrate(node, log, limits))
                    builder.add_edge(worker, merge)
                    builder.add_edge(merge, join)
                else:
                    builder.add_edge(worker, join)
                builder.add_node(join, _orchestrator_join(node, log, limits))
                if node.replan is None:
                    go_on(join, node.id, then)
                    return node.id
                again = replan_node_id(node)
                builder.add_node(again, _orchestrator_replan(node, runtime, log, limits))
                builder.add_conditional_edges(again, _fan_out_tasks(node), [worker, join, END])
                builder.add_conditional_edges(
                    join, _after_tasks(node, then), list(dict.fromkeys([again, then, END]))
                )
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


def hub_replan_instructions(orchestrator: OrchestratorNode, max_tasks: int) -> str:
    """What `orchestrator`'s hub is asked when a task failed (6.2): its own instructions, then
    how to replan. The tasks' outcomes are in its input, as data, never here."""
    return (
        f"{orchestrator.hub.instructions}\n\nA task of your plan did not complete. Your input is "
        "the work (`input`) and every task planned so far (`tasks`) with its `status` "
        "(`completed`, `failed` or `dropped`, never started) and its `output` or `error`. Plan "
        f"only the work still to do, at most {max_tasks} tasks: never repeat a completed task. "
        "Give each task a new `id` (a short slug: lower case letters, digits, `_` and `-`, used "
        "by no earlier task), a `title` (one line) and `instructions` (what its worker must do, "
        "on its own: a worker sees only its task and the work). Say what you changed and why, in "
        "one sentence, as `reason`. Plan no task if the work cannot or need not go on."
    )


async def _plan(
    orchestrator: OrchestratorNode,
    input: str,
    scope: _Scope,
    instructions: str | None = None,
    max_tasks: int | None = None,
) -> tuple[AgentNodeResult, PortFailure | None]:
    """Ask `orchestrator`'s hub for its plan, as one agent turn whose events are the
    orchestrator's: its answer checked against `orchestrator_plan_schema`, so it cannot plan more
    than `max_tasks` (`max_workers`) tasks or an off-shape one. `instructions` replace the first
    plan's (a replan's). It waits for an `agents_alive` slot, and its usage counts on the run's
    budget."""
    hub = orchestrator.hub
    agent = AgentNode(
        type="agent",
        id=orchestrator.id,
        role=hub.role,
        instructions=instructions or hub_instructions(orchestrator),
        provider=hub.provider,
        model=hub.model,
        output_schema=orchestrator_plan_schema(orchestrator, max_tasks),
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


def task_round(task: JsonValue) -> int:
    """The plan a task is from: 1 for the first, one more per replan (6.2). Tasks checkpointed
    before 6.2 have no `round`: they are from the first plan."""
    found = cast(dict[str, JsonValue], task).get("round", 1)
    return found if isinstance(found, int) else 1


def _plain_task(task: JsonValue) -> dict[str, JsonValue]:
    """A planned task as its worker and a reduce see it: `id`, `title` and `instructions`."""
    fields = cast(dict[str, JsonValue], task)
    return {k: fields[k] for k in ("id", "title", "instructions")}


def _task_id(task: JsonValue) -> str:
    return str(cast(dict[str, JsonValue], task)["id"])


def _dropped(result: AgentNodeResult) -> bool:
    """Whether a task never started because another failed and the hub will replan (6.2)."""
    return bool((result.data or {}).get("dropped"))


def _task_status(result: AgentNodeResult | None) -> str:
    if result is None:
        return "pending"
    return "dropped" if _dropped(result) else result.status


@dataclass
class _Round:
    """An orchestrator's tasks as they stand: every task planned (each with its `round`), the
    results of those that ended (by index), and the latest round (`number`, from `rounds`: a
    replan may plan no task)."""

    tasks: list[JsonValue]
    results: dict[int, AgentNodeResult]
    number: int

    @classmethod
    def of(cls, orchestrator: OrchestratorNode, state: RunState) -> "_Round":
        tasks = state.get("plans", {}).get(orchestrator.id) or []
        ended = state["map_results"].get(orchestrator.id, {})
        made = state.get("rounds", {}).get(orchestrator.id, 1)
        number = max([made, *(task_round(t) for t in tasks)])
        return cls(list(tasks), {int(k): v for k, v in ended.items()}, number)

    def indices(self, round: int) -> list[int]:
        return [i for i, t in enumerate(self.tasks) if task_round(t) == round]

    def failed(self, round: int) -> list[int]:
        """The tasks of `round` that ended without completing and were not dropped."""
        ended = [(i, self.results[i]) for i in self.indices(round) if i in self.results]
        return [i for i, r in ended if r.status != "completed" and not _dropped(r)]

    def completed(self) -> list[int]:
        return [i for i, r in sorted(self.results.items()) if r.status == "completed"]


def _replan_due(orchestrator: OrchestratorNode, state: RunState) -> bool:
    """Whether `orchestrator`'s hub should plan again (6.2): it replans on failure, has rounds
    left, has not ended, and a task of its latest round failed."""
    if orchestrator.replan is None or orchestrator.id in state["results"]:
        return False
    tasks = _Round.of(orchestrator, state)
    return tasks.number - 1 < orchestrator.replan.max_rounds and bool(tasks.failed(tasks.number))


def _orchestrator_entry(
    orchestrator: OrchestratorNode, runtime: AgentRuntime, log: RunEventLog, limits: _Limits
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Starts `orchestrator`: asks its hub for a plan and records it in the state (`plans`, each
    task with `round` 1), so a resumed run runs the same tasks; `_fan_out_tasks` then sends them.
    The hub counts as one agent spawned, and once the plan is made every task's agents count too,
    all at once (the tasks run in one LangGraph step, so they cannot count themselves): over
    `agents_spawned`, the orchestrator fails without running a task. A plan that does not match
    its schema, or names a task twice, fails it."""
    started: dict[str, JsonValue] = {"max_workers": orchestrator.max_workers}
    scope = _Scope(runtime, None, log, limits)
    node_id = orchestrator.id

    async def enter(state: RunState) -> RunUpdate:
        if refused := await _refuse_spawn(node_id, state, 1, limits, log, started):
            return _stopped(node_id, refused, 0, [])
        await log.emit(NODE_STARTED, node_id=node_id, payload=started)
        return await _make_plan(orchestrator, state, scope, round=1)

    return enter


def _stopped(node_id: str, result: AgentNodeResult, spawned: int, usage: list[Usage]) -> RunUpdate:
    """The update of an orchestrator that ended while (re)planning."""
    return {"results": {node_id: result}, "order": [node_id], "spawned": spawned, "usage": usage}


async def _over_spawned(
    node_id: str, observed: int, text: str, scope: _Scope
) -> AgentNodeResult | None:
    """If `observed` agents spawned takes the run past its `agents_spawned` limit, log the limit
    and `node_id`'s failure, and return its failed result; else `None`. The node has started."""
    limit = scope.limits.policy.agents_spawned
    if observed <= limit:
        return None
    over = PolicyLimitExceeded("agents_spawned", limit, observed, node_id)
    await scope.log.emit(POLICY_LIMIT_EXCEEDED, node_id=node_id, payload=over.payload())
    await scope.log.emit(NODE_FAILED, node_id=node_id, payload={"error": over.reason})
    return AgentNodeResult(status="failed", text=text, usage=None, error=over.reason)


async def _make_plan(
    orchestrator: OrchestratorNode,
    state: RunState,
    scope: _Scope,
    round: int,
    input: str | None = None,
    earlier: Sequence[JsonValue] = (),
) -> RunUpdate:
    """One hub turn and its plan: round 1 on the orchestrator's input, a replan (6.2) on
    `input` (the tasks' outcomes) with no more tasks than `max_workers` less those completed,
    none reusing the id of a task in `earlier`. The plan, appended to `earlier` with its `round`,
    goes in the state; a plan off its schema, naming a task twice or more agents than
    `agents_spawned` allows ends the orchestrator. The hub's agent already counts on
    `agents_spawned` (its caller checked it)."""
    node_id, log = orchestrator.id, scope.log
    per_task = agents_spawned(orchestrator.body)
    text = state["last_text"]
    if round == 1:
        answer, port = await _plan(orchestrator, text, scope)
    else:
        done = len(_Round.of(orchestrator, state).completed())
        cap = orchestrator.max_workers - done
        answer, port = await _plan(
            orchestrator,
            input or text,
            scope,
            instructions=hub_replan_instructions(orchestrator, cap),
            max_tasks=cap,
        )
    usage = [answer.usage] if answer.usage else []
    error = answer.error
    tasks: list[JsonValue] = []
    if answer.status == "completed":
        tasks = cast(list[JsonValue], (answer.data or {}).get("tasks", []))
        ids = [_task_id(t) for t in tasks]
        used = {_task_id(t) for t in earlier}
        if twice := next((i for i in ids if ids.count(i) > 1), None):
            error = f"the hub of {node_id!r} planned task {twice!r} twice"
        elif again := next((i for i in ids if i in used), None):
            error = f"the hub of {node_id!r} planned task {again!r} again"
    if answer.status != "completed" or error is not None:
        status: AgentNodeStatus = "failed" if answer.status == "completed" else answer.status
        why = error or "the hub did not plan"
        end: dict[str, JsonValue] = {"error": why}
        if port is not None:
            end["port"] = port.payload()
        await log.emit(NODE_END[status], node_id=node_id, payload=end)
        failed = AgentNodeResult(status=status, text=text, usage=None, error=why)
        return _stopped(node_id, failed, 1, usage)
    observed = state.get("spawned", 0) + 1 + per_task * len(tasks)
    if refused := await _over_spawned(node_id, observed, text, scope):
        return _stopped(node_id, refused, 1, usage)
    planned: list[JsonValue] = [
        {"id": t["id"], "title": t["title"]} for t in cast(list[dict[str, JsonValue]], tasks)
    ]
    reason = (answer.data or {}).get("reason", "")
    await log.emit(
        PLAN_MADE, node_id=node_id, payload={"tasks": planned, "reason": reason, "round": round}
    )
    numbered: list[JsonValue] = [{**_plain_task(t), "round": round} for t in tasks]
    return {
        "spawned": 1 + per_task * len(tasks),
        "usage": usage,
        "plans": {node_id: [*earlier, *numbered]},
        "rounds": {node_id: round},
    }


def _orchestrator_replan(
    orchestrator: OrchestratorNode, runtime: AgentRuntime, log: RunEventLog, limits: _Limits
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Asks `orchestrator`'s hub to plan again once a round settled with a failed task (6.2):
    `replan_started`, then one hub turn on `{input, round, tasks}` as JSON, every task so far
    with its round, status and output or error (data: an error may quote the repo). The new
    round's tasks are appended to the plan; `_fan_out_tasks` sends them. The hub counts as one
    more agent spawned."""
    scope = _Scope(runtime, None, log, limits)
    node_id = orchestrator.id

    async def replan(state: RunState) -> RunUpdate:
        tasks = _Round.of(orchestrator, state)
        round = tasks.number + 1
        failed: list[JsonValue] = []
        dropped: list[JsonValue] = []
        outcomes: list[JsonValue] = []
        for i, task in enumerate(tasks.tasks):
            result = tasks.results.get(i)
            status = _task_status(result)
            outcome: dict[str, JsonValue] = {
                **_plain_task(task),
                "round": task_round(task),
                "status": status,
            }
            if result is not None and status == "completed":
                outcome["output"] = result.text
            elif result is not None and status != "dropped":
                outcome["error"] = result.error or result.status
            outcomes.append(outcome)
            if task_round(task) == tasks.number and status == "dropped":
                dropped.append(_task_id(task))
        for i in tasks.failed(tasks.number):
            result = tasks.results[i]
            failed.append({"id": _task_id(tasks.tasks[i]), "error": result.error or result.status})
        await log.emit(
            REPLAN_STARTED,
            node_id=node_id,
            payload={"round": round, "failed": failed, "dropped": dropped},
        )
        text = state["last_text"]
        if refused := await _over_spawned(node_id, state.get("spawned", 0) + 1, text, scope):
            return _stopped(node_id, refused, 0, [])
        input = json.dumps(
            {"input": state["last_text"], "round": round, "tasks": outcomes},
            ensure_ascii=False,
            indent=2,
        )
        return await _make_plan(
            orchestrator, state, scope, round=round, input=input, earlier=tasks.tasks
        )

    return replan


def _fan_out_tasks(orchestrator: OrchestratorNode) -> Callable[[RunState], Sequence[Send] | str]:
    """One `Send` to the worker per planned task that has not run (the latest round's), with the
    run's artifacts; to the join if there is none; to `END` if the orchestrator failed. Each
    worker's input is `{"task", "input"}` as JSON: the task is data, and its worker's
    instructions stay the spec's. A task's index is its place in the whole plan, every round's
    tasks after the last round's, so `item` tags and results never collide."""

    def route(state: RunState) -> Sequence[Send] | str:
        if orchestrator.id in state["results"]:
            return END
        tasks = _Round.of(orchestrator, state)
        todo = [i for i in range(len(tasks.tasks)) if i not in tasks.results]
        if not todo:
            return tasks_join_node_id(orchestrator)
        refs = state.get("artifacts", {})
        return [
            Send(
                task_node_id(orchestrator),
                OrchestratorTask(
                    index=i,
                    task=tasks.tasks[i],
                    task_input=json.dumps(
                        {"task": _plain_task(tasks.tasks[i]), "input": state["last_text"]},
                        ensure_ascii=False,
                        indent=2,
                    ),
                    task_artifacts=dict(refs),
                ),
            )
            for i in todo
        ]

    return route


@dataclass
class _Workers:
    """One round's view of an orchestrator's tasks: those running, and whether one has not
    completed. Then tasks that have not started never run: they end `cancelled`, or `dropped`
    when the hub will replan (`settle`, 6.2). Without `settle` the running ones are cancelled;
    with it they finish, so no work is thrown away. The join decides from the checkpointed
    outcomes, so a resumed run joins correctly."""

    settle: bool = False
    running: dict[int, "asyncio.Task[tuple[str, AgentNodeResult]]"] = field(
        default_factory=dict[int, "asyncio.Task[tuple[str, AgentNodeResult]]"]
    )
    stopped: bool = False

    def end(self, index: int, status: AgentNodeStatus) -> None:
        """Record how task `index` ended; stop the round if it did not complete."""
        self.running.pop(index, None)
        if status == "completed" or self.stopped:
            return
        self.stopped = True
        if self.settle:
            return
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
    no other task of its round starts and the running ones are cancelled, or, while the hub may
    still replan (6.2), finish."""
    slots = asyncio.Semaphore(orchestrator.max_concurrency)
    rounds: dict[int, _Workers] = {}
    replan = orchestrator.replan

    def workers_of(round: int) -> _Workers:
        if round not in rounds:
            settle = replan is not None and round - 1 < replan.max_rounds
            rounds[round] = _Workers(settle=settle)
        return rounds[round]

    async def work(sent: OrchestratorTask) -> RunUpdate:
        index, task = sent["index"], _plain_task(sent["task"])
        workers = workers_of(task_round(sent["task"]))
        task_id = str(task["id"])
        marker: dict[str, JsonValue] = {"index": index, "task_id": task_id, "title": task["title"]}
        refs = dict(sent.get("task_artifacts", {}))
        scope = _Scope(
            runtime, tools, log, limits, item=index, refs=refs, task=(orchestrator.id, task_id)
        )
        cancelled = AgentNodeResult(status="cancelled", text=sent["task_input"], usage=None)
        dropped = False
        async with slots:
            if workers.stopped:
                result, error = cancelled, _CANCELLED_BY_ANOTHER
                dropped = workers.settle
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
        end: dict[str, JsonValue] = {**marker, "status": "dropped" if dropped else result.status}
        if error and not dropped:
            end["error"] = error
        await log.emit(TASK_COMPLETED, node_id=orchestrator.id, payload=end)
        usage = scope.usage()
        data: dict[str, JsonValue] = {"task": task}
        if dropped:
            data["dropped"] = True
        outcome = AgentNodeResult(
            status=result.status,
            text=result.text,
            usage=sum_usage(usage),
            error=None if dropped else error,
            data=data,
        )
        return {"map_results": {orchestrator.id: {str(index): outcome}}, "usage": usage}

    return work


def _orchestrator_integrate(
    orchestrator: OrchestratorNode, log: RunEventLog, limits: _Limits
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Merges the branches of `orchestrator`'s completed tasks, in plan order, into its
    integration branch once a round's tasks ended (6.3), before the join decides. It asks for
    every completed task each time, as the integrator merges none twice, so a resumed run merges
    what it missed. `branch_integrated` says what was merged. A task that conflicts with those
    merged before it becomes a failure (`conflicts with earlier tasks on …`), which the join and
    a replan (6.2) treat as any failed task; its own branch is left as it was. Without an
    integrator, or with no completed task, nothing happens. An integration branch that cannot be
    built fails the orchestrator."""
    node_id = orchestrator.id

    async def integrate(state: RunState) -> RunUpdate:
        integrator = limits.integrator
        if integrator is None or node_id in state["results"]:
            return {}
        tasks = _Round.of(orchestrator, state)
        done = tasks.completed()
        if not done:
            return {}
        keys = {task_writer_key(node_id, _task_id(tasks.tasks[i])): i for i in done}
        sources = [
            MergeRequest(key=key, message=_merge_message(tasks.tasks[i])) for key, i in keys.items()
        ]
        try:
            outcome = await integrator.integrate(node_id, sources)
        except IntegrationError as e:
            error = f"cannot build the integration branch: {e}"
            await log.emit(NODE_FAILED, node_id=node_id, payload={"error": error})
            failed = AgentNodeResult(
                status="failed", text=state["last_text"], usage=None, error=error
            )
            return _stopped(node_id, failed, 0, [])
        merged: list[JsonValue] = [_task_id(tasks.tasks[keys[k]]) for k in outcome.merged]
        empty: list[JsonValue] = [_task_id(tasks.tasks[keys[k]]) for k in outcome.empty]
        conflicts: list[JsonValue] = []
        failures: dict[str, AgentNodeResult] = {}
        for key, paths in outcome.conflicts.items():
            index = keys[key]
            conflicts.append({"id": _task_id(tasks.tasks[index]), "paths": list(paths)})
            failures[str(index)] = tasks.results[index].model_copy(
                update={"status": "failed", "error": conflict_error(paths)}
            )
        await log.emit(
            BRANCH_INTEGRATED,
            node_id=node_id,
            payload={
                "round": tasks.number,
                "branch": outcome.branch,
                "head": outcome.head,
                "merged": merged,
                "empty": empty,
                "conflicts": conflicts,
            },
        )
        update: RunUpdate = {
            "integrated": {
                node_id: {
                    "branch": outcome.branch,
                    "head": outcome.head,
                    "merged": merged,
                    "empty": empty,
                }
            }
        }
        if failures:
            update["map_results"] = {node_id: failures}
        return update

    return integrate


def _merge_message(task: JsonValue) -> str:
    """A task's merge commit message: `Merge task '<id>': <title>`."""
    title = cast(dict[str, JsonValue], task).get("title", "")
    return f"Merge task '{_task_id(task)}': {title}"


def _orchestrator_join(
    orchestrator: OrchestratorNode, log: RunEventLog, limits: _Limits
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Ends `orchestrator` once a round's tasks ended, unless its hub replans (6.2: then it
    changes nothing and `<id>.replan` runs next). Its output is its completed tasks' outputs in
    plan order (`data`: `tasks`, those tasks; `outputs`; `writers`, for a gate after it to show:
    the orchestrator's id once its integration branch (6.3) merged a task, else none, or each
    completed task's writer key when there is no integrator; `branch` and `merged` once
    integrated; `plan`, every task planned with its `round` and `status`; `rounds`). It
    completes when every task of its latest round completed (a replan that plans nothing
    completes it if a task completed before), else it ends like the first
    task of that round that failed (else the first that did not complete), naming the task. With
    `writes`, the output is stored as that artifact."""
    writes = body_writes(orchestrator)

    async def join(state: RunState) -> RunUpdate:
        if orchestrator.id in state["results"] or _replan_due(orchestrator, state):
            return {}  # it failed integrating, or its hub plans again
        tasks = _Round.of(orchestrator, state)
        rounds = tasks.number
        done = tasks.completed()
        done_tasks: list[JsonValue] = [_plain_task(tasks.tasks[i]) for i in done]
        outputs: list[JsonValue] = [tasks.results[i].text for i in done]
        integrated = state.get("integrated", {}).get(orchestrator.id)
        writers: list[JsonValue] = []
        if writes and integrated is not None:
            writers = [orchestrator.id] if integrated.get("merged") else []
        elif writes and limits.integrator is None:
            writers = [task_writer_key(orchestrator.id, _task_id(tasks.tasks[i])) for i in done]
        plan: list[JsonValue] = [
            {
                **_plain_task(t),
                "round": task_round(t),
                "status": _task_status(tasks.results.get(i)),
            }
            for i, t in enumerate(tasks.tasks)
        ]
        data: dict[str, JsonValue] = {
            "tasks": done_tasks,
            "outputs": outputs,
            "writers": writers,
            "plan": plan,
            "rounds": rounds,
        }
        if integrated is not None:
            data["branch"] = integrated.get("branch")
            data["merged"] = integrated.get("merged", [])
        text = "\n\n".join(str(o) for o in outputs)
        latest = tasks.indices(rounds)
        if not latest and rounds > 1 and not done:
            latest = tasks.indices(rounds - 1)  # a replan that planned nothing, nothing done
        ended = [(i, tasks.results[i]) for i in latest if i in tasks.results]
        bad = next(((i, r) for i, r in ended if r.status == "failed"), None)
        bad = bad or next(((i, r) for i, r in ended if r.status != "completed"), None)
        if bad is not None:
            index, stopped = bad
            error = f"task {_task_id(tasks.tasks[index])!r} {stopped.error}"
            if rounds > 1:
                error += f" (after {rounds - 1} {'replan' if rounds == 2 else 'replans'})"
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
            else {"tasks": len(tasks.tasks), "completed": len(done), "rounds": rounds}
        )
        if integrated is not None and not result.error:
            end["branch"] = integrated.get("branch")
            end["merged"] = integrated.get("merged", [])
        await log.emit(NODE_END[result.status], node_id=orchestrator.id, payload=end)
        return _update(orchestrator.id, result)

    return join


def _after_tasks(orchestrator: OrchestratorNode, then: str) -> Callable[[RunState], str]:
    """Where a round's join goes (6.2): to `<id>.replan` when the hub replans, else on to `then`
    if the orchestrator completed (`END` otherwise)."""
    replan = replan_node_id(orchestrator)

    def route(state: RunState) -> str:
        if _replan_due(orchestrator, state):
            return replan
        return then if state["results"][orchestrator.id].status == "completed" else END

    return route


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
