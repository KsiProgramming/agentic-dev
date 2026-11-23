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
failed. An orchestrator in a loop's body (6.9) plans afresh each iteration (its plan kept under
`<id>#<iteration>`), its hub given the loop body's input and every earlier iteration's tasks as
data; its tasks from the second iteration on start from its one integration branch, and its
`plan_made`, `task_*`, `replan_started` and `branch_integrated` carry `iteration`. A task starts
from the integration branch whenever it exists: a follow-up of a pull request review (7.6)
restores it, so even its first pass builds on what the pull request holds.

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
import functools
import hashlib
import json
import logging
import re
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Final, TypedDict, cast
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send, interrupt
from pydantic import JsonValue

from agentic_engine.agent import (
    AgentNodeResult,
    AgentNodeStatus,
    IssueBrief,
    RunContext,
    SpecFile,
    run_agent_node,
    sum_usage,
    work_before_text,
)
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
from agentic_engine.branches import BranchSaver, owner_node
from agentic_engine.breakers import BreakerTripped, BreakerWatch, paused_before_text
from agentic_engine.budget import BudgetMeter
from agentic_engine.commit import run_commit_node
from agentic_engine.events import (
    ARTIFACT_WRITTEN,
    BRANCH_INTEGRATED,
    BRANCH_SAVE_FAILED,
    BRANCH_SAVED,
    EVIDENCE_COLLECTED,
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
    PROTECTED_PATH_REFUSED,
    REPLAN_STARTED,
    REPO_CREATED,
    REVIEW_COLLECTED,
    ROUTE_CHOSEN,
    TASK_COMPLETED,
    TASK_STARTED,
    WRITES_PLANNED,
    NullEventSink,
    RunEventLog,
)
from agentic_engine.evidence import collect, pack_payload, send_back_comments
from agentic_engine.expr import (
    ROUTE_VARIABLES,
    CompiledList,
    ExpressionError,
    compile_condition,
    compile_list,
    compile_value,
)
from agentic_engine.gate import EvidenceInput, GateReview, run_gate_node, run_wait_node
from agentic_engine.graph.checkpoint import Checkpointer
from agentic_engine.graph.deltas import DeltaBuffer
from agentic_engine.graph.state import (
    MapItem,
    OrchestratorTask,
    ParallelBranch,
    RunState,
    RunUpdate,
)
from agentic_engine.graph.steps import top_step_of
from agentic_engine.integrate import (
    BranchIntegrator,
    IntegrationError,
    MergeRequest,
    conflict_error,
)
from agentic_engine.policy import PLATFORM_POLICY, Policy, PolicyLimitExceeded
from agentic_engine.ports import PortFailure, check_port
from agentic_engine.protect import (
    frozen_rules,
    protected_payload,
    protected_text,
    static_rules,
)
from agentic_engine.providers import ResolvedNode, ResolvedProviders
from agentic_engine.review import NONE, diff_stats, evidence_summary, review_input
from agentic_engine.review_gate import (
    ReviewInput,
    neutralise_notes,
    notes_text,
    shown_of,
)
from agentic_engine.review_gate import (
    send_back_comments as review_send_back,
)
from agentic_engine.spec import (
    BODY_FROM_TOOLS,
    COMMIT_TOOLS,
    CREATE_TOOLS,
    DEFAULT_ROUTE,
    FINDINGS_SCHEMA,
    JIRA_WRITE_TOOLS,
    PUBLISH_TOOLS,
    READ_TOOLS,
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
    SubflowNode,
    ToolNode,
    WaitForNode,
    WorkflowSpec,
    agents_spawned,
    classifier_schema,
    iter_nodes,
    node_tools,
    orchestrator_plan_schema,
    planned_writes,
    port_edges,
    router_routes,
    task_writer_key,
    task_writer_orchestrators,
    writer_node_ids,
)
from agentic_engine.spec.subflows import expression_views
from agentic_engine.tool import run_tool_node
from agentic_engine.write_plan import failing_plan, plan_call
from agentic_runtime import (
    AgentEvent,
    AgentRuntime,
    ProtectedPaths,
    ProtectRule,
    ReadableWriter,
    ReadableWriters,
    ToolExecutor,
    Usage,
)
from agentic_runtime.findings import (
    SEVERITIES,
    Check,
    FindingsReport,
    VoteError,
    clip_message,
    merge_reports,
)
from agentic_runtime.plans import WritePlan

_logger = logging.getLogger("agentic_engine")

type CompiledWorkflow = CompiledStateGraph[RunState]
type StepNode = AgentNode | ToolNode | GateNode


def _baselines(stored: Mapping[str, JsonValue] | None) -> dict[str, float]:
    """The USD each node usually costs, from a run's stored `cost_baselines`."""
    found: dict[str, float] = {}
    for node, entry in (stored or {}).items():
        mean = entry.get("mean_usd") if isinstance(entry, dict) else None
        if isinstance(mean, int | float):
            found[node] = float(mean)
    return found


def _with_pause(context: str, paused: Mapping[str, JsonValue] | None) -> str:
    """`context` with the "# Paused before" section of a node a breaker paused (13.7)."""
    if paused is None:
        return context
    note = paused_before_text(paused)
    return f"{context}\n\n{note}" if context else note


def _watch(node_id: str, limits: "_Limits", paths: Sequence[str] | None = None) -> BreakerWatch:
    """The circuit-breaker watch of one execution of the agent step `node_id` (13.7): with its
    node's usual cost, if the run has a baseline for it, and the paths it declared."""
    return BreakerWatch(
        node_id, limits.policy.breakers, average_usd=limits.baselines.get(node_id), paths=paths
    )


class CompileError(ValueError):
    """The spec uses something this compiler does not support yet."""


@dataclass
class _Limits:
    """A run's policy, the slots of its `agents_alive` limit, its budget meter if it has a
    budget, the review its gates show and edit branches through, the node each typed input
    comes from (consumer id → producer id, `port_edges`), the store of its artifacts, what
    merges its orchestrators' task branches (6.3), what every agent is told about the run
    (`context`, `RunContext.text`) and what saves its branches outside the sandbox (`saver`,
    12.2), shared by all its nodes for one attempt."""

    policy: Policy
    budget: BudgetMeter | None = None
    review: GateReview | None = None
    sources: dict[str, str] = field(default_factory=dict[str, str])
    artifacts: ArtifactStore = field(default_factory=InMemoryArtifactStore)
    integrator: BranchIntegrator | None = None
    views: dict[str, dict[str, str]] = field(default_factory=dict[str, dict[str, str]])
    context: str = ""
    saver: BranchSaver | None = None
    request: str | None = None
    issue: IssueBrief | None = None
    spec: SpecFile | None = None
    loops: dict[str, str] = field(default_factory=dict[str, str])
    """Each router in a loop's body → the innermost loop around it (7.9: `iteration` in `when`)."""
    providers: ResolvedProviders | None = None
    """The provider and model of each agent-like node, as the run stored them (8.3); none means
    each node's own, on Claude when it names none."""
    readable: ReadableWriters | None = None
    """What the repo tools resolve a call's `node` through (13.1); the engine sets it before every
    step that can read."""
    writer_ids: frozenset[str] = frozenset()
    """The run's writer nodes, outside orchestrators (each has its own branch)."""
    team_ids: frozenset[str] = frozenset()
    """The orchestrators whose tasks write (each has an integration branch once it merged)."""
    roles: dict[str, str] = field(default_factory=dict[str, str])
    """Each agent's and orchestrator's role, for what a later step is told about its work."""
    parallel_loops: dict[str, str] = field(default_factory=dict[str, str])
    """Each parallel in a loop's body → the innermost loop around it (13.6): its branches' outcomes
    are kept per pass, so a later pass never joins an earlier one's."""
    baselines: dict[str, float] = field(default_factory=dict[str, float])
    """What each node usually costs, in USD per execution (13.7): the cost breaker watches the
    nodes that have one."""
    pauses: dict[str, Mapping[str, JsonValue]] = field(
        default_factory=dict[str, Mapping[str, JsonValue]]
    )
    """The `breaker_tripped` payload of each node a circuit breaker paused (13.7), until the node's
    next run takes it (`take_pause`): that run is told why it was paused."""
    evidence_loops: dict[str, tuple[str, int]] = field(default_factory=dict[str, tuple[str, int]])
    """Each gate with evidence (13.3) → its loop's id and `max_iterations`: the checks never send
    the work back on the loop's last pass, which would end the loop with the work unapproved."""
    base_lint: dict[str, Mapping[str, object] | None] = field(
        default_factory=dict[str, Mapping[str, object] | None]
    )
    """The base commit's lint report per gate with evidence (13.3), read once per attempt."""
    protected: ProtectedPaths | None = None
    """What the repo tools refuse every writer (13.5); the engine sets its rules at compile time
    and a writer's frozen files when its step starts."""
    allow: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    """The workflow's `protect.allow`: the protected paths each writer may change."""
    start_gates: dict[str, str] = field(default_factory=dict[str, str])
    """Each node with a `start_from` → the gate that approves the work it starts from."""
    alive: asyncio.Semaphore = field(init=False)

    def __post_init__(self) -> None:
        self.alive = asyncio.Semaphore(self.policy.agents_alive)

    def provider_payload(self, node_id: str) -> dict[str, JsonValue]:
        """The `provider` and `model` an agent-like node's `node_started` carries (8.3); nothing
        when the run has no stored resolution."""
        found = self.resolved(node_id)
        return {} if found is None else {"provider": found.provider, "model": found.model}

    def work_text(
        self,
        node: AgentNode,
        writers: Sequence[ReadableWriter],
        reads_as: str | None,
        reviewing: str | None = None,
        paused: Mapping[str, JsonValue] | None = None,
    ) -> str:
        """The context `node` is told: the run's, then the work before it (13.1), the paths it
        may not change (13.5) and, if a circuit breaker paused its last attempt, why (13.7)."""
        work = work_before_text(node, writers, self.roles, reads_as, reviewing)
        if self.protected is not None and WRITE_TOOLS.intersection(node.tools):
            key = reads_as or node.id
            owner = key.partition(".")[0]
            guard = protected_text(self.protected.rules_for(key), self.allow.get(owner, ()))
            work = f"{work}\n\n{guard}" if work else guard
        if node.paths:
            only = ", ".join(f"`{g}`" for g in node.paths)
            note = (
                "# Declared paths\n\nYou may write only these paths: a write anywhere else "
                f"is refused and pauses the run for a person.\n\n- {only}"
            )
            work = f"{work}\n\n{note}" if work else note
        if paused is not None:
            note = paused_before_text(paused)
            work = f"{work}\n\n{note}" if work else note
        return f"{self.context}\n\n{work}" if work and self.context else work or self.context

    def take_pause(self, node_id: str) -> Mapping[str, JsonValue] | None:
        """The trip that paused `node_id`, once: only the node's next run is told about it."""
        return self.pauses.pop(node_id, None)

    def announce(self, writers: Sequence[ReadableWriter]) -> None:
        """Tell the repo tools which writers the step that is about to run may read."""
        if self.readable is not None:
            self.readable.set(list(writers), self.writer_ids | self.team_ids)

    def resolved(self, node_id: str) -> ResolvedNode | None:
        """The provider and model stored for the agent-like node `node_id`, if the run has any."""
        return self.providers.of(node_id) if self.providers is not None else None


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
                | SubflowNode()
            ):
                pass
            case _:
                raise CompileError(f"node type {node.type!r} at {path} is not supported yet")
    return steps


def evidence_node_id(gate: GateNode) -> str:
    """The LangGraph node that checks a writer's work before `gate` (13.3). `NodeId` has no
    `.`, so no spec node can take this name; the gate's send-backs are counted under it too."""
    return f"{gate.id}.evidence"


def review_node_id(gate: GateNode) -> str:
    """The LangGraph node that reads the review's findings before `gate` (13.6). Its send-backs are
    counted under the gate's `evidence_node_id`, with the checks'."""
    return f"{gate.id}.review"


def plan_node_id(gate: GateNode) -> str:
    """The LangGraph node that asks the writes `gate` guards for their plans (13.8), the last
    step before the gate. Its plans are in the state the gate's pause shows."""
    return f"{gate.id}.plan"


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


def subflow_done_node_id(subflow: SubflowNode) -> str:
    """The LangGraph node the workflow `subflow` calls ends at, which ends the subflow (6.5)."""
    return f"{subflow.id}.done"


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

    planned = planned_writes(spec.root)

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
            case SubflowNode():
                return 2 + (steps(node.call) if node.call is not None else 0)
            case ToolNode() if creates_repo(node):
                return 2  # and its `<id>.ready` node
            case GateNode():
                # The gate, and the steps before it: its checks, its review and its plan (13.8).
                return (
                    1
                    + (node.evidence is not None)
                    + (node.review is not None)
                    + (node.id in planned)
                )
            case AgentNode() | ToolNode() | ReduceNode():
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
    context: RunContext | None = None,
    saver: BranchSaver | None = None,
    providers: ResolvedProviders | None = None,
    readable: ReadableWriters | None = None,
    protected: ProtectedPaths | None = None,
    paused: Mapping[str, Mapping[str, JsonValue]] | None = None,
    cost_baselines: Mapping[str, JsonValue] | None = None,
) -> CompiledWorkflow:
    """Build the graph for `spec`. Agent nodes run on `runtime`, tool nodes call `tools`, gates
    commit their edits through `review`, run artifacts go to `artifacts` (kept in memory without
    one), orchestrators merge their tasks' branches through `integrator` (6.3; none are merged
    without one), every agent is told `context` about the run (the repository it works on), and
    all write to `log`, if given. Each step that may commit saves the run's branches through
    `saver` before it is checkpointed (12.2; nothing is saved without one). Each agent runs on
    the provider and model `providers` stored for its node (8.3; its own when none). Before each
    step the engine tells `readable` which writers it may read, and the agent itself (13.1). With
    `checkpointer`, the state is saved after each node, in the run's thread; a spec with a gate
    needs one, since a paused run continues from it. The run's agents are held to `policy`'s
    `agents_alive` and `agents_spawned`, and their usage to `budget`; the spec itself is checked
    against it before the run (`policy_errors`). `paused` is the `breaker_tripped` payload of each
    node a circuit breaker paused, for a run resumed after it (13.7): the node's next run is told
    why, in its context. `cost_baselines` is what each node usually costs
    (`{node_id: {mean_usd, runs}}`), for the cost breaker."""
    if log is None:
        log = RunEventLog(uuid4(), NullEventSink())
    steps = step_nodes(spec.root)
    if checkpointer is None and (gate := next((n for n in steps if isinstance(n, GateNode)), None)):
        raise CompileError(f"gate {gate.id!r} needs a checkpointer to pause the run")
    builder = StateGraph(RunState)
    sources = {consumer.id: producer.id for producer, consumer, _ in port_edges(spec.root)}
    limits = _Limits(
        policy,
        budget,
        review,
        sources,
        artifacts or InMemoryArtifactStore(),
        integrator,
        expression_views(spec.root),
        context.text() if context is not None else "",
        saver,
        context.request if context is not None else None,
        context.issue if context is not None else None,
        context.spec if context is not None else None,
    )
    limits.loops = _enclosing_loops(spec.root)
    limits.evidence_loops = _evidence_loops(spec.root)
    limits.parallel_loops = _parallel_loops(spec.root)
    limits.providers = providers
    limits.readable = readable
    limits.pauses = dict(paused or {})
    limits.baselines = _baselines(cost_baselines)
    if protected is not None:
        limits.protected = protected
        policy_paths = spec.protect
        limits.allow = dict(policy_paths.allow) if policy_paths is not None else {}
        protected.set(static_rules(policy_paths), limits.allow)
        protected.on_refused = _refusal_event(log)
    limits.start_gates = _start_gates(spec.root)
    limits.writer_ids = frozenset(writer_node_ids(spec.root))
    limits.team_ids = frozenset(task_writer_orchestrators(spec.root))
    limits.roles = {
        n.id: n.role if isinstance(n, AgentNode) else n.hub.role
        for _, n in iter_nodes(spec.root)
        if isinstance(n, AgentNode | OrchestratorNode)
    }

    planned = planned_writes(spec.root)  # gate id → the outward writes it shows plans of
    writes = {n.id: n for _, n in iter_nodes(spec.root) if isinstance(n, ToolNode)}
    loops: list[LoopNode] = []  # the loops `add` is inside
    top = top_step_of(spec)  # node id → the top-level step it runs in, for saved branches (12.4)

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
                loops.append(node)
                builder.add_edge(node.id, add(node.body, check))
                loops.pop()
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
                    node.id, _fan_out(node, over, items, limits), [worker, join, END]
                )
                builder.add_node(
                    worker,
                    _saving(
                        _map_item(node, runtime, tools, log, limits), log, limits, top[node.id]
                    ),
                    input_schema=MapItem,
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
                builder.add_conditional_edges(
                    node.id, _fan_out_branches(node, limits), [worker, END]
                )
                builder.add_node(
                    worker,
                    _saving(
                        _parallel_branch(node, runtime, tools, log, limits),
                        log,
                        limits,
                        top[node.id],
                    ),
                    input_schema=ParallelBranch,
                )
                builder.add_edge(worker, join)
                builder.add_node(join, _parallel_join(node, log, limits))
                go_on(join, node.id, then)
                return node.id
            case OrchestratorNode():
                at = _Orchestration(node, loops[-1] if loops else None)
                worker, join = task_node_id(node), tasks_join_node_id(node)
                builder.add_node(node.id, _orchestrator_entry(at, runtime, log, limits))
                builder.add_conditional_edges(
                    node.id, _fan_out_tasks(at, limits), [worker, join, END]
                )
                builder.add_node(
                    worker,
                    _saving(
                        _orchestrator_task(at, runtime, tools, log, limits),
                        log,
                        limits,
                        top[node.id],
                    ),
                    input_schema=OrchestratorTask,
                )
                if body_writes(node):
                    merge = integrate_node_id(node)
                    builder.add_node(
                        merge,
                        _saving(
                            _orchestrator_integrate(at, log, limits), log, limits, top[node.id]
                        ),
                    )
                    builder.add_edge(worker, merge)
                    builder.add_edge(merge, join)
                else:
                    builder.add_edge(worker, join)
                builder.add_node(join, _orchestrator_join(at, log, limits))
                if node.replan is None:
                    go_on(join, node.id, then)
                    return node.id
                again = replan_node_id(node)
                builder.add_node(again, _orchestrator_replan(at, runtime, log, limits))
                builder.add_conditional_edges(
                    again, _fan_out_tasks(at, limits), [worker, join, END]
                )
                builder.add_conditional_edges(
                    join, _after_tasks(at, then), list(dict.fromkeys([again, then, END]))
                )
                return node.id
            case RouterNode():
                done = router_done_node_id(node)
                builder.add_node(node.id, _router_entry(node, runtime, log, limits))
                starts = {
                    route_id: add(route, done)
                    for route_id, _, route in router_routes(node, node.id)
                }
                ends = [*starts.values(), END] + ([done] if node.otherwise == "skip" else [])
                builder.add_conditional_edges(
                    node.id, _to_route(node, starts), list(dict.fromkeys(ends))
                )
                builder.add_node(done, _router_done(node, log))
                go_on(done, node.id, then)
                return node.id
            case SubflowNode():
                if node.call is None:
                    raise CompileError(
                        f"subflow {node.id!r}: workflow {node.workflow.id!r} version "
                        f"{node.workflow.version} was not resolved for this run"
                    )
                done = subflow_done_node_id(node)
                builder.add_node(node.id, _subflow_entry(node, log, limits))
                start = add(node.call, done)
                builder.add_conditional_edges(
                    node.id, _continue_unless_failed(node.id, start), [start, END]
                )
                builder.add_node(done, _subflow_done(node, log))
                go_on(done, node.id, then)
                return node.id
            case ToolNode() if creates_repo(node):
                ready = repo_ready_node_id(node)
                builder.add_node(node.id, _step(node, runtime, tools, log, limits))  # no sandbox
                go_on(node.id, node.id, ready)
                builder.add_node(ready, _repo_ready)
                builder.add_edge(ready, then)
                return node.id
            case GateNode() if (
                node.evidence is not None or node.review is not None or node.id in planned
            ):
                builder.add_node(
                    node.id,
                    _saving(_step(node, runtime, tools, log, limits), log, limits, top[node.id]),
                )
                go_on(node.id, node.id, then)
                first = node.id
                if node.id in planned:
                    planning = plan_node_id(node)
                    guarded = [writes[w] for w in planned[node.id]]
                    builder.add_node(planning, _plan_writes(node, guarded, tools, log, limits))
                    builder.add_edge(planning, first)
                    first = planning
                if node.review is not None:
                    reading = review_node_id(node)
                    builder.add_node(reading, _review(node, tools, log, limits))
                    builder.add_edge(reading, first)
                    first = reading
                if node.evidence is not None:
                    checks = evidence_node_id(node)
                    builder.add_node(checks, _evidence(node, tools, log, limits))
                    builder.add_edge(checks, first)
                    first = checks
                return first
            case AgentNode() | ToolNode() | GateNode():
                builder.add_node(
                    node.id,
                    _saving(_step(node, runtime, tools, log, limits), log, limits, top[node.id]),
                )
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


def _saving[T](
    work: Callable[[T], Awaitable[RunUpdate]], log: RunEventLog, limits: _Limits, step: str
) -> Callable[[T], Awaitable[RunUpdate]]:
    """`work`, a step that may commit, then the run's branches saved through `limits.saver`
    before its update is returned, and so before it is checkpointed (12.2): a crash cannot fall
    between the step completing and its commits being saved. A step that raises (a gate pausing,
    a cancel) saves nothing. The versions record `step`, the top-level step `work` runs in
    (12.4). Without a saver, `work` as it is."""
    saver = limits.saver
    if saver is None:
        return work

    @functools.wraps(work)
    async def saving(state: T) -> RunUpdate:
        update = await work(state)
        await _save_branches(saver, log, step)
        return update

    return saving


async def _save_branches(saver: BranchSaver, log: RunEventLog, step: str) -> None:
    """Save the run's moved branches and log `branch_saved` or `branch_save_failed` for each.
    A saver that breaks is logged and the step goes on: its commits stay in the sandbox."""
    try:
        saves = await saver.save(step=step)
    except Exception:
        _logger.exception("run %s: could not save its branches", log.run_id)
        return
    for saved in saves.saved:
        await log.emit(
            BRANCH_SAVED, node_id=owner_node(saved.key), payload=saved.model_dump(mode="json")
        )
    for failed in saves.failed:
        await log.emit(
            BRANCH_SAVE_FAILED,
            node_id=owner_node(failed.key),
            payload=failed.model_dump(mode="json"),
        )


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
            reads = _reads_as(node, _integrated_reader(state))
            return _run_step(
                node,
                runtime,
                tools,
                log,
                limits,
                state["last_text"],
                refs,
                route_as=reads,
                results=state["results"],
                writers=writers_before(state, limits.writer_ids, limits.team_ids),
                evidence=_evidence_input(node, state),
                gate_review=_review_input(node, state),
                packs=state.get("evidence", {}),
            )

        if isinstance(node, AgentNode):
            frozen: dict[str, dict[str, JsonValue]] = {}
            if node.start_from is not None:
                started = await _start_from(node, state, limits)
                if isinstance(started, str):
                    return await _failed_start(node.id, started, state, log)
                frozen = started
            update = await _spawn(node.id, state, limits, log, run)
            if frozen:
                update["frozen"] = frozen
            return update
        result = await run()
        update = _update(node.id, result)
        sent_back = (result.data or {}).get("source") in ("checks", "review")
        if isinstance(node, GateNode) and sent_back:
            key = evidence_node_id(node)
            update["rounds"] = {key: state.get("rounds", {}).get(key, 0) + 1}
        if isinstance(node, GateNode) and node.review is not None and node.review.notes:
            await _write_notes(node, result, state, limits, log, update)
        return update

    return step


async def _start_from(
    node: AgentNode | OrchestratorNode, state: RunState, limits: _Limits
) -> dict[str, dict[str, JsonValue]] | str:
    """Start the branch of `node` from the work of its `start_from` writer (13.5), before its
    first turn, and hold it to that work's files as frozen: it can read them, never change them.
    The branch is made once (a resumed run keeps its commits), the frozen files are those the
    state kept the first time, so a restart, a restore and a rerun from a step give the same
    answer. Returns the `frozen` entry for the state, or why it cannot start; nothing without
    an integrator (a run with no repo)."""
    source = node.start_from
    integrator = limits.integrator
    if source is None or integrator is None:
        return {}
    try:
        started = await integrator.start_writer(
            node.id, source, orchestrator=isinstance(node, OrchestratorNode)
        )
    except IntegrationError as e:
        return f"cannot start from the work of {source!r}: {e}"
    entry: dict[str, JsonValue] = state.get("frozen", {}).get(node.id) or {
        "writer": source,
        "gate": limits.start_gates.get(node.id),
        "start": started.start,
        "files": list[JsonValue](started.files),
    }
    if limits.protected is not None:
        limits.protected.freeze(node.id, frozen_rules(entry))
    return {node.id: entry}


async def _failed_start(node_id: str, error: str, state: RunState, log: RunEventLog) -> RunUpdate:
    """The node cannot start from its `start_from` writer: it starts and fails, with no agent."""
    await log.emit(NODE_STARTED, node_id=node_id)
    await log.emit(NODE_FAILED, node_id=node_id, payload={"error": error})
    failed = AgentNodeResult(status="failed", text=state["last_text"], usage=None, error=error)
    return _update(node_id, failed)


def _start_gates(root: Node) -> dict[str, str]:
    """Each node with a `start_from` → the first gate after that writer (13.5), where a person
    approved the work it starts from."""
    ordered = list(iter_nodes(root))
    ids = [n.id for _, n in ordered]
    found: dict[str, str] = {}
    for index, (_, node) in enumerate(ordered):
        if not isinstance(node, AgentNode | OrchestratorNode) or node.start_from is None:
            continue
        if node.start_from not in ids:
            continue
        for _, later in ordered[ids.index(node.start_from) + 1 : index]:
            if isinstance(later, GateNode):
                found[node.id] = later.id
                break
    return found


def _refusal_event(log: RunEventLog) -> Callable[[str, str, str, ProtectRule], Awaitable[None]]:
    """What the repo tools call back for each refused change (13.5): one `protected_path_refused`
    event with the path and the rule, never the file's content."""

    async def refused(key: str, tool: str, path: str, rule: ProtectRule) -> None:
        owner = owner_node(key)
        why: dict[str, JsonValue] = {"kind": rule.kind}
        if rule.kind == "frozen":
            why |= {"writer": rule.writer, "gate": rule.gate}
        else:
            why["pattern"] = rule.glob
        payload: dict[str, JsonValue] = {"tool": tool, "path": path, "rule": why}
        if owner != key:
            payload["task"] = key
        await log.emit(PROTECTED_PATH_REFUSED, node_id=owner, payload=payload)

    return refused


def _evidence(
    gate: GateNode, tools: ToolExecutor | None, log: RunEventLog, limits: _Limits
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Checks the writer's work before `gate` (13.3): `build.test` and `scan.lint` on its branch,
    run by the engine through the run's tools, never by an agent. A step of its own, so a
    restart between it and the gate runs nothing twice (a gate runs again from its start when it
    continues). It stores the pack and, when a required check failed with a round left, the
    comments that send the work back, in the state the gate reads."""
    spec = gate.evidence
    assert spec is not None
    key = evidence_node_id(gate)

    async def check(state: RunState) -> RunUpdate:
        used = state.get("rounds", {}).get(key, 0)
        loop_id, passes = limits.evidence_loops.get(gate.id, ("", 0))
        passes_left = passes - state["iterations"].get(loop_id, passes)
        limits.announce(writers_before(state, limits.writer_ids, limits.team_ids))
        refs = state.get("artifacts", {})

        async def read(name: str) -> str | None:
            """The latest version of a run artifact the criteria check reads (13.4)."""
            ref = refs.get(name)
            stored = await limits.artifacts.get(name, ref.version) if ref is not None else None
            return stored.content if stored is not None else None

        pack = await collect(
            gate.id,
            spec,
            tools,
            base_cache=limits.base_lint,
            rounds_left=max(min(spec.max_rounds - used, passes_left), 0),
            node_id=key,
            read_artifact=read,
        )
        comments = send_back_comments(pack) if pack.sends_back() else []
        payload = pack_payload(pack)
        await log.emit(
            EVIDENCE_COLLECTED,
            node_id=gate.id,
            payload={**payload, "sent_back": bool(comments)},
        )
        asked: list[JsonValue] = [c.model_dump(mode="json") for c in comments]
        proceed = spec.pause == "on_failure" and not comments and pack.clean()
        update: RunUpdate = {
            "evidence": {key: {"pack": payload, "comments": asked, "proceed": proceed}}
        }
        name = f"{gate.id[:40]}.evidence.json"
        stored = AgentNodeResult(
            status="completed", text=json.dumps(payload), usage=None, data=payload
        )
        written = await _write(gate.id, name, None, stored, limits, log)
        if written.artifact is not None:
            update["artifacts"] = {name: written.artifact}
        return update

    return check


def _review(
    gate: GateNode, tools: ToolExecutor | None, log: RunEventLog, limits: _Limits
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Reads the review's findings before `gate` (13.6): the latest version of `review.from`, each
    finding mapped to the writer whose diff holds its file, and the comments that send the work
    back when a finding is at or above `block_at` and a round is left. A step of its own, so a
    restart between it and the gate decides the same. It stores what it found in the state the
    gate reads (under `<gate>.review`). Rounds are counted with the gate's checks: one counter
    under `evidence_node_id`, never using the loop's last pass (lessons 13). A lens that could not
    run, or a report that cannot be read, never sends the work back: it is not the writer's fault,
    so a person decides."""
    spec = gate.review
    assert spec is not None
    key = review_node_id(gate)

    async def read(state: RunState) -> RunUpdate:
        used = state.get("rounds", {}).get(evidence_node_id(gate), 0)
        loop_id, passes = limits.evidence_loops.get(gate.id, ("", 0))
        passes_left = passes - state["iterations"].get(loop_id, passes)
        rounds_left = max(min(spec.max_rounds - used, passes_left), 0)
        refs = state.get("artifacts", {})
        ref = refs.get(spec.from_)
        stored = await limits.artifacts.get(ref.name, ref.version) if ref is not None else None
        problem: str | None = None
        report: FindingsReport | None = None
        if stored is None:
            problem = f"the review wrote no {spec.from_!r}"
        else:
            try:
                report = FindingsReport.model_validate_json(stored.content)
            except ValueError:
                problem = f"{spec.from_!r} is not a findings report"
        writers = writers_before(state, limits.writer_ids, limits.team_ids)
        diffs: dict[str, str] = {}
        if tools is not None and report is not None:
            limits.announce(writers)
            for w in writers:
                shown = await tools.call("repo.diff", {"node": w.node_id})
                if not shown.is_error:
                    diffs[w.node_id] = shown.text
        if report is None or ref is None:
            report = FindingsReport(
                scanner="merged",
                checks=[
                    Check(
                        path=".",
                        kind="branch",
                        tool="review",
                        status="failed",
                        reason=clip_message(problem or "no review"),
                    )
                ],
                findings=[],
                counts={},
                truncated=False,
            )
        version = ref.version if ref is not None else 0
        shown_review = shown_of(spec.from_, version, report, spec.block_at, rounds_left, diffs)
        sends = bool(shown_review.failed_lenses) is False and rounds_left > 0
        comments = review_send_back(shown_review) if sends else []
        await log.emit(
            REVIEW_COLLECTED,
            node_id=gate.id,
            payload={
                "from": spec.from_,
                "version": version,
                "counts": dict(shown_review.counts),
                "blocking": sum(1 for c in shown_review.comments if c.blocking),
                "failed_lenses": list[JsonValue](shown_review.failed_lenses),
                "rounds_left": rounds_left,
                "sent_back": bool(comments),
            },
        )
        found = ReviewInput(shown=shown_review, send=comments)
        return {"evidence": {key: found.model_dump(mode="json", by_alias=True)}}

    return read


def _plan_writes(
    gate: GateNode,
    guarded: list[ToolNode],
    tools: ToolExecutor | None,
    log: RunEventLog,
    limits: _Limits,
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Asks the outward writes `gate` guards for their plans (13.8) before it pauses: each tool's
    plan mode, called by the engine through the run's tools (never by an agent), with the
    arguments the write's own step will resolve. A step of its own, after the checks and the
    review, so a restart between it and the gate plans nothing twice, and a pass the checks or the
    review sent back plans nothing. The plans are kept in the state (`write_plans`), and the
    runner shows them with the gate (`gate_waiting`)."""

    async def plan(state: RunState) -> RunUpdate:
        found = _evidence_input(gate, state)
        reviewed = _review_input(gate, state)
        if tools is None or (found is not None and found.comments):
            return {}
        if reviewed is not None and reviewed.send:
            return {}
        if found is not None and found.proceed and reviewed is None:
            return {}  # the gate passes by itself: nobody decides here
        made: list[WritePlan] = []
        for write in guarded:
            made.append(await _plan_write(write, state, tools, limits))
        shown: list[JsonValue] = [p.model_dump(mode="json") for p in made]
        await log.emit(WRITES_PLANNED, node_id=gate.id, payload={"gate": gate.id, "plans": shown})
        return {
            "write_plans": {
                p.node_id or "": {"gate": gate.id, "plan": p.model_dump(mode="json")} for p in made
            }
        }

    return plan


async def _plan_write(
    write: ToolNode,
    state: RunState,
    tools: ToolExecutor,
    limits: _Limits,
    expect: Mapping[str, JsonValue] | None = None,
) -> WritePlan:
    """The plan of `write` as its tool answers it now, the arguments resolved the way the write's
    own step will resolve them. What the platform adds after the approval (the review's notes, a
    comment's links) is left out and named in `pending`."""
    without_notes = write.model_copy(
        update={"args": {k: v for k, v in write.args.items() if k != "notes_from"}}
    )
    try:
        called = await _with_body_from(without_notes, limits.artifacts, state.get("artifacts", {}))
        called = _with_links(called, state["results"])
        called = _with_issue_from(called, limits.request)
    except (ArtifactError, ToolArgsError) as e:
        return failing_plan(write, write.args, f"unresolved: {e}")
    return await plan_call(write, called, tools, expect)


def _review_input(node: StepNode, state: RunState) -> ReviewInput | None:
    """What the review before the gate `node` found (13.6), as the checkpoint holds it."""
    if not isinstance(node, GateNode) or node.review is None:
        return None
    found = state.get("evidence", {}).get(review_node_id(node))
    return ReviewInput.model_validate(found) if found is not None else None


async def _write_notes(
    gate: GateNode,
    result: AgentNodeResult,
    state: RunState,
    limits: _Limits,
    log: RunEventLog,
    update: RunUpdate,
) -> None:
    """With `review.notes`, an approval writes the comments that were not dismissed as Markdown, a
    new version of the artifact, for `github.openPR`'s `notes_from` (13.6)."""
    spec = gate.review
    found = _review_input(gate, state)
    if spec is None or spec.notes is None or found is None:
        return
    if result.status != "completed" or (result.data or {}).get("decision") != "approve":
        return
    dismissed = set(cast(list[str], (result.data or {}).get("dismissed") or []))
    left = [c for c in found.shown.comments if c.fingerprint not in dismissed]
    text = notes_text(left, len(found.shown.comments) - len(left))
    stored = AgentNodeResult(status="completed", text=text, usage=None)
    written = await _write(gate.id, spec.notes, None, stored, limits, log)
    if written.artifact is not None:
        update["artifacts"] = {**update.get("artifacts", {}), spec.notes: written.artifact}


def _evidence_input(node: StepNode, state: RunState) -> EvidenceInput | None:
    """What the checks before the gate `node` found (13.3), as the checkpoint holds it."""
    if not isinstance(node, GateNode) or node.evidence is None:
        return None
    found = state.get("evidence", {}).get(evidence_node_id(node))
    return EvidenceInput.model_validate(found) if found is not None else None


def _integrated_reader(state: RunState) -> str | None:
    """The orchestrator whose integration branch the run's readers read (6.9): the latest one,
    in run order, that merged a task; `None` before any did, when they read the run's checkout."""
    integrated = state.get("integrated", {})
    return next(
        (o for o in reversed(state["order"]) if (integrated.get(o) or {}).get("merged")), None
    )


def writers_before(
    state: RunState, writer_ids: Collection[str], team_ids: Collection[str] = ()
) -> list[ReadableWriter]:
    """The writers whose work the next step may read (13.1), in run order: the writer nodes that
    completed, and the orchestrators whose integration branch merged a task. Worked out from the
    checkpointed state (`order`, `results`, `integrated`): a resumed run gets the same answer."""
    integrated = state.get("integrated", {})
    found: list[ReadableWriter] = []
    for node_id in dict.fromkeys(state["order"]):
        result = state["results"].get(node_id)
        if node_id in writer_ids and result is not None and result.status == "completed":
            found.append(ReadableWriter(node_id, "writer"))
        elif node_id in team_ids and (integrated.get(node_id) or {}).get("merged"):
            found.append(ReadableWriter(node_id, "integration"))
    return found


def _encode_writers(writers: Sequence[ReadableWriter]) -> list[dict[str, str]]:
    """Writers as a `Send` payload keeps them (the checkpoint stores JSON)."""
    return [{"node_id": w.node_id, "kind": w.kind} for w in writers]


def _decode_writers(raw: Sequence[Mapping[str, str]] | None) -> tuple[ReadableWriter, ...]:
    return tuple(
        ReadableWriter(w["node_id"], "integration" if w["kind"] == "integration" else "writer")
        for w in raw or ()
    )


def _writers_payload(writers: Sequence[ReadableWriter]) -> list[JsonValue]:
    """The `writers` a `node_started` carries."""
    return [{"node_id": w.node_id, "kind": w.kind} for w in writers]


def _reads_as(node: Node, reads: str | None) -> str | None:
    """What a node that only reads the repo calls its tools as: the orchestrator `reads`, so its
    `repo.*` reads go to that orchestrator's integration branch, the work merged so far (6.9); a
    node that writes, publishes or reads nothing calls as itself (`None`)."""
    tools = set(node_tools(node))
    if isinstance(node, AgentNode) and node.review is not None:
        return None  # a review agent reads the reviewed writer's refs, as itself (13.6)
    if reads is None or not tools & READ_TOOLS or tools & (WRITE_TOOLS | PUBLISH_TOOLS):
        return None
    return reads


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


@dataclass(frozen=True)
class _NoChange:
    """The reviewed writer finished without work (a lead that planned no task, a writer that
    committed nothing): there is nothing to review, which is not a failure."""

    writer: str


def _nothing_to_review(writer: str) -> AgentNodeResult:
    """A review agent's answer when `writer` made no change: an empty findings report whose one
    check says it was skipped and why, so the merged report and the gate say so."""
    report = FindingsReport(
        scanner="agent",
        checks=[
            Check(
                path=".",
                kind="review",
                tool="agent",
                status="skipped",
                reason=f"nothing to review: {writer!r} made no change",
            )
        ],
        findings=[],
        counts={s: 0 for s in SEVERITIES},
        truncated=False,
    )
    data: dict[str, JsonValue] = report.model_dump(mode="json")
    return AgentNodeResult(
        status="completed", text=json.dumps(data, indent=2), usage=None, data=data
    )


async def _review_setup(
    node: AgentNode,
    writers: Sequence[ReadableWriter],
    refs: Mapping[str, ArtifactRef],
    packs: Mapping[str, JsonValue],
    limits: "_Limits",
    tools: ToolExecutor | None,
) -> tuple[str, str, dict[str, JsonValue]] | str | _NoChange:
    """What a review agent (13.6) is given, built from the run and never from the previous step's
    output: the writer it reviews (`of`, else the latest writer that completed), its input (the
    spec, the writer's change and its evidence pack) and the `review` of its `node_started`. The
    writer's work is read from git refs: the repo tools default the agent's reads to it. An error
    text when there is no writer to review."""
    assert node.review is not None
    of = node.review.of or (writers[-1].node_id if writers else None)
    if of is None:
        return "no writer ran before"
    if of not in {w.node_id for w in writers}:
        return _NoChange(of)
    spec_text: str | None = None
    spec_version: int | None = None
    if (name := node.review.spec_from) is not None and name in refs:
        try:
            spec_text = await reader_input(limits.artifacts, [name], refs)
            spec_version = refs[name].version
        except ArtifactError:
            spec_text = None
    change: str | None = None
    if tools is not None:
        limits.announce(writers)
        shown = await tools.call("repo.diff", {"node": of})
        change = None if shown.is_error else shown.text
    mine: list[dict[str, JsonValue]] = []
    for value in packs.values():
        pack = value.get("pack") if isinstance(value, dict) else None
        if isinstance(pack, dict) and pack.get("node") == of:
            mine.append(pack)
    evidence = evidence_summary(mine)
    if limits.readable is not None:
        limits.readable.set_review(node.id, of)
    started: dict[str, JsonValue] = {
        "of": of,
        "spec": node.review.spec_from,
        "spec_version": spec_version,
        "diff": diff_stats(change or ""),
        "evidence": evidence != NONE,
    }
    text = review_input(spec=spec_text, change=change, evidence=evidence, writer=of)
    return of, text, started


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
    results: Mapping[str, AgentNodeResult] | None = None,
    writers: Sequence[ReadableWriter] = (),
    evidence: EvidenceInput | None = None,
    packs: Mapping[str, JsonValue] | None = None,
    gate_review: ReviewInput | None = None,
) -> AgentNodeResult:
    """Run one agent, tool or gate node on `input`, writing its events (tagged with `item` inside
    a map or an orchestrator's task, `branch` inside a parallel). `writers` ran before it: an
    agent with repo read tools is told about them and may read their work (13.1).
    `route_as` is what the node is known by to the tools and the runtime: a task's writer key
    inside an orchestrator. A node that
    reads run artifacts runs on the versions in `refs` instead, and one that writes one stores its
    output once it completes. An agent waits for one of the run's `agents_alive` slots before it
    starts, and its usage is counted on the run's budget: once that is spent, the node ends
    `node_cancelled` and `PolicyLimitExceeded` is raised. A review agent (13.6) is not given
    `input`: the engine builds its own from the spec, the reviewed writer's change and the
    evidence in `packs`, and types its answer as findings."""
    reviewing: str | None = None
    review_started: dict[str, JsonValue] | None = None
    if isinstance(node, AgentNode) and node.review is not None:
        built = await _review_setup(node, writers, refs, packs or {}, limits, tools)
        if isinstance(built, _NoChange):
            skipped: dict[str, JsonValue] = {"review": {"of": built.writer, "no_change": True}}
            await log.emit(NODE_STARTED, node_id=node.id, payload=skipped, item=item, branch=branch)
            await log.emit(NODE_COMPLETED, node_id=node.id, item=item, branch=branch)
            return _nothing_to_review(built.writer)
        if isinstance(built, str):
            await log.emit(NODE_STARTED, node_id=node.id, item=item, branch=branch)
            failed: dict[str, JsonValue] = {"error": built}
            await log.emit(NODE_FAILED, node_id=node.id, payload=failed, item=item, branch=branch)
            return AgentNodeResult(status="failed", text=input, usage=None, error=built)
        node = node.model_copy(update={"output_schema": FINDINGS_SCHEMA})
        reviewing, input, review_started = built

    # One watch per execution of a step that runs an agent (13.7); a step that a breaker paused
    # last time is told why.
    paused = limits.take_pause(node.id) if isinstance(node, AgentNode) else None
    declared = node.paths if isinstance(node, AgentNode) else None
    if declared is not None and limits.protected is not None:
        # The repo tools refuse a write outside them too, whatever order a provider emits in.
        limits.protected.declared.set(route_as or node.id, declared)
    watch = (
        None
        if isinstance(node, ToolNode | GateNode | WaitForNode)
        else _watch(node.id, limits, declared)
    )

    async def write(event: AgentEvent) -> None:
        await log.agent_event(node.id, event, item, branch)
        if isinstance(event, Usage) and limits.budget is not None:
            limits.budget.add(event, node.id)
        if watch is not None:
            watch.see(event)

    # Streamed text is merged so the log gets at most one `text_delta` per 250 ms.
    buffer = DeltaBuffer(write)
    on_event = buffer.emit

    async def run() -> AgentNodeResult:
        match node:
            case ToolNode() if node.tool in COMMIT_TOOLS:
                return await run_commit_node(
                    node,
                    limits.review,
                    limits.artifacts,
                    refs,
                    limits.issue,
                    limits.request,
                    on_event,
                    limits.spec,
                )
            case ToolNode():
                try:
                    called = await _with_body_from(node, limits.artifacts, refs)
                    called = _with_links(called, results or {})
                    called = _with_issue_from(called, limits.request)
                except (ArtifactError, ToolArgsError) as e:
                    return AgentNodeResult(status="failed", text=input, usage=None, error=str(e))
                return await run_tool_node(called, tools, on_event, route_as)
            case WaitForNode():
                asked = (results or {}).get(node.after_from) or None
                comment = (asked.data or {}).get("comment_id") if asked else None
                brief = limits.issue
                return await run_wait_node(
                    node,
                    input,
                    log,
                    brief.key if brief else None,
                    brief.url if brief else "",
                    str(comment) if comment else None,
                )
            case GateNode():
                return await run_gate_node(
                    node,
                    input,
                    log,
                    limits.review,
                    limits.policy.approval_ttl_s,
                    limits.artifacts,
                    refs,
                    evidence,
                    gate_review,
                )
            case AgentNode():
                async with limits.alive:
                    limits.announce(writers)
                    return await run_agent_node(
                        node,
                        runtime,
                        input,
                        on_event,
                        route_as,
                        limits.work_text(node, writers, route_as, reviewing, paused),
                        limits.resolved(node.id),
                    )

    reads = [] if isinstance(node, GateNode) else node.reads
    # A gate runs again from its start when the run continues; the runner logs its start.
    if not isinstance(node, GateNode):
        started: dict[str, JsonValue] | None = None
        if reads:
            read: list[JsonValue] = [
                {"name": name, "version": refs[name].version} for name in reads if name in refs
            ]
            started = {"reads": read}
        if isinstance(node, AgentNode) and (provider := limits.provider_payload(node.id)):
            started = {**(started or {}), **provider}
        if isinstance(node, AgentNode) and READ_TOOLS.intersection(node.tools):
            started = {**(started or {}), "writers": _writers_payload(writers)}
        if (
            isinstance(node, AgentNode)
            and limits.protected is not None
            and WRITE_TOOLS.intersection(node.tools)
        ):
            key = route_as or node.id
            started = {
                **(started or {}),
                "protected": protected_payload(
                    limits.protected.rules_for(key), limits.allow.get(key.partition(".")[0], ())
                ),
            }
        if review_started is not None:
            started = {**(started or {}), "review": review_started}
        if paused is not None:
            after: dict[str, JsonValue] = {
                "breaker": paused.get("breaker"),
                "reason": paused.get("reason"),
            }
            started = {**(started or {}), "resumed_after": after}
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
    except (asyncio.CancelledError, PolicyLimitExceeded, BreakerTripped):
        await log.emit(NODE_CANCELLED, node_id=node.id, item=item, branch=branch)
        raise
    port: PortFailure | None = None
    if not isinstance(node, GateNode) and node.output_schema is not None:
        result, port = _check_output(node, result)
    # A gate with `on_changes` stores only a request for changes (7.8), never its approval.
    asked = isinstance(node, GateNode) and (result.data or {}).get("decision") == "changes"
    keeps = not isinstance(node, GateNode) or node.select is not None or asked
    if node.writes and keeps and result.status == "completed" and not result.ends_run:
        schema = None if isinstance(node, GateNode) else node.output_schema
        result = await _write(node.id, node.writes, schema, result, limits, log, branch)
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


MAX_BODY_FROM_CHARS = 60_000
"""The most of a `body_from` artifact a pull request's body takes (GitHub allows 65,536)."""

MAX_JIRA_BODY_FROM_CHARS = 30_000
"""The most of a `body_from` artifact a Jira comment takes (the tool posts at most 32,000)."""

ISSUE_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]*-[1-9][0-9]{0,9}$")
"""A Jira issue key, as `issue_from: "request"` must find it in the run's request (7.2)."""


class ToolArgsError(Exception):
    """A tool node's arguments could not be resolved from the run (`issue_from`)."""


def _with_links(node: ToolNode, results: Mapping[str, AgentNodeResult]) -> ToolNode:
    """`node` with its `links_from` (7.5, a Jira comment's argument) put in place: a "Links" list
    at the end of its `body`, with the pull request the `pr` step opened and, for each file the
    `files` step committed, its diff in that pull request (`<pr>/files#diff-<sha256 of path>`,
    which still works once the branch is deleted). The links are made by the platform from the
    steps' `results`, never by a model. The tool never sees `links_from`; with no pull request,
    there is no list."""
    links = node.args.get("links_from")
    if not isinstance(links, dict):
        return node
    pr = results.get(str(links.get("pr")))
    url = (pr.data or {}).get("url") if pr is not None else None
    lines: list[str] = []
    if isinstance(url, str) and url:
        lines.append(f"- Pull request: {url}")
        done = results.get(str(links.get("files")))
        paths = (done.data or {}).get("paths") if done is not None else None
        for path in paths if isinstance(paths, list) else []:
            if isinstance(path, str):
                anchor = hashlib.sha256(path.encode()).hexdigest()
                lines.append(f"- [{path}]({url}/files#diff-{anchor})")
    args = {k: v for k, v in node.args.items() if k != "links_from"}
    if lines:
        static = args.get("body")
        head = static if isinstance(static, str) and static else ""
        listed = "**Links**\n" + "\n".join(lines)
        args["body"] = f"{head}\n\n{listed}" if head else listed
    return node.model_copy(update={"args": args})


def _with_issue_from(node: ToolNode, request: str | None) -> ToolNode:
    """`node` with its `issue_from: "request"` (7.2, a Jira write's argument) put in place as
    `issue`: the run's request, trimmed, which must be one issue key. The tool never sees
    `issue_from`. Raises `ToolArgsError` otherwise, before Jira is called."""
    if node.tool not in JIRA_WRITE_TOOLS or node.args.get("issue_from") != "request":
        return node
    key = (request or "").strip()
    if not ISSUE_KEY.match(key):
        raise ToolArgsError(
            "the run's request must be one Jira issue key, such as PROJ-12, for "
            f"{node.tool}; it is {key[:40]!r}"
        )
    args = {k: v for k, v in node.args.items() if k != "issue_from"} | {"issue": key.upper()}
    return node.model_copy(update={"args": args})


async def _with_body_from(
    node: ToolNode, artifacts: ArtifactStore, refs: Mapping[str, ArtifactRef]
) -> ToolNode:
    """`node` with its `body_from` (6.7 `github.openPR`, 7.2 `jira.comment`: an argument naming a
    run artifact) put in place: that artifact's text, as the run has it, under the static `body`,
    cut at `MAX_BODY_FROM_CHARS` (`MAX_JIRA_BODY_FROM_CHARS` for a comment). The tool never sees
    `body_from`. Raises `ArtifactError` when the run has not written the artifact."""
    name = node.args.get("body_from")
    notes_name = node.args.get("notes_from") if node.tool in PUBLISH_TOOLS else None
    if node.tool not in BODY_FROM_TOOLS or not (
        isinstance(name, str) or isinstance(notes_name, str)
    ):
        return node
    static = node.args.get("body")
    body = static if isinstance(static, str) else ""
    if isinstance(name, str):
        ref = refs.get(name)
        stored = await artifacts.get(name, ref.version) if ref is not None else None
        if stored is None:
            raise ArtifactError(f"artifact {name!r} was not written")
        cap = MAX_JIRA_BODY_FROM_CHARS if node.tool in JIRA_WRITE_TOOLS else MAX_BODY_FROM_CHARS
        text = stored.content[:cap]
        body = f"{body}\n\n{text}" if body else text
    if isinstance(notes_name, str):
        # 13.6: the approved review's comments, as model output: no mention, no HTML.
        ref = refs.get(notes_name)
        stored = await artifacts.get(notes_name, ref.version) if ref is not None else None
        if stored is None:
            raise ArtifactError(f"artifact {notes_name!r} was not written")
        notes = f"## Review notes\n\n{neutralise_notes(stored.content)}"
        body = f"{body}\n\n{notes}" if body else notes
    args = {k: v for k, v in node.args.items() if k not in ("body_from", "notes_from")}
    return node.model_copy(update={"args": args | {"body": body}})


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
        results = _results_for(loop.id, state["results"], limits)
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


def _results_for(
    node_id: str, results: Mapping[str, AgentNodeResult], limits: _Limits
) -> dict[str, JsonValue]:
    """`results` as the expressions of the node `node_id` see it: node id → `{status, text,
    data}`. Inside a called workflow (6.5), its own nodes by the ids it gives them, whatever ids
    they run under."""
    view = limits.views.get(node_id)
    if view is None:
        return _results_of(results)
    return _results_of({own: results[run] for own, run in view.items() if run in results})


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
                last=state["last_text"],
                results=_results_for(map.id, state["results"], limits),
                artifacts=artifacts,
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
    map: MapNode, over: CompiledList, evaluated: dict[str, list[JsonValue]], limits: _Limits
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
            results = _results_for(map.id, state["results"], limits)
            items = over.evaluate(last=state["last_text"], results=results)
        if not items:
            return join_node_id(map)
        refs = state.get("artifacts", {})
        return [
            Send(
                item_node_id(map),
                MapItem(
                    index=i,
                    item=item,
                    item_input=_item_input(item),
                    item_artifacts=dict(refs),
                    item_reads=_integrated_reader(state),
                    item_writers=_encode_writers(
                        writers_before(state, limits.writer_ids, limits.team_ids)
                    ),
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
            scope = _Scope(
                runtime,
                tools,
                log,
                limits,
                item=index,
                refs=refs,
                reads=task.get("item_reads"),
                writers=_decode_writers(task.get("item_writers")),
            )
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


def _fan_out_branches(
    parallel: ParallelNode, limits: _Limits
) -> Callable[[RunState], Sequence[Send] | str]:
    """One `Send` to the worker per branch, each with the parallel's input; to `END` if the
    parallel could not start."""

    def route(state: RunState) -> Sequence[Send] | str:
        # A result here is the entry's refusal (failed); a finished earlier pass's is not.
        if (
            refused := state["results"].get(parallel.id)
        ) is not None and refused.status == "failed":
            return END
        worker = branch_node_id(parallel)
        refs = state.get("artifacts", {})
        key = _outcomes_key(parallel, state, limits)
        return [
            Send(
                worker,
                ParallelBranch(
                    index=i,
                    branch_input=state["last_text"],
                    outcomes_key=key,
                    branch_evidence=dict(state.get("evidence", {})),
                    branch_artifacts=dict(refs),
                    branch_reads=_integrated_reader(state),
                    branch_writers=_encode_writers(
                        writers_before(state, limits.writer_ids, limits.team_ids)
                    ),
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
    joins: dict[str, _BranchJoin] = {}  # one per pass: a loop's later pass starts undecided

    async def work(task: ParallelBranch) -> RunUpdate:
        join = joins.setdefault(task.get("outcomes_key", parallel.id), _BranchJoin(parallel))
        index, text = task["index"], task["branch_input"]
        branch_id = parallel.branches[index].id
        marker: dict[str, JsonValue] = {"index": index, "branch_id": branch_id}
        await log.emit(PARALLEL_BRANCH_STARTED, node_id=parallel.id, payload=marker)
        refs = dict(task.get("branch_artifacts", {}))
        reads = task.get("branch_reads")
        scope = _Scope(
            runtime,
            tools,
            log,
            limits,
            branch=index,
            refs=refs,
            reads=reads,
            writers=_decode_writers(task.get("branch_writers")),
            packs=task.get("branch_evidence", {}),
        )
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
            "parallel_results": {task.get("outcomes_key", parallel.id): {branch_id: outcome}},
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


def _outcomes_key(parallel: ParallelNode, state: RunState, limits: _Limits) -> str:
    """Where `parallel`'s branches' outcomes are kept this pass: its id, or inside a loop (13.6)
    `<id>#<iteration>`."""
    loop = limits.parallel_loops.get(parallel.id)
    if loop is None:
        return parallel.id
    return f"{parallel.id}#{state['iterations'].get(loop, 0)}"


def _parallel_loops(root: Node) -> dict[str, str]:
    """Each parallel in a loop's body → the id of the innermost loop around it."""
    loops: dict[str, str] = {}
    for _, node in iter_nodes(root):
        if isinstance(node, LoopNode):
            for _, inner in iter_nodes(node.body):
                if isinstance(inner, ParallelNode):
                    loops[inner.id] = node.id
    return loops


def _parallel_join(
    parallel: ParallelNode, log: RunEventLog, limits: _Limits
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Ends the parallel by its join, from its branches' checkpointed outcomes. Its output is the
    completed branches' outputs in branch order (`data`: `outputs` by branch id, and the ids of
    the branches that `completed`, `failed` and were `cancelled`)."""

    async def join(state: RunState) -> RunUpdate:
        by_id = state.get("parallel_results", {}).get(_outcomes_key(parallel, state, limits), {})
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
    shared with the parallels inside it), the artifacts it wrote (`wrote`) and the orchestrator
    whose integration branch its readers read (`reads`, 6.9) and the writers that ran before it
    (`writers`, 13.1)."""

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
    reads: str | None = None
    writers: tuple[ReadableWriter, ...] = ()
    packs: Mapping[str, JsonValue] = field(default_factory=dict[str, JsonValue])
    """The run's evidence packs when the scope started (13.6: what a review agent is given)."""

    def route_as(self, node: Node) -> str | None:
        """What `node` is known by to the tools: inside an orchestrator's task, a writer works as
        the task (`task_writer_key`), on the task's own branch; a node that only reads, as the
        orchestrator whose integration branch the scope reads (`reads`, 6.9); else as itself."""
        if self.task is not None and WRITE_TOOLS.intersection(node_tools(node)):
            return task_writer_key(*self.task)
        if self.task is None:
            return _reads_as(node, self.reads)
        return None

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
                writers=scope.writers,
                packs=scope.packs,
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
        case SubflowNode():
            return await _subflow_inline(node, input, scope)
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
        results = _results_for(router.id, state["results"], limits)
        loop = limits.loops.get(router.id)
        iteration = state["iterations"].get(loop, 0) if loop is not None else 0
        choice = await _choose(
            router, state["last_text"], results, state.get("artifacts", {}), scope, iteration
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


SKIPPED_ROUTE = ""
"""What a router chose when no route matched and it skips (`otherwise: "skip"`, 7.5): not a
route id (a route id is a `NodeId`), so it never names one."""


def _chosen(choice: AgentNodeResult) -> str | None:
    """The route a router's choice names, `SKIPPED_ROUTE` if it skips, or `None` if it made no
    choice."""
    if choice.status != "completed":
        return None
    data = choice.data or {}
    if data.get("skipped") is True:
        return SKIPPED_ROUTE
    route = data.get("route")
    return route if isinstance(route, str) else None


def _to_route(router: RouterNode, starts: Mapping[str, str]) -> Callable[[RunState], str]:
    """To the first node of the route `router` chose; to its end if it skipped (7.5); to `END`
    if it chose none."""

    def route(state: RunState) -> str:
        chosen = state.get("routes", {}).get(router.id)
        if chosen == SKIPPED_ROUTE:
            return router_done_node_id(router)
        return starts[chosen] if chosen is not None else END

    return route


_SKIPPED_END: Final[dict[str, JsonValue]] = {"route": None, "skipped": True}
"""The `node_completed` payload of a router that skipped (7.5)."""


def _evidence_loops(root: Node) -> dict[str, tuple[str, int]]:
    """Each gate with evidence → the innermost loop around it, as its id and `max_iterations`."""
    found: dict[str, tuple[str, int]] = {}
    for _, node in iter_nodes(root):
        if isinstance(node, LoopNode):
            for _, inner in iter_nodes(node.body):
                if isinstance(inner, GateNode) and (
                    inner.evidence is not None or inner.review is not None
                ):
                    found[inner.id] = (node.id, node.max_iterations)
    return found


def _enclosing_loops(root: Node) -> dict[str, str]:
    """Each router in a loop's body → the id of the innermost loop around it."""
    loops: dict[str, str] = {}
    for _, node in iter_nodes(root):
        if isinstance(node, LoopNode):
            for _, inner in iter_nodes(node.body):
                if isinstance(inner, RouterNode):
                    loops[inner.id] = node.id
    return loops


def _router_done(
    router: RouterNode, log: RunEventLog
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Ends `router` once its route completed. Its output is the route's, and its `data` the
    route's last node's."""
    outputs = {route_id: _output_id(route) for route_id, _, route in router_routes(router, "")}

    async def done(state: RunState) -> RunUpdate:
        chosen = state.get("routes", {}).get(router.id)
        if chosen == SKIPPED_ROUTE:
            await log.emit(NODE_COMPLETED, node_id=router.id, payload=_SKIPPED_END)
            skipped = AgentNodeResult(status="completed", text=state["last_text"], usage=None)
            return _update(router.id, skipped)
        chosen = chosen or DEFAULT_ROUTE
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
    results = _results_for(router.id, scope.ran, scope.limits)
    choice = await _choose(router, input, results, scope.refs, scope)
    route_id = _chosen(choice)
    if route_id is None:
        scope.ran[router.id] = choice
        return router.id, choice
    if route_id == SKIPPED_ROUTE:
        await scope.log.emit(NODE_COMPLETED, node_id=router.id, payload=_SKIPPED_END, **scope.tag())
        skipped = AgentNodeResult(status="completed", text=input, usage=None)
        scope.ran[router.id] = skipped
        return router.id, skipped
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
    iteration: int = 0,
) -> AgentNodeResult:
    """Start `router` and choose its route: by its rules, or by asking its classifier. Logs
    `route_chosen`, and returns a completed result whose `data` is `{route, mode, reason}` and
    whose usage is the classifier's; or logs `node_failed` and returns the failure."""
    log, tag = scope.log, scope.tag()
    mode = "classifier" if router.classifier is not None else "rule"
    started = _router_started(router)
    if router.classifier is not None:
        started = {**started, **scope.limits.provider_payload(router.id)}
    await log.emit(NODE_STARTED, node_id=router.id, payload=started, **tag)
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
            route, reason = await _rule(router, input, results, refs, scope.limits, iteration)
        except ExpressionError as e:
            return await _not_routed(router, "failed", str(e), input, None, None, scope)
        if route is None and router.otherwise == "skip":
            skipped: dict[str, JsonValue] = {"route": None, "mode": mode, "reason": reason}
            await log.emit(ROUTE_CHOSEN, node_id=router.id, payload=skipped, **tag)
            data = {**skipped, "skipped": True}
            return AgentNodeResult(status="completed", text=input, usage=None, data=data)
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
    iteration: int = 0,
) -> tuple[str | None, str]:
    """The first route of `router` whose `when` holds and that condition, else its default (or
    `None` if it has none). Raises `ExpressionError` naming the route whose condition failed."""
    reads = any("artifacts" in (route.when or "") for route in router.routes)
    artifacts = await artifact_values(limits.artifacts, refs) if reads else {}
    for route in router.routes:
        when = route.when or "false"
        try:
            met = compile_condition(when, ROUTE_VARIABLES).evaluate(
                last=input, iteration=iteration, results=results, artifacts=artifacts
            )
        except ExpressionError as e:
            raise ExpressionError(when, f"when of route {route.id!r} failed: {e.message}") from e
        if met:
            return route.id, when
    if router.default is None:
        return None, "no route matched"
    return DEFAULT_ROUTE, "no route matched"


def _subflow_started(subflow: SubflowNode) -> dict[str, JsonValue]:
    """The payload of `subflow`'s `node_started`: the workflow it calls."""
    workflow: dict[str, JsonValue] = {
        "id": subflow.workflow.id,
        "version": subflow.workflow.version,
        "name": subflow.called_name or subflow.workflow.id,
    }
    return {"workflow": workflow}


async def _subflow_input(
    subflow: SubflowNode,
    last: str,
    results: dict[str, JsonValue],
    refs: Mapping[str, ArtifactRef],
    limits: _Limits,
) -> str:
    """What the workflow `subflow` calls gets: the value of its `input`, else `last`. Raises
    `ExpressionError` when `input` fails."""
    if subflow.input is None:
        return last
    reads = "artifacts" in subflow.input
    artifacts = await artifact_values(limits.artifacts, refs) if reads else {}
    return compile_value(subflow.input).evaluate(last=last, results=results, artifacts=artifacts)


def _subflow_entry(
    subflow: SubflowNode, log: RunEventLog, limits: _Limits
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Starts `subflow` and gives the workflow it calls its input; fails the subflow if its
    `input` cannot be evaluated."""

    async def enter(state: RunState) -> RunUpdate:
        await log.emit(NODE_STARTED, node_id=subflow.id, payload=_subflow_started(subflow))
        try:
            text = await _subflow_input(
                subflow,
                state["last_text"],
                _results_for(subflow.id, state["results"], limits),
                state.get("artifacts", {}),
                limits,
            )
        except ExpressionError as e:
            error = f"input failed: {e}"
            await log.emit(NODE_FAILED, node_id=subflow.id, payload={"error": error})
            failed = AgentNodeResult(
                status="failed", text=state["last_text"], usage=None, error=error
            )
            return {"results": {subflow.id: failed}, "order": [subflow.id]}
        if (port := _subflow_input_port(subflow, text, limits)) is not None:
            await log.emit(
                NODE_FAILED,
                node_id=subflow.id,
                payload={"error": port.error, "port": port.payload()},
            )
            failed = AgentNodeResult(status="failed", text=text, usage=None, error=port.error)
            return {"results": {subflow.id: failed}, "order": [subflow.id]}
        return {"last_text": text}

    return enter


def _subflow_input_port(subflow: SubflowNode, text: str, limits: _Limits) -> PortFailure | None:
    """Why what the workflow `subflow` calls is given does not match that workflow's
    `input_schema` (6.6), or `None` when it matches or the workflow is untyped."""
    schema = subflow.boundary_input_schema
    if schema is None:
        return None
    checked = check_port("input", subflow.id, schema, text, limits.sources.get(subflow.id))
    return checked if isinstance(checked, PortFailure) else None


def _subflow_output(
    subflow: SubflowNode, text: str, data: dict[str, JsonValue] | None
) -> AgentNodeResult | PortFailure:
    """The completed result of `subflow` from the called workflow's output: checked against that
    workflow's `output_schema` (6.6) when it has one (its last node's `data` when there is some,
    else the text), the matching object as its `data` and its pretty JSON as its text."""
    schema = subflow.output_schema
    if schema is None:
        return AgentNodeResult(status="completed", text=text, usage=None, data=data)
    checked = check_port("output", subflow.id, schema, data if data is not None else text)
    if isinstance(checked, PortFailure):
        return checked
    pretty = json.dumps(checked, indent=2, ensure_ascii=False)
    return AgentNodeResult(status="completed", text=pretty, usage=None, data=checked)


def _subflow_done(
    subflow: SubflowNode, log: RunEventLog
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Ends `subflow` once the workflow it calls completed. Its output is that workflow's, and
    its `data` the workflow's last node's."""
    assert subflow.call is not None
    output = _output_id(subflow.call)

    async def done(state: RunState) -> RunUpdate:
        source = state["results"].get(output)
        data = source.data if source is not None else None
        result = _subflow_output(subflow, state["last_text"], data)
        if isinstance(result, PortFailure):
            payload: dict[str, JsonValue] = {"error": result.error, "port": result.payload()}
            await log.emit(NODE_FAILED, node_id=subflow.id, payload=payload)
            failed = AgentNodeResult(
                status="failed", text=state["last_text"], usage=None, error=result.error
            )
            return {"results": {subflow.id: failed}, "order": [subflow.id]}
        await log.emit(NODE_COMPLETED, node_id=subflow.id)
        return _update(subflow.id, result)

    return done


async def _subflow_inline(
    subflow: SubflowNode, input: str, scope: _Scope
) -> tuple[str, AgentNodeResult]:
    """Run `subflow` inside a map item or a branch: the workflow it calls runs in `scope`. Its
    agents were counted with the rest of the item or branch."""
    assert subflow.call is not None
    log, tag = scope.log, scope.tag()
    await log.emit(NODE_STARTED, node_id=subflow.id, payload=_subflow_started(subflow), **tag)
    try:
        input = await _subflow_input(
            subflow,
            input,
            _results_for(subflow.id, scope.ran, scope.limits),
            scope.refs,
            scope.limits,
        )
    except ExpressionError as e:
        error = f"input failed: {e}"
        await log.emit(NODE_FAILED, node_id=subflow.id, payload={"error": error}, **tag)
        failed = AgentNodeResult(status="failed", text=input, usage=None, error=error)
        scope.ran[subflow.id] = failed
        return subflow.id, failed
    if (port := _subflow_input_port(subflow, input, scope.limits)) is not None:
        refused: dict[str, JsonValue] = {"error": port.error, "port": port.payload()}
        await log.emit(NODE_FAILED, node_id=subflow.id, payload=refused, **tag)
        failed = AgentNodeResult(status="failed", text=input, usage=None, error=port.error)
        scope.ran[subflow.id] = failed
        return subflow.id, failed
    ended, result = await _run_inline(subflow.call, input, scope)
    end: dict[str, JsonValue] = {}
    if (error := _stop_error(ended, result)) is not None:
        end["error"] = error
    if result.status != "completed":
        await log.emit(NODE_END[result.status], node_id=subflow.id, payload=end, **tag)
        scope.ran[subflow.id] = result.model_copy(update={"usage": None, "error": error})
        return ended, result
    done = _subflow_output(subflow, result.text, result.data)
    if isinstance(done, PortFailure):
        wrong: dict[str, JsonValue] = {"error": done.error, "port": done.payload()}
        await log.emit(NODE_FAILED, node_id=subflow.id, payload=wrong, **tag)
        failed = AgentNodeResult(status="failed", text=result.text, usage=None, error=done.error)
        scope.ran[subflow.id] = failed
        return subflow.id, failed
    await log.emit(NODE_COMPLETED, node_id=subflow.id, payload=end, **tag)
    scope.ran[subflow.id] = done
    return subflow.id, done


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

    watch = _watch(router.id, limits)

    async def write(event: AgentEvent) -> None:
        await log.agent_event(router.id, event, scope.item, scope.branch)
        if isinstance(event, Usage) and limits.budget is not None:
            limits.budget.add(event, router.id)
        watch.see(event)

    buffer = DeltaBuffer(write)
    try:
        try:
            async with limits.alive:
                result = await run_agent_node(
                    agent,
                    scope.runtime,
                    input,
                    buffer.emit,
                    context=_with_pause(limits.context, limits.take_pause(router.id)),
                    resolved=limits.resolved(router.id),
                )
        finally:
            await buffer.close()
    except (asyncio.CancelledError, PolicyLimitExceeded, BreakerTripped):
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


def hub_iteration_instructions(orchestrator: OrchestratorNode) -> str:
    """What `orchestrator`'s hub is asked in a later iteration of the loop it is in (6.9): its
    own instructions, then how to plan again from what the last iteration ended with (a review,
    say). That and the earlier tasks are in its input, as data, never here."""
    return (
        f"{orchestrator.hub.instructions}\n\nThis work was done before and looked at again. Your "
        "input is what the last pass ended with (`input`, e.g. a review of the work), which pass "
        "this is (`iteration`) and every task planned in earlier passes (`previous`) with its "
        "`iteration`, `status` (`completed`, `failed` or `dropped`) and its `output` or `error`. "
        "The completed tasks' changes are already in the code your workers start from. Plan only "
        f"the work still to do, at most {orchestrator.max_workers} tasks: never redo what is "
        "done. Give each task a new `id` (a short slug: lower case letters, digits, `_` and `-`, "
        "used by no earlier task), a `title` (one line) and `instructions` (what its worker must "
        "do, on its own: a worker sees only its task and the input). Say what this pass changes "
        "and why, in one sentence, as `reason`. Plan no task if nothing is left to do."
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
    plan's (a replan's, a later iteration's). It waits for an `agents_alive` slot, and its usage
    counts on the run's budget."""
    hub = orchestrator.hub
    agent = AgentNode(
        type="agent",
        id=orchestrator.id,
        role=hub.role,
        instructions=instructions or hub_instructions(orchestrator),
        provider=hub.provider,
        model=hub.model,
        tools=list(hub.tools),
        output_schema=orchestrator_plan_schema(orchestrator, max_tasks),
    )
    log, limits = scope.log, scope.limits

    watch = _watch(orchestrator.id, limits)

    async def write(event: AgentEvent) -> None:
        await log.agent_event(orchestrator.id, event)
        if isinstance(event, Usage) and limits.budget is not None:
            limits.budget.add(event, orchestrator.id)
        watch.see(event)

    buffer = DeltaBuffer(write)
    try:
        try:
            async with limits.alive:
                limits.announce(scope.writers)
                result = await run_agent_node(
                    agent,
                    scope.runtime,
                    input,
                    buffer.emit,
                    context=limits.work_text(
                        agent,
                        scope.writers,
                        orchestrator.id,
                        paused=limits.take_pause(orchestrator.id),
                    ),
                    resolved=limits.resolved(orchestrator.id),
                )
        finally:
            await buffer.close()
    except (asyncio.CancelledError, PolicyLimitExceeded, BreakerTripped):
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


def plan_key(orchestrator_id: str, iteration: int | None) -> str:
    """Where an orchestrator's plan, rounds and task results are kept in the state (`plans`,
    `rounds`, `map_results`): by its id, or by `<id>#<iteration>` in a loop's body (6.9), so each
    iteration plans afresh and a resumed run finds each iteration's plan. A `NodeId` has no `#`."""
    return orchestrator_id if iteration is None else f"{orchestrator_id}#{iteration}"


@dataclass
class _Round:
    """An orchestrator's tasks as they stand, in one iteration: every task planned (each with its
    `round`), the results of those that ended (by index), and the latest round (`number`, from
    `rounds`: a replan may plan no task)."""

    tasks: list[JsonValue]
    results: dict[int, AgentNodeResult]
    number: int

    @classmethod
    def of(cls, at: "_Orchestration", state: RunState) -> "_Round":
        return cls.keyed(state, at.key(state))

    @classmethod
    def keyed(cls, state: RunState, key: str) -> "_Round":
        tasks = state.get("plans", {}).get(key) or []
        ended = state["map_results"].get(key, {})
        made = state.get("rounds", {}).get(key, 1)
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

    def outcomes(self) -> list[JsonValue]:
        """Every task with its `round`, `status` and `output` (completed) or `error`, as a
        replanning hub sees them (data: an error may quote the repo)."""
        outcomes: list[JsonValue] = []
        for i, task in enumerate(self.tasks):
            result = self.results.get(i)
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
        return outcomes


@dataclass(frozen=True)
class _Orchestration:
    """An orchestrator, and the loop whose body it is in, if any (6.9). In a loop, its plans,
    rounds and task results are kept per iteration (`plan_key`), its result carries the
    `iteration` it ended in (so the iteration after it is not taken as ended), and its
    `plan_made`, `task_*`, `replan_started` and `branch_integrated` events say the iteration."""

    node: OrchestratorNode
    loop: LoopNode | None = None

    @property
    def id(self) -> str:
        return self.node.id

    def iteration(self, state: RunState) -> int | None:
        """The iteration of its loop it runs in; `None` outside a loop."""
        if self.loop is None:
            return None
        return state["iterations"].get(self.loop.id, 1)

    def key(self, state: RunState) -> str:
        return plan_key(self.id, self.iteration(state))

    def ended(self, state: RunState) -> bool:
        """Whether it ended (in a loop: in this iteration)."""
        result = state["results"].get(self.id)
        if result is None:
            return False
        iteration = self.iteration(state)
        return iteration is None or (result.data or {}).get("iteration") == iteration

    def tagged(self, payload: dict[str, JsonValue], state: RunState) -> dict[str, JsonValue]:
        """`payload`, with the `iteration` in a loop."""
        iteration = self.iteration(state)
        return payload if iteration is None else {**payload, "iteration": iteration}

    def result(self, result: AgentNodeResult, state: RunState) -> AgentNodeResult:
        """`result`, with the `iteration` in its `data` in a loop."""
        iteration = self.iteration(state)
        if iteration is None:
            return result
        return result.model_copy(update={"data": {**(result.data or {}), "iteration": iteration}})

    def earlier(self, state: RunState) -> list[tuple[int, _Round]]:
        """Its tasks in each earlier iteration that planned, in order (6.9); none outside a
        loop."""
        iteration = self.iteration(state) or 1
        plans = state.get("plans", {})
        return [
            (n, _Round.keyed(state, plan_key(self.id, n)))
            for n in range(1, iteration)
            if plan_key(self.id, n) in plans
        ]

    def stopped(
        self, state: RunState, result: AgentNodeResult, spawned: int, usage: list[Usage]
    ) -> RunUpdate:
        """The update of the orchestrator ending while it (re)plans or integrates."""
        return {
            "results": {self.id: self.result(result, state)},
            "order": [self.id],
            "spawned": spawned,
            "usage": usage,
        }


def _replan_due(at: _Orchestration, state: RunState) -> bool:
    """Whether the orchestrator's hub should plan again (6.2): it replans on failure, has rounds
    left, has not ended, and a task of its latest round failed."""
    replan = at.node.replan
    if replan is None or at.ended(state):
        return False
    tasks = _Round.of(at, state)
    return tasks.number - 1 < replan.max_rounds and bool(tasks.failed(tasks.number))


def _orchestrator_entry(
    at: _Orchestration, runtime: AgentRuntime, log: RunEventLog, limits: _Limits
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Starts the orchestrator: asks its hub for a plan and records it in the state (`plans`,
    each task with `round` 1), so a resumed run runs the same tasks; `_fan_out_tasks` then sends
    them. The hub counts as one agent spawned, and once the plan is made every task's agents
    count too, all at once (the tasks run in one LangGraph step, so they cannot count
    themselves): over `agents_spawned`, the orchestrator fails without running a task. A plan
    that does not match its schema, or names a task twice, fails it."""
    started: dict[str, JsonValue] = {
        "max_workers": at.node.max_workers,
        **limits.provider_payload(at.id),
    }
    scope = _Scope(runtime, None, log, limits)
    node_id = at.id

    async def enter(state: RunState) -> RunUpdate:
        if refused := await _refuse_spawn(node_id, state, 1, limits, log, started):
            return at.stopped(state, refused, 0, [])
        frozen: dict[str, dict[str, JsonValue]] = {}
        if at.node.start_from is not None:
            begun = await _start_from(at.node, state, limits)
            if isinstance(begun, str):
                return at.stopped(
                    state,
                    AgentNodeResult(
                        status="failed", text=state["last_text"], usage=None, error=begun
                    ),
                    0,
                    [],
                )
            frozen = begun
        await log.emit(NODE_STARTED, node_id=node_id, payload=started)
        update = await _make_plan(at, state, scope, round=1)
        if frozen:
            update["frozen"] = frozen
        return update

    return enter


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


def _iteration_input(at: _Orchestration, state: RunState, earlier: list[tuple[int, _Round]]) -> str:
    """A later iteration's hub input (6.9), as JSON: the loop body's input for this iteration
    (`input`: what the last one ended with), the `iteration`, and every task of the earlier
    iterations (`previous`) with its `iteration`, `round`, `status` and output or error."""
    previous: list[JsonValue] = [
        {**cast(dict[str, JsonValue], outcome), "iteration": n}
        for n, tasks in earlier
        for outcome in tasks.outcomes()
    ]
    return json.dumps(
        {"input": state["last_text"], "iteration": at.iteration(state), "previous": previous},
        ensure_ascii=False,
        indent=2,
    )


async def _make_plan(
    at: _Orchestration,
    state: RunState,
    scope: _Scope,
    round: int,
    input: str | None = None,
    earlier: Sequence[JsonValue] = (),
) -> RunUpdate:
    """One hub turn and its plan: round 1 on the orchestrator's input, or in a later iteration
    of its loop (6.9) on `_iteration_input`, at most `max_workers` tasks; a replan (6.2) on
    `input` (the tasks' outcomes) with no more tasks than `max_workers` less those completed in
    this iteration. No task may reuse the id of a task in `earlier` or of an earlier iteration's.
    The plan, appended to `earlier` with its `round`, goes in the state; a plan off its schema,
    naming a task twice or more agents than `agents_spawned` allows ends the orchestrator. The
    hub's agent already counts on `agents_spawned` (its caller checked it)."""
    orchestrator, node_id, log = at.node, at.id, scope.log
    ahead = writers_before(state, scope.limits.writer_ids, scope.limits.team_ids)
    scope = replace(scope, writers=tuple(ahead))
    per_task = agents_spawned(orchestrator.body)
    text = state["last_text"]
    before = at.earlier(state)
    if round == 1 and not before:
        answer, port = await _plan(orchestrator, text, scope)
    elif round == 1:
        answer, port = await _plan(
            orchestrator,
            _iteration_input(at, state, before),
            scope,
            instructions=hub_iteration_instructions(orchestrator),
        )
    else:
        done = len(_Round.of(at, state).completed())
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
        used.update(_task_id(t) for _, r in before for t in r.tasks)
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
        return at.stopped(state, failed, 1, usage)
    observed = state.get("spawned", 0) + 1 + per_task * len(tasks)
    if refused := await _over_spawned(node_id, observed, text, scope):
        return at.stopped(state, refused, 1, usage)
    planned: list[JsonValue] = [
        {"id": t["id"], "title": t["title"]} for t in cast(list[dict[str, JsonValue]], tasks)
    ]
    reason = (answer.data or {}).get("reason", "")
    await log.emit(
        PLAN_MADE,
        node_id=node_id,
        payload=at.tagged({"tasks": planned, "reason": reason, "round": round}, state),
    )
    numbered: list[JsonValue] = [{**_plain_task(t), "round": round} for t in tasks]
    key = at.key(state)
    return {
        "spawned": 1 + per_task * len(tasks),
        "usage": usage,
        "plans": {key: [*earlier, *numbered]},
        "rounds": {key: round},
    }


def _orchestrator_replan(
    at: _Orchestration, runtime: AgentRuntime, log: RunEventLog, limits: _Limits
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Asks the orchestrator's hub to plan again once a round settled with a failed task (6.2):
    `replan_started`, then one hub turn on `{input, round, tasks}` as JSON, every task so far
    (of this iteration, in a loop) with its round, status and output or error (data: an error
    may quote the repo). The new round's tasks are appended to the plan; `_fan_out_tasks` sends
    them. The hub counts as one more agent spawned."""
    scope = _Scope(runtime, None, log, limits)
    node_id = at.id

    async def replan(state: RunState) -> RunUpdate:
        tasks = _Round.of(at, state)
        round = tasks.number + 1
        dropped: list[JsonValue] = [
            _task_id(tasks.tasks[i])
            for i in tasks.indices(tasks.number)
            if i in tasks.results and _dropped(tasks.results[i])
        ]
        failed: list[JsonValue] = [
            {
                "id": _task_id(tasks.tasks[i]),
                "error": tasks.results[i].error or tasks.results[i].status,
            }
            for i in tasks.failed(tasks.number)
        ]
        await log.emit(
            REPLAN_STARTED,
            node_id=node_id,
            payload=at.tagged({"round": round, "failed": failed, "dropped": dropped}, state),
        )
        text = state["last_text"]
        if refused := await _over_spawned(node_id, state.get("spawned", 0) + 1, text, scope):
            return at.stopped(state, refused, 0, [])
        input = json.dumps(
            {"input": state["last_text"], "round": round, "tasks": tasks.outcomes()},
            ensure_ascii=False,
            indent=2,
        )
        return await _make_plan(at, state, scope, round=round, input=input, earlier=tasks.tasks)

    return replan


def _fan_out_tasks(
    at: _Orchestration, limits: _Limits
) -> Callable[[RunState], Sequence[Send] | str]:
    """One `Send` to the worker per planned task that has not run (the latest round's), with the
    run's artifacts; to the join if there is none; to `END` if the orchestrator failed. Each
    worker's input is `{"task", "input"}` as JSON: the task is data, and its worker's
    instructions stay the spec's. A task's index is its place in the whole plan of its
    iteration, every round's tasks after the last round's, so `item` tags and results never
    collide; in a loop, the send says where the plan is kept and the iteration (6.9)."""

    def route(state: RunState) -> Sequence[Send] | str:
        if at.ended(state):
            return END
        tasks = _Round.of(at, state)
        todo = [i for i in range(len(tasks.tasks)) if i not in tasks.results]
        if not todo:
            return tasks_join_node_id(at.node)
        refs = state.get("artifacts", {})
        iteration = at.iteration(state)
        writers = _encode_writers(writers_before(state, limits.writer_ids, limits.team_ids))
        sends: list[Send] = []
        for i in todo:
            sent = OrchestratorTask(
                index=i,
                task=tasks.tasks[i],
                task_input=json.dumps(
                    {"task": _plain_task(tasks.tasks[i]), "input": state["last_text"]},
                    ensure_ascii=False,
                    indent=2,
                ),
                task_artifacts=dict(refs),
                task_writers=writers,
            )
            if iteration is not None:
                sent["plan_key"] = at.key(state)
                sent["iteration"] = iteration
            sends.append(Send(task_node_id(at.node), sent))
        return sends

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
    at: _Orchestration,
    runtime: AgentRuntime,
    tools: ToolExecutor | None,
    log: RunEventLog,
    limits: _Limits,
) -> Callable[[OrchestratorTask], Awaitable[RunUpdate]]:
    """Runs the orchestrator's body for one task (`_run_inline`), at most `max_concurrency` at
    once; its writers work on the task's own branch (`task_writer_key`), which for a replan's
    task or in a later iteration of its loop starts from the integration branch (6.9,
    `BranchIntegrator.start_tasks`), so it builds on the work merged so far. Once a task does
    not complete, no other task of its round starts and the running ones are cancelled, or,
    while the hub may still replan (6.2), finish."""
    orchestrator = at.node
    slots = asyncio.Semaphore(orchestrator.max_concurrency)
    rounds: dict[tuple[str, int], _Workers] = {}
    replan = orchestrator.replan
    writes = body_writes(orchestrator)

    def workers_of(key: str, round: int) -> _Workers:
        if (key, round) not in rounds:
            settle = replan is not None and round - 1 < replan.max_rounds
            rounds[key, round] = _Workers(settle=settle)
        return rounds[key, round]

    async def start(sent: OrchestratorTask, scope: _Scope) -> tuple[str, AgentNodeResult]:
        """The task's body, its branch first started from the integration branch (nothing if
        that branch was not made yet: a first round, unless the run restored it, 7.6), so a
        replan's task or a later iteration's builds on the work merged so far."""
        integrator = limits.integrator
        if writes and integrator is not None:
            key = task_writer_key(orchestrator.id, _task_id(sent["task"]))
            try:
                await integrator.start_tasks(orchestrator.id, [key])
            except IntegrationError as e:
                error = f"cannot start from the integration branch: {e}"
                failed = AgentNodeResult(
                    status="failed", text=sent["task_input"], usage=None, error=error
                )
                return orchestrator.id, failed
        return await _run_inline(orchestrator.body, sent["task_input"], scope)

    async def work(sent: OrchestratorTask) -> RunUpdate:
        index, task = sent["index"], _plain_task(sent["task"])
        key = sent.get("plan_key", orchestrator.id)
        workers = workers_of(key, task_round(sent["task"]))
        task_id = str(task["id"])
        marker: dict[str, JsonValue] = {"index": index, "task_id": task_id, "title": task["title"]}
        if "iteration" in sent:
            marker["iteration"] = sent["iteration"]
        refs = dict(sent.get("task_artifacts", {}))
        scope = _Scope(
            runtime,
            tools,
            log,
            limits,
            item=index,
            refs=refs,
            task=(orchestrator.id, task_id),
            writers=_decode_writers(sent.get("task_writers")),
        )
        cancelled = AgentNodeResult(status="cancelled", text=sent["task_input"], usage=None)
        dropped = False
        async with slots:
            if workers.stopped:
                result, error = cancelled, _CANCELLED_BY_ANOTHER
                dropped = workers.settle
            else:
                await log.emit(TASK_STARTED, node_id=orchestrator.id, payload=marker)
                runner = asyncio.create_task(start(sent, scope))
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
        return {"map_results": {key: {str(index): outcome}}, "usage": usage}

    return work


def _orchestrator_integrate(
    at: _Orchestration, log: RunEventLog, limits: _Limits
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Merges the branches of the orchestrator's completed tasks, in plan order, into its
    integration branch once a round's tasks ended (6.3), before the join decides. It asks for
    every completed task each time (in a loop, every iteration's, 6.9), as the integrator merges
    none twice, so a resumed run merges what it missed and `merged` lists all the work on the
    branch. `branch_integrated` says what was merged. A task that conflicts with those merged
    before it becomes a failure (`conflicts with earlier tasks on …`), which the join and a
    replan (6.2) treat as any failed task; its own branch is left as it was. Without an
    integrator, or with no completed task in this iteration, nothing happens. An integration
    branch that cannot be built fails the orchestrator."""
    node_id = at.id

    async def integrate(state: RunState) -> RunUpdate:
        integrator = limits.integrator
        if integrator is None or at.ended(state):
            return {}
        tasks = _Round.of(at, state)
        if not tasks.completed():
            return {}
        everything = [(r, i) for _, r in at.earlier(state) for i in r.completed()]
        everything += [(tasks, i) for i in tasks.completed()]
        keys = {task_writer_key(node_id, _task_id(r.tasks[i])): (r, i) for r, i in everything}
        sources = [
            MergeRequest(key=key, message=_merge_message(r.tasks[i]))
            for key, (r, i) in keys.items()
        ]
        try:
            outcome = await integrator.integrate(node_id, sources)
        except IntegrationError as e:
            error = f"cannot build the integration branch: {e}"
            await log.emit(NODE_FAILED, node_id=node_id, payload={"error": error})
            failed = AgentNodeResult(
                status="failed", text=state["last_text"], usage=None, error=error
            )
            return at.stopped(state, failed, 0, [])

        def ids(found: Sequence[str]) -> list[JsonValue]:
            return [_task_id(keys[k][0].tasks[keys[k][1]]) for k in found]

        conflicts: list[JsonValue] = []
        failures: dict[str, AgentNodeResult] = {}
        for key, paths in outcome.conflicts.items():
            owner, index = keys[key]
            conflicts.append({"id": _task_id(owner.tasks[index]), "paths": list(paths)})
            if owner is tasks:  # an earlier iteration's task is merged already
                failures[str(index)] = tasks.results[index].model_copy(
                    update={"status": "failed", "error": conflict_error(paths)}
                )
        merged, empty = ids(outcome.merged), ids(outcome.empty)
        await log.emit(
            BRANCH_INTEGRATED,
            node_id=node_id,
            payload=at.tagged(
                {
                    "round": tasks.number,
                    "branch": outcome.branch,
                    "head": outcome.head,
                    "merged": merged,
                    "empty": empty,
                    "conflicts": conflicts,
                },
                state,
            ),
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
            update["map_results"] = {at.key(state): failures}
        return update

    return integrate


def _merge_message(task: JsonValue) -> str:
    """A task's merge commit message: `Merge task '<id>': <title>`."""
    title = cast(dict[str, JsonValue], task).get("title", "")
    return f"Merge task '{_task_id(task)}': {title}"


def _orchestrator_join(
    at: _Orchestration, log: RunEventLog, limits: _Limits
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Ends the orchestrator once a round's tasks ended, unless its hub replans (6.2: then it
    changes nothing and `<id>.replan` runs next). Its output is its completed tasks' outputs in
    plan order (`data`: `tasks`, those tasks; `outputs`; `writers`, for a gate after it to show:
    the orchestrator's id once its integration branch (6.3) merged a task, else none, or each
    completed task's writer key when there is no integrator; `branch` and `merged` once
    integrated; `plan`, every task planned with its `round` and `status`; `rounds`; in a loop,
    `iteration`, and the tasks, outputs, plan and rounds are this iteration's while the text,
    `writers` and `merged` are every iteration's, 6.9). It completes when every task of its
    latest round completed (a replan that plans nothing completes it if a task completed
    before), else it ends like the first task of that round that failed (else the first that did
    not complete), naming the task. With `writes`, the output is stored as that artifact."""
    orchestrator = at.node
    writes = body_writes(orchestrator)

    async def join(state: RunState) -> RunUpdate:
        if at.ended(state) or _replan_due(at, state):
            return {}  # it failed integrating, or its hub plans again
        tasks = _Round.of(at, state)
        rounds = tasks.number
        done = tasks.completed()
        done_tasks: list[JsonValue] = [_plain_task(tasks.tasks[i]) for i in done]
        outputs: list[JsonValue] = [tasks.results[i].text for i in done]
        integrated = state.get("integrated", {}).get(orchestrator.id)
        writers: list[JsonValue] = []
        if writes and integrated is not None:
            writers = [orchestrator.id] if integrated.get("merged") else []
        elif writes and limits.integrator is None:
            every = [(r, i) for _, r in at.earlier(state) for i in r.completed()]
            every += [(tasks, i) for i in done]
            writers = [task_writer_key(orchestrator.id, _task_id(r.tasks[i])) for r, i in every]
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
        # In a loop, the output is all the work on the branch: every iteration's (6.9).
        earlier = [r.results[i].text for _, r in at.earlier(state) for i in r.completed()]
        text = "\n\n".join(str(o) for o in [*earlier, *outputs])
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
            return _update(orchestrator.id, at.result(failed, state))
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
        return _update(orchestrator.id, at.result(result, state))

    return join


def _after_tasks(at: _Orchestration, then: str) -> Callable[[RunState], str]:
    """Where a round's join goes (6.2): to `<id>.replan` when the hub replans, else on to `then`
    if the orchestrator completed (`END` otherwise)."""
    replan = replan_node_id(at.node)

    def route(state: RunState) -> str:
        if _replan_due(at, state):
            return replan
        return then if state["results"][at.id].status == "completed" else END

    return route


def _results_of(results: Mapping[str, AgentNodeResult]) -> dict[str, JsonValue]:
    """`results` as a CEL expression sees it: node id → `{status, text, data}`."""
    return {
        node_id: {"status": r.status, "text": r.text, "data": r.data}
        for node_id, r in results.items()
    }


_PULL_REQUEST_FIELDS = ("url", "number", "head", "base", "commit", "updated")
"""What `pr_opened` says of a publish; `updated` when a follow-up pushed to an open pull request
(7.6) instead of opening one."""


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


def _continue_unless_failed(node_id: str, next_id: str) -> Callable[[RunState], str]:
    """On to `next_id` unless the node `node_id` ended without completing (to `END` then)."""

    def route(state: RunState) -> str:
        result = state["results"].get(node_id)
        return END if result is not None and result.status != "completed" else next_id

    return route


def _continue_if_completed(node_id: str, next_id: str) -> Callable[[RunState], str]:
    def route(state: RunState) -> str:
        result = state["results"][node_id]
        # A gate rejected with `on_reject: end` (6.7) completes and ends the run there.
        return next_id if result.status == "completed" and not result.ends_run else END

    return route
