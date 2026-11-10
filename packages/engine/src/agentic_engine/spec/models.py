"""Workflow spec v0: the document the canvas, Architect, monitor and engine share.

New primitives are added as members of the `Node` union; existing specs keep validating.
"""

import re
from collections.abc import Callable, Collection, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    PrivateAttr,
    field_validator,
    model_validator,
)

from agentic_engine.expr import (
    ROUTE_VARIABLES,
    ExpressionError,
    compile_condition,
    compile_item_condition,
    compile_list,
    compile_value,
)
from agentic_engine.policy import (
    BUDGET_MAX_USD,
    BUDGET_MIN_USD,
    PLATFORM_POLICY,
    Policy,
    PolicyLimit,
)
from agentic_engine.ports import schema_problem
from agentic_runtime.findings import FindingsReport

NodeId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,62}$")]
"""Slug used in branch names (`agent/<run>/<node>`), so it must be path- and ref-safe."""

NonEmptyStr = Annotated[str, Field(min_length=1)]

PortSchema = Annotated[
    dict[str, JsonValue],
    Field(
        description="A JSON Schema 2020-12 whose root is an object, with only local `$ref`s.",
        examples=[{"type": "object", "required": ["findings"], "properties": {"findings": {}}}],
    ),
]
"""A typed port (4.2): checked against the value that crosses it, at runtime."""

ArtifactName = Annotated[
    str,
    Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,58}\.(json|md|txt)$",
        description="A run artifact's name: letters, digits, `.`, `_` and `-`, ending in `.json`, "
        "`.md` or `.txt`, which give its media type.",
        examples=["findings.json"],
    ),
]
"""The name of a run artifact (4.3), shared by the nodes of one run."""

_WRITES_DESCRIPTION = (
    "Write the node's output as this run artifact (a new version each time it runs); a `.json` "
    "artifact must be JSON."
)
_READS_DESCRIPTION = (
    "Take these run artifacts as input, instead of the previous output: one artifact's content, "
    "or an object by name for several."
)


class _Base(BaseModel):
    # One JSON Schema per model: a spec is both sent (`POST /runs`) and read back
    # (`GET /runs/{id}`), and both sides name it the same.
    model_config = ConfigDict(extra="forbid", frozen=True, json_schema_mode_override="validation")


class AgentNode(_Base):
    """One agent turn: a role and instructions run on a provider."""

    type: Literal["agent"]
    id: NodeId
    role: NonEmptyStr
    instructions: NonEmptyStr
    provider: Literal["claude"] | None = Field(
        default=None, description="Unset means the workspace default."
    )
    model: NonEmptyStr | None = None
    tools: list[str] = Field(default_factory=list[str])
    input_schema: PortSchema | None = Field(
        default=None, description="Its input must be JSON that matches this, or it does not start."
    )
    output_schema: PortSchema | None = Field(
        default=None,
        description="It is asked to answer with JSON that matches this, and fails if it does not; "
        "the parsed object is its `data`.",
    )
    reads: list[ArtifactName] = Field(
        default_factory=list[str], max_length=8, description=_READS_DESCRIPTION
    )
    writes: ArtifactName | None = Field(default=None, description=_WRITES_DESCRIPTION)

    @model_validator(mode="after")
    def _unique_reads(self) -> Self:
        return _check_unique_reads(self)


class ToolNode(_Base):
    """One call of a platform tool with fixed arguments; no model is involved. Its output is the
    next node's input, and an error result fails the node."""

    type: Literal["tool"]
    id: NodeId
    tool: NonEmptyStr = Field(description="The platform tool to call, e.g. `repo.list_files`.")
    args: dict[str, JsonValue] = Field(
        default_factory=dict[str, JsonValue], description="The tool's arguments."
    )
    input_schema: PortSchema | None = Field(
        default=None, description="Its input must be JSON that matches this, or it does not run."
    )
    output_schema: PortSchema | None = Field(
        default=None,
        description="Its structured result (else its text as JSON) must match this, or it fails.",
    )
    reads: list[ArtifactName] = Field(
        default_factory=list[str], max_length=8, description=_READS_DESCRIPTION
    )
    writes: ArtifactName | None = Field(default=None, description=_WRITES_DESCRIPTION)

    @model_validator(mode="after")
    def _unique_reads(self) -> Self:
        return _check_unique_reads(self)


def _check_unique_reads[N: AgentNode | ToolNode](node: N) -> N:
    if len(set(node.reads)) != len(node.reads):
        raise ValueError(f"node {node.id!r}: `reads` names an artifact twice")
    return node


MAX_SELECT_ITEMS = 1000
"""The most items a selection gate shows (6.7): a findings report keeps at most 1,000."""


class GateSelect(_Base):
    """What a selection gate asks the approver to choose from (6.7): the items of a JSON run
    artifact. Approving names the chosen items by their key."""

    artifact: ArtifactName = Field(
        description="A `.json` run artifact written before the gate, whose items are shown."
    )
    items: NonEmptyStr = Field(
        default="findings",
        max_length=64,
        description="The top-level array field of the artifact that holds the items.",
    )
    key: NonEmptyStr = Field(
        default="fingerprint",
        max_length=64,
        description="The field of each item that names it; items without one cannot be chosen.",
    )
    preselect: NonEmptyStr | None = Field(
        default=None,
        description="A CEL condition over `item`: the items checked when the gate opens.",
    )
    min: int = Field(
        default=1, ge=0, le=MAX_SELECT_ITEMS, description="The fewest items an approval selects."
    )

    @model_validator(mode="after")
    def _json_artifact(self) -> Self:
        if not self.artifact.endswith(".json"):
            raise ValueError(f"select.artifact {self.artifact!r} must be a .json artifact")
        return self


class GateNode(_Base):
    """A human decision point: the run pauses here until someone approves or rejects. Its input
    (the previous node's output) is shown to the approver and passes through unchanged, unless
    it selects (6.7): then its output is the artifact's items the approver chose."""

    type: Literal["gate"]
    id: NodeId
    title: NonEmptyStr = Field(description="What the approver is asked to decide.")
    prompt: str | None = Field(
        default=None, description="More guidance for the approver, shown with the input."
    )
    ttl_s: int | None = Field(
        default=None,
        ge=1,
        description="Seconds the gate waits for a decision before the run is cancelled; at most "
        "the run's `approval_ttl_s`, which applies when this is unset.",
    )
    select: GateSelect | None = Field(
        default=None,
        description="Ask the approver to choose items of a JSON run artifact; the gate's output "
        "is that artifact with only the chosen items.",
    )
    on_reject: Literal["cancel", "end"] | None = Field(
        default=None,
        description="What a rejection does: cancel the run (unset), or end it here as completed, "
        "skipping the steps after the gate (a step of the root sequence only).",
    )
    writes: ArtifactName | None = Field(
        default=None,
        description="With `select`, store the chosen items as this run artifact.",
    )

    @model_validator(mode="after")
    def _writes_selection(self) -> Self:
        if self.writes is not None and self.select is None:
            raise ValueError(f"gate {self.id!r}: `writes` needs `select`")
        if self.writes is not None and not self.writes.endswith(".json"):
            raise ValueError(f"gate {self.id!r}: `writes` must be a .json artifact")
        return self


class SequenceNode(_Base):
    """Runs its steps in order."""

    type: Literal["sequence"]
    id: NodeId
    steps: list["Node"] = Field(min_length=1)


MAX_LOOP_ITERATIONS = PLATFORM_POLICY.loop_iterations
"""The platform's ceiling for loop iterations; a workspace policy may lower it (`policy_errors`)."""


class LoopNode(_Base):
    """Runs its body again and again until `until` is true, at most `max_iterations` times.

    Iteration 1 gets the loop's input; each later one gets the previous iteration's output, and
    the loop's output is its last iteration's. `until` is a CEL condition over `last` (the body's
    output), `iteration` (iterations completed, from 1) and `results` (node id → `{status, text,
    data}`, the latest result of each node run so far). Reaching `max_iterations` ends the loop
    normally. The body cannot contain gates, writers, publishers or loops: each is keyed by node
    id, which repeats in every iteration. It may hold an orchestrator (6.9), whose plans are kept
    per iteration and whose writers all land on its one integration branch."""

    type: Literal["loop"]
    id: NodeId
    body: "Node"
    until: NonEmptyStr = Field(
        description="CEL condition checked after each iteration; true stops the loop.",
        examples=['last.contains("APPROVED")'],
    )
    max_iterations: int = Field(ge=1, le=MAX_LOOP_ITERATIONS)


MAX_AGENTS_ALIVE = PLATFORM_POLICY.agents_alive
"""The platform's ceiling for agents running at once; caps `map.max_concurrency`. A workspace
policy may lower it (`policy_errors`)."""

MAX_AGENTS_SPAWNED = PLATFORM_POLICY.agents_spawned
"""The platform's ceiling for agents a run may start. A map's item count is only known at
runtime, so the engine checks it there against the run's policy."""


class MapNode(_Base):
    """Runs its body once per item of the list `over` evaluates to, at most `max_concurrency` at
    a time, and outputs the items' outputs in item order.

    `over` is a CEL expression over `last` (the map's input) and `results` (as for a loop's
    `until`), e.g. `results.list_modules.data.modules`. Each item is its body's input: a string
    as is, any other value as JSON. The body can only hold agent, tool and sequence nodes: the
    others are keyed by node id, which repeats for every item. Its items' agents count toward the
    run's `agents_spawned` limit; one item that does not complete fails the map."""

    type: Literal["map"]
    id: NodeId
    over: NonEmptyStr = Field(
        description="CEL expression that evaluates to the list of items.",
        examples=["results.list_modules.data.modules"],
    )
    body: "Node"
    max_concurrency: int = Field(ge=1, le=MAX_AGENTS_ALIVE)


class ReduceAgent(_Base):
    """The agent a `reduce` node with the `agent` strategy runs, as for an `agent` node."""

    role: NonEmptyStr
    instructions: NonEmptyStr
    provider: Literal["claude"] | None = Field(
        default=None, description="Unset means the workspace default."
    )
    model: NonEmptyStr | None = None


class ReduceNode(_Base):
    """Combines the outputs of the map or parallel `from`, which runs before it: a map's items in
    item order, a parallel's completed branches in branch order.

    `concat` joins them with `separator`. `agent` runs one agent turn whose input is the JSON
    array `[{"item": …, "output": …}]` (data, never instructions; a branch's item is its id).
    `dedupe` and `vote` (4.5) merge findings reports with no model: one finding per issue, with
    the highest severity, the sources that reported it and a confidence; `vote` keeps only the
    issues `min_votes` sources reported. Their output is a findings report."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_mode_override="validation",
        validate_by_name=True,
        serialize_by_alias=True,
    )

    type: Literal["reduce"]
    id: NodeId
    from_: NodeId = Field(
        alias="from", description="The map or parallel whose outputs are combined."
    )
    strategy: Literal["concat", "agent", "dedupe", "vote"]
    separator: str | None = Field(
        default=None, description="`concat` only: what goes between outputs (default two newlines)."
    )
    agent: ReduceAgent | None = Field(default=None, description="`agent` only, and required.")
    min_votes: int | None = Field(
        default=None,
        ge=1,
        description="`vote` only: how many sources must report an issue to keep it (default a "
        "majority of the sources that completed).",
    )
    writes: ArtifactName | None = Field(default=None, description=_WRITES_DESCRIPTION)

    @property
    def merges(self) -> bool:
        """Whether it merges findings reports (`dedupe`, `vote`)."""
        return self.strategy in ("dedupe", "vote")

    @model_validator(mode="after")
    def _strategy_fields(self) -> Self:
        if self.strategy == "agent" and self.agent is None:
            raise ValueError("the agent strategy needs `agent`")
        if self.strategy != "agent" and self.agent is not None:
            raise ValueError("`agent` is only used by the agent strategy")
        if self.strategy != "concat" and self.separator is not None:
            raise ValueError("`separator` is only used by the concat strategy")
        if self.strategy != "vote" and self.min_votes is not None:
            raise ValueError("`min_votes` is only used by the vote strategy")
        return self


class ParallelNode(_Base):
    """Runs its branches at the same time, each on the parallel's input, and joins them.

    `join` says when the parallel is done: `all` once every branch completed, `any` once one
    did, `quorum` once `quorum` did. It decides as soon as the outcome is known (`all` fails on
    the first branch that does not complete, the others once the join can no longer be met) and
    the branches still running end `node_cancelled`. `settled` (4.6) never decides early: it
    waits for every branch to end and completes if at least one completed, so one failed branch
    does not cancel the others. Its output is the completed branches' outputs in branch order.
    A branch is one `agent`, `tool` or `sequence` node (4.6: or a `parallel` or a router, and a
    reduce that writes nothing), its id names the branch, and it holds no gate, writer or
    publisher. Every agent in the branches counts toward the run's `agents_spawned` limit when
    the parallel starts."""

    type: Literal["parallel"]
    id: NodeId
    branches: list["Node"] = Field(min_length=2, max_length=MAX_AGENTS_ALIVE)
    join: Literal["all", "any", "quorum", "settled"]
    quorum: int | None = Field(
        default=None, description="`quorum` only, and required: how many branches must complete."
    )

    @model_validator(mode="after")
    def _join_fields(self) -> Self:
        if self.join != "quorum":
            if self.quorum is not None:
                raise ValueError("`quorum` is only used by the quorum join")
            return self
        if self.quorum is None:
            raise ValueError("the quorum join needs `quorum`")
        if not 1 <= self.quorum <= len(self.branches):
            raise ValueError(
                f"`quorum` {self.quorum} must be from 1 to the {len(self.branches)} branches"
            )
        return self


MAX_ROUTES = 8
"""Routes a router may have, besides its `default`."""

DEFAULT_ROUTE = "default"
"""The name `route_chosen` gives a router's `default`; no route may take it as its id."""


class Route(_Base):
    """One way a router can go: `then` runs when this route is chosen."""

    id: NodeId = Field(description="The route's name, shown in the console and the events.")
    when: NonEmptyStr | None = Field(
        default=None,
        description="Rule mode, and required there: the CEL condition that picks this route.",
        examples=['artifacts["findings.json"].findings.size() == 0'],
    )
    description: Annotated[str, Field(max_length=300)] | None = Field(
        default=None, description="What the route is for; a classifier is shown it to choose."
    )
    then: "Node" = Field(description="What runs on this route: one agent, tool or sequence node.")


class RouterClassifier(_Base):
    """The agent that chooses a router's route (classifier mode), as for an `agent` node. It
    answers with one of the router's route ids and a reason, through a typed output the engine
    makes (`classifier_schema`)."""

    instructions: NonEmptyStr
    provider: Literal["claude"] | None = Field(
        default=None, description="Unset means the workspace default."
    )
    model: NonEmptyStr | None = None


class RouterNode(_Base):
    """Runs exactly one of its routes, on the router's input, and outputs what that route outputs.

    In rule mode every route has `when`, a CEL condition over `last` (the router's input),
    `results` and `artifacts` (as for a loop's `until`); the first route whose condition is true
    runs, else `default`. In classifier mode no route has `when`: one agent (`classifier`)
    chooses a route id, `default` included when there is one, and says why. A router with no
    matching route and no `default` fails. The routes not taken never start. A route is one
    `agent`, `tool` or `sequence` node, and it may hold what the router's own place allows."""

    type: Literal["router"]
    id: NodeId
    routes: list[Route] = Field(min_length=1, max_length=MAX_ROUTES)
    default: "Node | None" = Field(default=None, description="What runs when no route is chosen.")
    classifier: RouterClassifier | None = Field(
        default=None, description="Classifier mode: the agent that chooses the route."
    )

    @property
    def route_ids(self) -> list[str]:
        """The names a route can be chosen by, `default` last if the router has one."""
        ids = [route.id for route in self.routes]
        return [*ids, DEFAULT_ROUTE] if self.default is not None else ids

    def route(self, route_id: str) -> "Node":
        """What runs on the route named `route_id` (`default` for the default)."""
        if route_id == DEFAULT_ROUTE and self.default is not None:
            return self.default
        return next(route.then for route in self.routes if route.id == route_id)

    @model_validator(mode="after")
    def _mode_fields(self) -> Self:
        ids = [route.id for route in self.routes]
        if DEFAULT_ROUTE in ids:
            raise ValueError(f"no route may be named {DEFAULT_ROUTE!r}; use `default`")
        if len(set(ids)) != len(ids):
            raise ValueError("two routes have the same id")
        if self.classifier is None:
            if missing := [route.id for route in self.routes if route.when is None]:
                raise ValueError(
                    f"route {missing[0]!r} needs `when`, or the router needs `classifier`"
                )
        elif with_when := [route.id for route in self.routes if route.when is not None]:
            raise ValueError(
                f"route {with_when[0]!r} has `when`, but a classifier chooses this router's route"
            )
        return self


MAX_TASK_TITLE = 80
"""The longest title a hub may give a task."""

MAX_TASK_INSTRUCTIONS = 4000
"""The longest instructions a hub may give a task."""

TASK_ID_PATTERN = r"^(?!lock$)[a-z][a-z0-9_-]{0,39}$"
"""A task id a hub plans (6.1): a slug with no `.`, so `<orchestrator>.<task>` names one task's
writer unambiguously (`task_writer_key`); not `lock`, as git refuses a branch ending `.lock`."""


class OrchestratorHub(_Base):
    """The agent that plans an orchestrator's tasks, as for an `agent` node. It answers with the
    tasks through a typed output the engine makes (`orchestrator_plan_schema`). With `tools`, it
    may read the repo first, to plan from the code (6.9): read tools only, as it never writes;
    in a loop's later iteration, or a replan, it reads the integration branch once there is one."""

    role: NonEmptyStr
    instructions: NonEmptyStr
    provider: Literal["claude"] | None = Field(
        default=None, description="Unset means the workspace default."
    )
    model: NonEmptyStr | None = None
    tools: list[str] = Field(
        default_factory=list[str],
        description="The repo tools the hub may call while it plans: `repo.list_files`, "
        "`repo.read_file`, `repo.search` and `repo.list_modules` only.",
    )

    @field_validator("tools")
    @classmethod
    def _reads_only(cls, tools: list[str]) -> list[str]:
        if other := sorted(set(tools) - READ_TOOLS):
            raise ValueError(
                f"a hub may only read the repo, not call {', '.join(other)}; give the work "
                "to its worker instead"
            )
        return tools


MAX_REPLAN_ROUNDS = 3
"""The most times a hub may replan (6.2): each round is a hub turn and up to `max_workers` more
workers, so the cap keeps an orchestrator's cost bounded."""


class OrchestratorReplan(_Base):
    """When an orchestrator's hub plans again (6.2). On `failure`: once a task fails, no other
    task starts, those running finish, those not started are dropped, and the hub plans the
    remaining work from every task's outcome, at most `max_rounds` times."""

    on: Literal["failure"] = Field(description="What makes the hub plan again.")
    max_rounds: int = Field(
        default=1, ge=1, le=MAX_REPLAN_ROUNDS, description="The most times the hub replans."
    )


class OrchestratorNode(_Base):
    """A hub agent plans subtasks at runtime, and the engine runs its body (the worker) once per
    task, at most `max_concurrency` at a time (6.1).

    The hub gets the orchestrator's input and answers with at most `max_workers` tasks, each an
    `id`, a `title` and `instructions`. Each worker's input is `{"task": …, "input": …}` as JSON
    (the task is data, never the worker's instructions). The output is the workers' outputs in
    task order, and a `reduce` may combine them (its sources are the task ids). The body is one
    `agent` or a `sequence` of agent and tool nodes; a writer in it commits on its task's own
    branch (`agent/<run>/<orchestrator>.<task>`). The hub and every worker's agents count toward
    the run's `agents_spawned` limit once the plan is made; one worker that does not complete
    cancels the others and fails the orchestrator, unless `replan` (6.2) lets the hub plan the
    remaining work again. In a loop's body (6.9) it plans afresh each iteration, from the loop
    body's input and every earlier iteration's tasks, and every iteration's tasks build on its one
    integration branch."""

    type: Literal["orchestrator"]
    id: NodeId
    hub: OrchestratorHub
    body: "Node" = Field(description="The worker: what runs once per task.")
    max_workers: int = Field(
        ge=1, le=MAX_AGENTS_SPAWNED, description="The most tasks the hub may plan."
    )
    max_concurrency: int = Field(ge=1, le=MAX_AGENTS_ALIVE)
    replan: OrchestratorReplan | None = Field(
        default=None, description="Unset: a failed task fails the orchestrator."
    )
    writes: ArtifactName | None = Field(default=None, description=_WRITES_DESCRIPTION)


class WorkflowRef(_Base):
    """A stored workflow of the run's workspace, by id and version (6.5)."""

    id: NodeId = Field(description="The stored workflow's id.")
    version: int = Field(ge=1, description="The version to run; a version never changes.")


class SubflowNode(_Base):
    """Runs another stored workflow, by id and version, as one step of this one (6.5).

    The called workflow is read from the run's workspace when the run is created and runs inside
    this run: its nodes share the run's repo, sandbox, limits, budget, artifacts and event log,
    and their ids are its own. Its input is the subflow's input, or the value
    of `input`; its output is the called workflow's. A spec names the workflow only: the engine
    attaches the called workflow's root (`call`) when it resolves the run (`expand_workflow`). A
    node of the called workflow whose id the run already uses runs as `<subflow>-<id>`; the
    called workflow's own expressions still name it by its id."""

    type: Literal["subflow"]
    id: NodeId
    workflow: WorkflowRef = Field(description="The workflow to run, and which version.")
    input: NonEmptyStr | None = Field(
        default=None,
        description="A CEL expression over `last`, `results` and `artifacts` whose value is the "
        "called workflow's input (a string as it is, any other value as JSON); unset, it gets "
        "the subflow's input.",
    )
    _call: "Node | None" = PrivateAttr(default=None)
    _name: str | None = PrivateAttr(default=None)
    _ids: dict[str, str] = PrivateAttr(default_factory=dict[str, str])
    _input_schema: dict[str, JsonValue] | None = PrivateAttr(default=None)
    _output_schema: dict[str, JsonValue] | None = PrivateAttr(default=None)

    @property
    def call(self) -> "Node | None":
        """The called workflow's root, once resolved; `None` before."""
        return self._call

    @property
    def called_name(self) -> str | None:
        """The called workflow's name, once resolved."""
        return self._name

    @property
    def ids(self) -> dict[str, str]:
        """Once resolved, each node id of the called workflow (its own, not those of the
        workflows it calls in turn) to the id it runs under in this run: itself, unless another
        node of the run has it (`expand_workflow`)."""
        return dict(self._ids)

    @property
    def input_schema(self) -> dict[str, JsonValue] | None:
        """Once resolved, the called workflow's `input_schema` (6.6): the subflow's input port.
        A subflow with its own `input` expression has none, as its input is not the step before."""
        return self._input_schema if self.input is None else None

    @property
    def output_schema(self) -> dict[str, JsonValue] | None:
        """Once resolved, the called workflow's `output_schema` (6.6): the subflow's output
        port."""
        return self._output_schema

    @property
    def boundary_input_schema(self) -> dict[str, JsonValue] | None:
        """The called workflow's `input_schema`, checked at runtime against what the called
        workflow is given, whether it comes from the step before or from `input`."""
        return self._input_schema

    def resolved(
        self,
        root: "Node",
        name: str,
        ids: Mapping[str, str],
        input_schema: dict[str, JsonValue] | None = None,
        output_schema: dict[str, JsonValue] | None = None,
    ) -> "SubflowNode":
        """This subflow with the called workflow's `root`, `name`, node `ids` and port schemas
        attached."""
        copy = self.model_copy()
        copy._call = root
        copy._name = name
        copy._ids = dict(ids)
        copy._input_schema = input_schema
        copy._output_schema = output_schema
        return copy


Node = Annotated[
    AgentNode
    | ToolNode
    | GateNode
    | SequenceNode
    | LoopNode
    | MapNode
    | ReduceNode
    | ParallelNode
    | RouterNode
    | OrchestratorNode
    | SubflowNode,
    Field(discriminator="type"),
]


def orchestrator_plan_schema(
    node: OrchestratorNode, max_tasks: int | None = None
) -> dict[str, JsonValue]:
    """The output schema of `node`'s hub: at most `max_tasks` tasks (`max_workers` unless a
    replan says fewer), and why it split the work so. Unique task ids are checked by the engine
    once the plan matches."""
    return {
        "type": "object",
        "required": ["tasks", "reason"],
        "properties": {
            "tasks": {
                "type": "array",
                "maxItems": node.max_workers if max_tasks is None else max_tasks,
                "items": {
                    "type": "object",
                    "required": ["id", "title", "instructions"],
                    "properties": {
                        "id": {"type": "string", "pattern": TASK_ID_PATTERN},
                        "title": {"type": "string", "minLength": 1, "maxLength": MAX_TASK_TITLE},
                        "instructions": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": MAX_TASK_INSTRUCTIONS,
                        },
                    },
                    "additionalProperties": False,
                },
            },
            "reason": {"type": "string", "maxLength": 300},
        },
        "additionalProperties": False,
    }


def task_writer_key(orchestrator_id: str, task_id: str) -> str:
    """What a writer in `orchestrator_id`'s body is known by while it works on task `task_id`:
    its worktree, its branch (`agent/<run>/<key>`) and the node a gate's edits name. A `NodeId`
    and a task id have no `.`, so the key is never another node's id."""
    return f"{orchestrator_id}.{task_id}"


def task_writer_orchestrator(key: str) -> str | None:
    """The orchestrator a task writer's key (`task_writer_key`) belongs to; `None` for a node
    id."""
    orchestrator, dot, _ = key.partition(".")
    return orchestrator if dot else None


def classifier_schema(router: RouterNode) -> dict[str, JsonValue]:
    """The output schema of `router`'s classifier: one of its route ids and why."""
    ids: list[JsonValue] = list(router.route_ids)
    return {
        "type": "object",
        "required": ["route", "reason"],
        "properties": {
            "route": {"enum": ids},
            "reason": {"type": "string", "maxLength": 300},
        },
        "additionalProperties": False,
    }


def router_routes(router: RouterNode, path: str) -> list[tuple[str, str, "Node"]]:
    """`(route id, path, node)` for each of `router`'s routes, `default` last."""
    routes = [(r.id, f"{path}.routes[{i}].then", r.then) for i, r in enumerate(router.routes)]
    if router.default is not None:
        routes.append((DEFAULT_ROUTE, f"{path}.default", router.default))
    return routes


def iter_nodes(node: Node, path: str = "root") -> Iterator[tuple[str, Node]]:
    """Yield `(path, node)` for `node` and all its descendants, depth first.

    Paths use the JSON field names, e.g. `root.steps[1].steps[0]`.
    """
    yield path, node
    match node:
        case SequenceNode():
            for i, step in enumerate(node.steps):
                yield from iter_nodes(step, f"{path}.steps[{i}]")
        case LoopNode() | MapNode() | OrchestratorNode():
            yield from iter_nodes(node.body, f"{path}.body")
        case ParallelNode():
            for i, branch in enumerate(node.branches):
                yield from iter_nodes(branch, f"{path}.branches[{i}]")
        case RouterNode():
            for _, route_path, route in router_routes(node, path):
                yield from iter_nodes(route, route_path)
        case SubflowNode() if node.call is not None:
            yield from iter_nodes(node.call, f"{path}.call")
        case _:
            pass


_SCOPE = re.compile(r"\.(branches\[\d+\]|routes\[\d+\]\.then|default|body)")


def scope_of(path: str) -> str:
    """The innermost parallel branch, router route, or loop or map body the node at `path` is
    in, as that branch's, route's or body's path; `""` for none. What runs there may not run at
    all (a route not taken) or runs apart from the rest of the run (a branch, an item)."""
    ends = [m.end() for m in _SCOPE.finditer(path)]
    return path[: ends[-1]] if ends else ""


def within(path: str, scope: str) -> bool:
    """Whether the node at `path` is in `scope` (`scope_of`); everything is in `""`."""
    return not scope or path == scope or path.startswith((f"{scope}.", f"{scope}["))


def node_tools(node: Node) -> list[str]:
    """The platform tools `node` itself may call: an agent's `tools`, a tool node's `tool`, an
    orchestrator's hub's `tools` (its worker's are its body's)."""
    match node:
        case AgentNode():
            return list(node.tools)
        case ToolNode():
            return [node.tool]
        case OrchestratorNode():
            return list(node.hub.tools)
        case (
            GateNode()
            | SequenceNode()
            | LoopNode()
            | MapNode()
            | ReduceNode()
            | ParallelNode()
            | RouterNode()
            | SubflowNode()
        ):
            return []


READ_TOOLS = frozenset({"repo.list_files", "repo.read_file", "repo.search", "repo.list_modules"})
"""Tools that read the run's repo in the sandbox."""

WRITE_TOOLS = frozenset({"repo.write_file", "repo.commit"})
"""Tools that change a node's own branch in the sandbox: a node naming one is a writer."""

PUBLISH_TOOLS = frozenset({"github.openPR"})
"""Tools that publish a writer's branch outside the sandbox (push, pull request). They are
irreversible, so only a tool node may call one, after a gate that follows the writer."""

CREATE_TOOLS = frozenset({"github.createRepo"})
"""Tools that create the run's repo on GitHub. Irreversible, so only a tool node may call one,
after a gate, as a step of the root sequence before anything uses the repo."""

ARTIFACT_TOOLS = frozenset({"artifacts.list", "artifacts.read"})
"""Tools that read the run's artifacts (4.3). Every run has them, with or without a repo."""

SCAN_TOOLS = frozenset({"scan.lint", "scan.secrets", "scan.dependencies"})
"""Deterministic scanners over the run's repo in the sandbox (4.4): read-only, so allowed
everywhere. Each returns a findings report (`agentic_runtime.findings.FindingsReport`)."""

PLATFORM_TOOLS = (
    READ_TOOLS | WRITE_TOOLS | PUBLISH_TOOLS | CREATE_TOOLS | ARTIFACT_TOOLS | SCAN_TOOLS
)
"""Every tool a node may name. The tool servers register exactly these (checked in tests)."""

type IssueCode = Literal[
    "schema",
    "id_mismatch",
    "duplicate_node_id",
    "invalid_expression",
    "not_allowed_in_loop",
    "not_allowed_in_map",
    "not_allowed_in_parallel",
    "reference",
    "publish_not_tool_node",
    "publish_without_gate",
    "create_not_tool_node",
    "create_without_gate",
    "create_not_first",
    "unknown_tool",
    "policy_limit",
    "budget_unpriced_model",
    "invalid_schema",
    "port_mismatch",
    "artifact_unknown",
    "artifact_conflict",
    "invalid_vote",
    "invalid_router",
    "not_allowed_in_orchestrator",
    "subflow_unknown",
    "subflow_cycle",
    "subflow_unpublished",
    "invalid_gate",
]


class ValidationIssue(_Base):
    """One reason a workflow cannot run: what is wrong (`code`), where (`path`, `node_id`) and
    what to change (`message`). A `policy_limit` issue also names the `limit`, its `value` and
    what the spec would reach (`observed`)."""

    code: IssueCode = Field(description="The kind of problem; stable, so clients may branch on it.")
    path: str = Field(
        description="Where in the spec, by its JSON field names, e.g. `root.steps[1].body`; "
        "empty for the document itself.",
        examples=["root.steps[1].body"],
    )
    node_id: str | None = Field(default=None, description="The node to fix, if there is one.")
    message: str = Field(description="The problem and what to change, for people.")
    limit: PolicyLimit | None = None
    value: int | None = Field(default=None, description="The limit's value.")
    observed: int | None = Field(default=None, description="What the spec would reach.")


def messages(issues: list[ValidationIssue]) -> list[str]:
    """The issues' messages, in order."""
    return [issue.message for issue in issues]


def duplicate_id_issues(root: Node) -> list[ValidationIssue]:
    """Each node under `root` whose id an earlier node already uses, in run order."""
    issues: list[ValidationIssue] = []
    seen: dict[str, str] = {}
    for path, node in iter_nodes(root):
        if node.id not in seen:
            seen[node.id] = path
            continue
        issues.append(
            ValidationIssue(
                code="duplicate_node_id",
                path=path,
                node_id=node.id,
                message=f"duplicate node id {node.id!r} at {path} (first used at "
                f"{seen[node.id]}); node ids must be unique",
            )
        )
    return issues


def publish_gate_issues(root: Node) -> list[ValidationIssue]:
    """Why the publishing nodes under `root` are not safe to run, in run order (depth first);
    empty if they are. Each must be a tool node whose `from_node` names an earlier writer (an
    orchestrator whose tasks write publishes its integration branch, 6.3), with a gate between
    that writer and itself, so a human approves what is published."""
    issues: list[ValidationIssue] = []
    seen: list[tuple[str, Node]] = []
    tasked = task_workers(root)
    loops: set[str] = set()
    for path, node in iter_nodes(root):
        if isinstance(node, OrchestratorNode):
            seen.append((_runs_in(path, loops), node))
            continue
        if isinstance(node, LoopNode):
            loops.add(path)
        if isinstance(node, SequenceNode | LoopNode | MapNode | ParallelNode | RouterNode):
            continue
        for tool in sorted(PUBLISH_TOOLS.intersection(node_tools(node))):
            if not isinstance(node, ToolNode):
                message = f"node {node.id!r}: {tool} can only be called by a tool node"
                issues.append(
                    ValidationIssue(
                        code="publish_not_tool_node", path=path, node_id=node.id, message=message
                    )
                )
                continue
            # A writer or gate on a route of a router may not have run: only those whose
            # route holds the publisher too count.
            earlier = [n for at, n in seen if within(path, scope_of(at))]
            if found := _publish_issue(node, earlier, tasked):
                code, message = found
                issues.append(
                    ValidationIssue(code=code, path=path, node_id=node.id, message=message)
                )
        seen.append((_runs_in(path, loops), node))
    return issues


def _runs_in(path: str, loops: Collection[str]) -> str:
    """`path` as where its node runs for the nodes after it: a loop's body runs at least once and
    ends before the nodes after the loop (6.9), so a node in it counts as at its loop's place."""
    scope = scope_of(path)
    while scope.endswith(".body") and scope.removesuffix(".body") in loops:
        path = scope.removesuffix(".body")
        scope = scope_of(path)
    return path


def publish_gate_errors(root: Node) -> list[str]:
    """The messages of `publish_gate_issues`."""
    return messages(publish_gate_issues(root))


def _publish_issue(
    node: "ToolNode", earlier: list[Node], tasked: Mapping[str, str] | None = None
) -> tuple[IssueCode, str] | None:
    source = node.args.get("from_node")
    if not isinstance(source, str):
        return (
            "reference",
            f"node {node.id!r}: {node.tool} needs `from_node`, the writer to publish",
        )
    if (orchestrator := (tasked or {}).get(source)) is not None:
        return (
            "reference",
            f"node {node.id!r}: `from_node` {source!r} is a worker of {orchestrator!r}, which "
            f"writes once per task; publish {orchestrator!r}, its integration branch, instead",
        )
    ids = [n.id for n in earlier]
    if source not in ids:
        return (
            "reference",
            f"node {node.id!r}: `from_node` {source!r} is not a node that runs before it",
        )
    writer = earlier[ids.index(source)]
    if not _writes(writer):
        return "reference", f"node {node.id!r}: `from_node` {source!r} is not a writer"
    between = earlier[ids.index(source) + 1 :]
    if not any(isinstance(n, GateNode) for n in between):
        return (
            "publish_without_gate",
            f"node {node.id!r}: {node.tool} must come after a gate that follows {source!r}, so "
            "a human approves what is published",
        )
    return None


def create_repo_issues(root: Node) -> list[ValidationIssue]:
    """Why the nodes under `root` that create the run's repo are not safe to run, in run order;
    empty if they are. Each must be a tool node, a step of the root sequence, and the only one;
    a gate must come before it, so a human approves the new repo, and no node before it may use
    the repo (`repo.*`, `github.*`), which does not exist yet."""
    issues: list[ValidationIssue] = []
    top = {id(step) for step in root.steps} if isinstance(root, SequenceNode) else set[int]()
    earlier: list[Node] = []
    created = False
    for path, node in iter_nodes(root):
        tools = node_tools(node)
        for tool in sorted(CREATE_TOOLS.intersection(tools)):
            found: tuple[IssueCode, str] | None
            if not isinstance(node, ToolNode):
                found = (
                    "create_not_tool_node",
                    f"node {node.id!r}: {tool} can only be called by a tool node",
                )
            elif created:
                found = (
                    "create_not_first",
                    f"node {node.id!r}: a workflow creates at most one repo",
                )
            elif id(node) not in top:
                found = (
                    "create_not_first",
                    f"node {node.id!r}: {tool} must be a step of the root sequence",
                )
            elif user := next((n for n in earlier if _uses_repo(n)), None):
                found = (
                    "create_not_first",
                    f"node {node.id!r}: {tool} must come before {user.id!r}, which uses the repo",
                )
            elif not any(isinstance(n, GateNode) for n in earlier):
                found = (
                    "create_without_gate",
                    f"node {node.id!r}: {tool} must come after a gate, so a human approves the "
                    "new repo",
                )
            else:
                found = None
            if found is not None:
                code, message = found
                issues.append(
                    ValidationIssue(code=code, path=path, node_id=node.id, message=message)
                )
            created = True
        earlier.append(node)
    return issues


def creates_repo(root: Node) -> bool:
    """Whether a node under `root` creates the run's repo."""
    return any(CREATE_TOOLS.intersection(node_tools(node)) for _, node in iter_nodes(root))


REPO_TOOL_PREFIXES = ("repo.", "github.", "scan.")
"""Tools that work on the run's repo, so a run naming one needs a repo: `repo.*` and `scan.*` in
its sandbox, `github.*` on its GitHub remote."""


def _uses_repo(node: Node) -> bool:
    return any(tool.startswith(REPO_TOOL_PREFIXES) for tool in node_tools(node))


def loop_issues(root: Node) -> list[ValidationIssue]:
    """Why the loops under `root` cannot run, in run order (depth first); empty if they can. A
    loop's `until` must be a valid condition, and its body must not hold a gate, a writer, a
    publisher, another loop, a map or a parallel: the issue is on that node, which is the one to
    move. An orchestrator may be in it (6.9): its worker is checked by `orchestrator_issues`, and
    its writers, which commit on task branches merged into its integration branch, are allowed."""
    issues: list[ValidationIssue] = []
    for path, node in iter_nodes(root):
        if not isinstance(node, LoopNode):
            continue
        try:
            compile_condition(node.until)
        except ExpressionError as e:
            message = f"loop {node.id!r} at {path}: invalid until: {e}"
            issues.append(
                ValidationIssue(
                    code="invalid_expression", path=path, node_id=node.id, message=message
                )
            )
        for inner_path, inner in _outside_workers(node.body, f"{path}.body"):
            if reason := _not_in_loop(inner):
                message = (
                    f"loop {node.id!r} at {path}: {reason} {inner.id!r} at {inner_path} cannot "
                    "be inside a loop yet"
                )
                issues.append(
                    ValidationIssue(
                        code="not_allowed_in_loop",
                        path=inner_path,
                        node_id=inner.id,
                        message=message,
                    )
                )
    return issues


def loop_errors(root: Node) -> list[str]:
    """The messages of `loop_issues`."""
    return messages(loop_issues(root))


def _outside_workers(node: Node, path: str) -> Iterator[tuple[str, Node]]:
    """`iter_nodes`, without the nodes of an orchestrator's worker: they run once per task, and
    `orchestrator_issues` checks them."""
    workers: list[str] = []
    for at, inner in iter_nodes(node, path):
        if any(within(at, worker) for worker in workers):
            continue
        if isinstance(inner, OrchestratorNode):
            workers.append(f"{at}.body")
        yield at, inner


def _not_in_loop(node: Node) -> str | None:
    tools = set(node_tools(node))
    match node:
        case GateNode():
            return "gate"
        case LoopNode():
            return "loop"
        case MapNode():
            return "map"
        case ParallelNode():
            return "parallel"
        case OrchestratorNode():
            return None  # 6.9: planned afresh each iteration, on one integration branch
        case _ if tools & PUBLISH_TOOLS:
            return "publisher"
        case _ if tools & CREATE_TOOLS:
            return "repo creator"
        case _ if tools & WRITE_TOOLS:
            return "writer"
        case _:
            return None


def map_issues(root: Node) -> list[ValidationIssue]:
    """Why the maps and reduces under `root` cannot run, in run order (depth first); empty if
    they can. A map's `over` must be a valid list expression, and its body must hold only agent,
    tool, sequence and router nodes, none of them a writer or a publisher. A reduce's `from` must
    name a map or a parallel that runs before it, in the same branch, route or body or around it,
    and a vote's `min_votes` must be reachable by that parallel's join (`invalid_vote`; a map's
    item count is only known when it runs)."""
    issues: list[ValidationIssue] = []
    sources: dict[str, MapNode | ParallelNode | OrchestratorNode] = {}
    scopes: dict[str, str] = {}
    for path, node in iter_nodes(root):
        match node:
            case MapNode():
                try:
                    compile_list(node.over)
                except ExpressionError as e:
                    message = f"map {node.id!r} at {path}: invalid over: {e}"
                    issues.append(
                        ValidationIssue(
                            code="invalid_expression", path=path, node_id=node.id, message=message
                        )
                    )
                for inner_path, inner in iter_nodes(node.body, f"{path}.body"):
                    if reason := _not_in_map(inner):
                        message = (
                            f"map {node.id!r} at {path}: {reason} {inner.id!r} at {inner_path} "
                            "cannot be inside a map yet"
                        )
                        issues.append(
                            ValidationIssue(
                                code="not_allowed_in_map",
                                path=inner_path,
                                node_id=inner.id,
                                message=message,
                            )
                        )
                sources[node.id] = node
                scopes[node.id] = scope_of(path)
            case ParallelNode() | OrchestratorNode():
                sources[node.id] = node
                scopes[node.id] = scope_of(path)
            case ReduceNode() if node.from_ not in sources:
                message = (
                    f"reduce {node.id!r} at {path}: `from` {node.from_!r} is not a map, "
                    "parallel or orchestrator that runs before it"
                )
                issues.append(
                    ValidationIssue(code="reference", path=path, node_id=node.id, message=message)
                )
            # A source in a branch, route or body the reduce is not in may not have run.
            case ReduceNode() if not within(path, scopes[node.from_]):
                message = (
                    f"reduce {node.id!r} at {path}: `from` {node.from_!r} runs inside "
                    f"{scopes[node.from_]}, which the reduce is not in; move the reduce there"
                )
                issues.append(
                    ValidationIssue(code="reference", path=path, node_id=node.id, message=message)
                )
            case ReduceNode() if node.min_votes is not None:
                source = sources[node.from_]
                if isinstance(source, ParallelNode) and (why := _votes_unreachable(node, source)):
                    issues.append(
                        ValidationIssue(
                            code="invalid_vote",
                            path=path,
                            node_id=node.id,
                            message=f"reduce {node.id!r} at {path}: {why}",
                        )
                    )
            case _:
                pass
    return issues


def _votes_unreachable(reduce: ReduceNode, parallel: ParallelNode) -> str | None:
    """Why `reduce`'s `min_votes` can never be met by the branches of `parallel` that complete."""
    votes, branches = reduce.min_votes or 0, len(parallel.branches)
    if votes > branches:
        return f"`min_votes` {votes} is more than the {branches} branches of {parallel.id!r}"
    if parallel.join == "any" and votes > 1:
        return f"`min_votes` {votes} needs more than the one branch an `any` join waits for"
    if parallel.join == "quorum" and votes > (parallel.quorum or 0):
        return (
            f"`min_votes` {votes} is more than the {parallel.quorum} branches the quorum join "
            "waits for"
        )
    return None


def map_errors(root: Node) -> list[str]:
    """The messages of `map_issues`."""
    return messages(map_issues(root))


def _not_in_map(node: Node) -> str | None:
    match node:
        # A subflow's called nodes are checked as nodes of the map themselves.
        case AgentNode() | ToolNode() | SequenceNode() | RouterNode() | SubflowNode():
            return _not_in_loop(node)
        case _:
            return node.type


def _not_in_parallel(node: Node) -> str | None:
    """Why `node` cannot be in a parallel's branch: as in a map's body, but a branch may also
    hold a parallel, and a reduce that writes no artifact (4.6)."""
    match node:
        case ParallelNode():
            return None
        case ReduceNode():
            return "writing reduce" if node.writes else None
        case _:
            return _not_in_map(node)


def parallel_issues(root: Node) -> list[ValidationIssue]:
    """Why the parallels under `root` cannot run, in run order (depth first); empty if they can.
    A branch must hold only agent, tool, sequence, router and parallel nodes and reduces that
    write no artifact, none of them a writer or a publisher: the issue is on that node, which is
    the one to move."""
    issues: list[ValidationIssue] = []
    for path, node in iter_nodes(root):
        if not isinstance(node, ParallelNode):
            continue
        for i, branch in enumerate(node.branches):
            for inner_path, inner in iter_nodes(branch, f"{path}.branches[{i}]"):
                if reason := _not_in_parallel(inner):
                    message = (
                        f"parallel {node.id!r} at {path}: {reason} {inner.id!r} at {inner_path} "
                        "cannot be inside a parallel yet"
                    )
                    issues.append(
                        ValidationIssue(
                            code="not_allowed_in_parallel",
                            path=inner_path,
                            node_id=inner.id,
                            message=message,
                        )
                    )
    return issues


def router_issues(root: Node) -> list[ValidationIssue]:
    """Why the routers under `root` cannot run, in run order; empty if they can. Each `when` must
    be a valid condition (`invalid_expression`, on the `when`), and each route an agent, tool or
    sequence node (`invalid_router`, on the route)."""
    issues: list[ValidationIssue] = []
    for path, node in iter_nodes(root):
        if not isinstance(node, RouterNode):
            continue
        for i, route in enumerate(node.routes):
            if route.when is None:
                continue
            try:
                compile_condition(route.when, ROUTE_VARIABLES)
            except ExpressionError as e:
                message = f"router {node.id!r} at {path}: route {route.id!r}: invalid when: {e}"
                issues.append(
                    ValidationIssue(
                        code="invalid_expression",
                        path=f"{path}.routes[{i}].when",
                        node_id=node.id,
                        message=message,
                    )
                )
        for route_id, route_path, route in router_routes(node, path):
            if isinstance(route, AgentNode | ToolNode | SequenceNode):
                continue
            message = (
                f"router {node.id!r} at {path}: route {route_id!r} is {route.type} {route.id!r}; "
                "a route is one agent, tool or sequence node (wrap it in a sequence)"
            )
            issues.append(
                ValidationIssue(
                    code="invalid_router", path=route_path, node_id=route.id, message=message
                )
            )
    return issues


def _not_in_orchestrator(node: Node) -> str | None:
    """Why `node` cannot be in an orchestrator's body (its worker) in 6.1: only agent, tool and
    sequence nodes, and no publisher or repo creator. A writer may be there: it writes on its
    task's own branch."""
    tools = set(node_tools(node))
    match node:
        case AgentNode() | ToolNode() | SequenceNode():
            if tools & PUBLISH_TOOLS:
                return "publisher"
            if tools & CREATE_TOOLS:
                return "repo creator"
            return None
        case _:
            return node.type


def orchestrator_issues(root: Node) -> list[ValidationIssue]:
    """Why the orchestrators under `root` cannot run, in run order; empty if they can. Its body
    may hold only agent, tool and sequence nodes, none of them a publisher or a repo creator
    (`not_allowed_in_orchestrator`, on that node). An orchestrator may not be inside a map, a
    parallel or another orchestrator (the map and parallel rules and this one say so); it may be
    in a loop (6.9)."""
    issues: list[ValidationIssue] = []
    for path, node in iter_nodes(root):
        if not isinstance(node, OrchestratorNode):
            continue
        for inner_path, inner in iter_nodes(node.body, f"{path}.body"):
            if reason := _not_in_orchestrator(inner):
                message = (
                    f"orchestrator {node.id!r} at {path}: {reason} {inner.id!r} at {inner_path} "
                    "cannot be inside an orchestrator's worker yet"
                )
                issues.append(
                    ValidationIssue(
                        code="not_allowed_in_orchestrator",
                        path=inner_path,
                        node_id=inner.id,
                        message=message,
                    )
                )
    return issues


def task_workers(root: Node) -> dict[str, str]:
    """The id of every node in the body of an orchestrator under `root`, to that orchestrator's
    id: nodes that run once per planned task."""
    return {
        inner.id: node.id
        for _, node in iter_nodes(root)
        if isinstance(node, OrchestratorNode)
        for _, inner in iter_nodes(node.body)
    }


def _writes(node: Node) -> bool:
    """Whether `node` has a branch to publish: it may write itself, or it is an orchestrator
    whose tasks may write (their integration branch, 6.3)."""
    if isinstance(node, OrchestratorNode):
        return any(WRITE_TOOLS.intersection(node_tools(n)) for _, n in iter_nodes(node.body))
    return bool(WRITE_TOOLS.intersection(node_tools(node)))


def task_node_ids(root: Node) -> set[str]:
    """The ids of the orchestrators under `root` and of every node in their bodies: nodes that
    run once per planned task."""
    ids: set[str] = set()
    for _, node in iter_nodes(root):
        if isinstance(node, OrchestratorNode):
            ids.add(node.id)
            ids.update(inner.id for _, inner in iter_nodes(node.body))
    return ids


def tool_issues(root: Node, known_tools: Collection[str] = PLATFORM_TOOLS) -> list[ValidationIssue]:
    """Each tool a node under `root` names that is not one of `known_tools`, in run order."""
    issues: list[ValidationIssue] = []
    known = ", ".join(sorted(known_tools))
    for path, node in iter_nodes(root):
        for tool in node_tools(node):
            if tool in known_tools:
                continue
            message = (
                f"{node.type} {node.id!r} at {path}: unknown tool {tool!r}; use one of {known}"
            )
            issues.append(
                ValidationIssue(code="unknown_tool", path=path, node_id=node.id, message=message)
            )
    return issues


def policy_issues(root: Node, policy: Policy) -> list[ValidationIssue]:
    """Why the spec under `root` cannot run under `policy`, in run order (depth first); empty if
    it can. A loop's `max_iterations` must be within `loop_iterations`, a map's
    `max_concurrency` and a parallel's branches within `agents_alive`, and loops, maps and
    parallels must not nest deeper than `max_depth`, and a gate's `ttl_s` must be within
    `approval_ttl_s`. Agents spawned and wall time are only known at runtime, where the engine
    checks them; agents beyond `agents_alive` at once (a parallel inside a branch) wait there for
    a slot."""
    issues: list[ValidationIssue] = []

    def over(
        node: Node, path: str, limit: PolicyLimit, value: int, observed: int, why: str
    ) -> None:
        issues.append(
            ValidationIssue(
                code="policy_limit",
                path=path,
                node_id=node.id,
                message=f"{node.type} {node.id!r} at {path}: {why}",
                limit=limit,
                value=value,
                observed=observed,
            )
        )

    def visit(node: Node, path: str, depth: int) -> None:
        match node:
            case LoopNode() if node.max_iterations > policy.loop_iterations:
                why = (
                    f"max_iterations {node.max_iterations} is above the workspace limit of "
                    f"{policy.loop_iterations}"
                )
                over(
                    node, path, "loop_iterations", policy.loop_iterations, node.max_iterations, why
                )
            case MapNode() | OrchestratorNode() if node.max_concurrency > policy.agents_alive:
                why = (
                    f"max_concurrency {node.max_concurrency} is above the workspace limit of "
                    f"{policy.agents_alive} agents alive"
                )
                over(node, path, "agents_alive", policy.agents_alive, node.max_concurrency, why)
            case ParallelNode() if len(node.branches) > policy.agents_alive:
                why = (
                    f"{len(node.branches)} branches are above the workspace limit of "
                    f"{policy.agents_alive} agents alive"
                )
                over(node, path, "agents_alive", policy.agents_alive, len(node.branches), why)
            case GateNode() if node.ttl_s is not None and node.ttl_s > policy.approval_ttl_s:
                why = (
                    f"ttl_s {node.ttl_s} is above the workspace limit of "
                    f"{policy.approval_ttl_s} seconds"
                )
                over(node, path, "approval_ttl_s", policy.approval_ttl_s, node.ttl_s, why)
            case _:
                pass
        match node:
            case LoopNode() | MapNode() | ParallelNode() | OrchestratorNode():
                if depth + 1 > policy.max_depth:
                    why = (
                        f"nesting depth {depth + 1} is above the workspace limit of "
                        f"{policy.max_depth}"
                    )
                    over(node, path, "max_depth", policy.max_depth, depth + 1, why)
                if isinstance(node, ParallelNode):
                    for i, branch in enumerate(node.branches):
                        visit(branch, f"{path}.branches[{i}]", depth + 1)
                else:
                    visit(node.body, f"{path}.body", depth + 1)
            case SequenceNode():
                for i, step in enumerate(node.steps):
                    visit(step, f"{path}.steps[{i}]", depth)
            case RouterNode():
                for _, route_path, route in router_routes(node, path):
                    visit(route, route_path, depth)
            case SubflowNode() if node.call is not None:
                # A call is a level of nesting, so calls nest only as deep as `max_depth`. One
                # that was not resolved has its own issue (`expand_workflow`).
                if depth + 1 > policy.max_depth:
                    why = (
                        f"nesting depth {depth + 1} is above the workspace limit of "
                        f"{policy.max_depth}"
                    )
                    over(node, path, "max_depth", policy.max_depth, depth + 1, why)
                else:
                    visit(node.call, f"{path}.call", depth + 1)
            case _:
                pass

    visit(root, "root", 0)
    return issues


def agents_spawned(node: Node) -> int:
    """The most agents `node` starts, counted before it runs: a router its classifier and its
    largest route. A map's items are only known when it runs, so a map counts none here, and an
    orchestrator only its hub (its workers are counted once it has planned them)."""
    match node:
        case AgentNode():
            return 1
        case ReduceNode():
            return 1 if node.agent is not None else 0
        case ToolNode() | GateNode() | MapNode():
            return 0
        case OrchestratorNode():
            return 1
        case SequenceNode():
            return sum(agents_spawned(step) for step in node.steps)
        case LoopNode():
            return agents_spawned(node.body)
        case ParallelNode():
            return sum(agents_spawned(branch) for branch in node.branches)
        case RouterNode():
            routes = [agents_spawned(route) for _, _, route in router_routes(node, "")]
            return (1 if node.classifier is not None else 0) + max(routes)
        case SubflowNode():
            return 0 if node.call is None else agents_spawned(node.call)


def policy_errors(root: Node, policy: Policy) -> list[str]:
    """The messages of `policy_issues`."""
    return messages(policy_issues(root, policy))


def budget_issues(
    root: Node, policy: Policy, priced: Callable[[str], bool], default_model: str
) -> list[ValidationIssue]:
    """Why the budget of `policy` cannot be held to the spec under `root`, in spec order; empty
    if it can, or if there is no budget. Every agent (a reduce's too) must run on a model that
    `priced` knows: its own `model`, else `default_model`. A usage with no price cannot be
    counted against a budget."""
    if policy.budget_usd is None:
        return []
    issues: list[ValidationIssue] = []
    for path, node in iter_nodes(root):
        match node:
            case AgentNode():
                model = node.model
            case ReduceNode() if node.agent is not None:
                model = node.agent.model
            case RouterNode() if node.classifier is not None:
                model = node.classifier.model
            case OrchestratorNode():
                model = node.hub.model
            case _:
                continue
        model = model or default_model
        if not priced(model):
            message = (
                f"{node.type} {node.id!r} at {path}: model {model!r} has no price, so the "
                "budget cannot be enforced"
            )
            issues.append(
                ValidationIssue(
                    code="budget_unpriced_model",
                    path=path,
                    node_id=node.id,
                    message=message,
                    limit="budget_usd",
                )
            )
    return issues


def budget_errors(
    root: Node, policy: Policy, priced: Callable[[str], bool], default_model: str
) -> list[str]:
    """The messages of `budget_issues`."""
    return messages(budget_issues(root, policy, priced, default_model))


type PortNode = AgentNode | ToolNode
"""A node that may declare typed ports."""

type PortConsumer = AgentNode | ToolNode | SubflowNode
"""A node whose input may be typed: a port node, or a subflow whose called workflow declares an
`input_schema` (6.6)."""

type PortProducer = AgentNode | ToolNode | ReduceNode | SubflowNode
"""A node whose output may be typed: a port node, a reduce that merges findings, or a subflow
whose called workflow declares an `output_schema` (6.6)."""

FINDINGS_SCHEMA: dict[str, JsonValue] = FindingsReport.model_json_schema()
"""The output schema of a `dedupe` or `vote` reduce: a findings report."""


def output_schema(node: PortProducer) -> dict[str, JsonValue] | None:
    """The schema `node`'s output is typed with, if any (a subflow's is its called workflow's)."""
    if isinstance(node, ReduceNode):
        return FINDINGS_SCHEMA if node.merges else None
    return node.output_schema


type ArtifactWriter = AgentNode | ToolNode | ReduceNode
"""A node that may write a run artifact."""


_UNTYPED = ReduceNode.model_validate(
    {"type": "reduce", "id": "untyped", "from": "untyped", "strategy": "concat"}
)
"""An artifact's writer when a router's routes write it with different types: a reduce that does
not merge has no typed output, so no port edge is drawn from it."""


@dataclass
class _ArtifactFlow:
    """What `_walk_artifacts` finds: each reader's writers, by artifact name, and the issues."""

    writers: dict[str, dict[str, ArtifactWriter]] = field(
        default_factory=dict[str, dict[str, ArtifactWriter]]
    )
    issues: list[ValidationIssue] = field(default_factory=list[ValidationIssue])


def _walk_artifacts(root: Node) -> _ArtifactFlow:
    """Follow the run artifacts under `root` in run order. A read must have a writer that has
    always run before it: an earlier step, not a sibling branch of the same parallel, and not a
    later step of the same loop body (its first iteration would not have it). A map's body may not
    write (its ids repeat for every item), and two branches of one parallel may not write the same
    name. After a parallel, what its branches wrote is visible; after a router, what all its
    routes wrote."""
    flow = _ArtifactFlow()

    def conflict(node: Node, path: str, why: str) -> None:
        message = f"{node.type} {node.id!r} at {path}: {why}"
        flow.issues.append(
            ValidationIssue(code="artifact_conflict", path=path, node_id=node.id, message=message)
        )

    def unknown(node: Node, path: str, name: str, verb: str) -> None:
        message = (
            f"{node.type} {node.id!r} at {path}: {verb} {name!r}, which no node writes before "
            "it; write it in an earlier step"
        )
        flow.issues.append(
            ValidationIssue(code="artifact_unknown", path=path, node_id=node.id, message=message)
        )

    def visit(node: Node, path: str, seen: dict[str, ArtifactWriter]) -> dict[str, ArtifactWriter]:
        match node:
            case AgentNode() | ToolNode():
                found: dict[str, ArtifactWriter] = {}
                for i, name in enumerate(node.reads):
                    if name in seen:
                        found[name] = seen[name]
                        continue
                    message = (
                        f"{node.type} {node.id!r} at {path}: reads {name!r}, which no node writes "
                        "before it; write it in an earlier step"
                    )
                    flow.issues.append(
                        ValidationIssue(
                            code="artifact_unknown",
                            path=f"{path}.reads[{i}]",
                            node_id=node.id,
                            message=message,
                        )
                    )
                if node.reads:
                    flow.writers[node.id] = found
                body_from = (
                    node.args.get("body_from")
                    if isinstance(node, ToolNode) and node.tool == "github.openPR"
                    else None
                )
                if isinstance(body_from, str) and body_from not in seen:
                    unknown(node, f"{path}.args.body_from", body_from, "takes its body from")
                return {**seen, node.writes: node} if node.writes else seen
            case ReduceNode():
                return {**seen, node.writes: node} if node.writes else seen
            case OrchestratorNode():
                for inner_path, inner in iter_nodes(node.body, f"{path}.body"):
                    if isinstance(inner, AgentNode | ToolNode | ReduceNode) and inner.writes:
                        conflict(
                            inner,
                            inner_path,
                            f"writes {inner.writes!r} inside orchestrator {node.id!r}, which runs "
                            "it once per task; give the orchestrator `writes` instead",
                        )
                visit(node.body, f"{path}.body", seen)
                return {**seen, node.writes: _UNTYPED} if node.writes else seen
            case GateNode():
                if node.select is None:
                    return seen
                name = node.select.artifact
                if name not in seen:
                    unknown(node, f"{path}.select.artifact", name, "selects from")
                    return seen
                # The chosen items keep the artifact's shape, so its writer types them.
                return {**seen, node.writes: seen[name]} if node.writes else seen
            case SequenceNode():
                for i, step in enumerate(node.steps):
                    seen = visit(step, f"{path}.steps[{i}]", seen)
                return seen
            case LoopNode():
                return visit(node.body, f"{path}.body", seen)
            case MapNode():
                for inner_path, inner in iter_nodes(node.body, f"{path}.body"):
                    if isinstance(inner, AgentNode | ToolNode | ReduceNode) and inner.writes:
                        conflict(
                            inner,
                            inner_path,
                            f"writes {inner.writes!r} inside map {node.id!r}, which runs it once "
                            "per item; write it after the map (e.g. from a reduce)",
                        )
                visit(node.body, f"{path}.body", seen)
                return seen
            case ParallelNode():
                after = dict(seen)
                by_branch: dict[str, str] = {}
                for i, branch in enumerate(node.branches):
                    branch_path = f"{path}.branches[{i}]"
                    wrote = visit(branch, branch_path, seen)
                    for name, writer in wrote.items():
                        if seen.get(name) is writer:
                            continue
                        if name in by_branch:
                            conflict(
                                writer,
                                branch_path,
                                f"writes {name!r}, which branch {by_branch[name]!r} of parallel "
                                f"{node.id!r} also writes; branches run at the same time",
                            )
                            continue
                        by_branch[name] = branch.id
                        after[name] = writer
                return after
            case RouterNode():
                # One route runs: a name is written after the router when every route writes
                # it. Its typed producer is the routes' writer when they all type it alike;
                # otherwise a reader of it has none.
                wrote = [visit(r, at, seen) for _, at, r in router_routes(node, path)]
                after = dict(seen)
                for name, writer in wrote[0].items():
                    writers = [w.get(name) for w in wrote]
                    if seen.get(name) is writer or any(w is None for w in writers):
                        continue
                    alike = all(
                        w is not None and output_schema(w) == output_schema(writer) for w in writers
                    )
                    after[name] = writer if alike else _UNTYPED
                return after
            case SubflowNode():
                # The called workflow runs in this run: what it writes is the run's.
                return seen if node.call is None else visit(node.call, f"{path}.call", seen)

    visit(root, "root", {})
    return flow


def artifact_issues(root: Node) -> list[ValidationIssue]:
    """Why the run artifacts under `root` cannot be exchanged, in run order: a read with no
    earlier writer (`artifact_unknown`, on the read), and a write that races
    (`artifact_conflict`, on the writer)."""
    return _walk_artifacts(root).issues


def artifact_writers(root: Node) -> dict[str, dict[str, ArtifactWriter]]:
    """For each node under `root` that reads run artifacts, the node that last wrote each of
    them before it (names with no earlier writer left out)."""
    return _walk_artifacts(root).writers


def port_edges(root: Node) -> list[tuple[PortProducer, PortConsumer, str]]:
    """Each place under `root` where one node's output is the next agent or tool node's input, as
    `(producer, consumer, consumer's path)` in run order: consecutive steps of a sequence (nested
    sequences flattened), looking through gates, which pass their input on unchanged. The producer
    is an agent or tool node, or a reduce that merges findings (its output is a findings report).
    A resolved subflow (6.6) is a consumer when its called workflow declares an `input_schema` (and
    it has no `input` expression of its own) and a producer when it declares an `output_schema`;
    an untyped one breaks the edge. A loop, map, parallel, router or other reduce between two
    steps breaks the edge: its output is not typed. A node that reads one run artifact takes it
    from the artifact's last writer instead (if that is a producer), and one that reads several
    has no producer."""
    edges: list[tuple[PortProducer, PortConsumer, str]] = []
    writers = artifact_writers(root)

    def steps(node: Node, path: str) -> Iterator[tuple[str, Node]]:
        if isinstance(node, SequenceNode):
            for i, step in enumerate(node.steps):
                yield from steps(step, f"{path}.steps[{i}]")
        else:
            yield path, node

    def visit(node: Node, path: str) -> None:
        previous: PortProducer | None = None
        for step_path, step in steps(node, path):
            match step:
                case AgentNode() | ToolNode():
                    if step.reads:
                        read = writers.get(step.id, {})
                        source = read.get(step.reads[0]) if len(step.reads) == 1 else None
                        if isinstance(source, AgentNode | ToolNode) or (
                            isinstance(source, ReduceNode) and source.merges
                        ):
                            edges.append((source, step, step_path))
                    elif previous is not None:
                        edges.append((previous, step, step_path))
                    previous = step
                case GateNode():
                    if step.select is not None:
                        previous = None  # it passes on the chosen items, not its input (6.7)
                case LoopNode() | MapNode() | OrchestratorNode():
                    previous = None
                    visit(step.body, f"{step_path}.body")
                case ParallelNode():
                    previous = None
                    for i, branch in enumerate(step.branches):
                        visit(branch, f"{step_path}.branches[{i}]")
                case RouterNode():
                    previous = None
                    for _, route_path, route in router_routes(step, step_path):
                        visit(route, route_path)
                case ReduceNode():
                    previous = step if step.merges else None
                case SubflowNode():
                    if previous is not None and step.input_schema is not None:
                        edges.append((previous, step, step_path))
                    previous = step if step.output_schema is not None else None
                    if step.call is not None:
                        visit(step.call, f"{step_path}.call")
                case SequenceNode():
                    previous = None

    visit(root, "root")
    return edges


def merge_sources(root: Node) -> list[tuple[ReduceNode, PortNode, str]]:
    """Each node whose output a `dedupe` or `vote` reduce under `root` merges, as
    `(reduce, source, source's path)`: the last step of a map's body or of each parallel branch
    (gates looked through), when it is an agent or tool node."""
    containers: dict[str, tuple[str, MapNode | ParallelNode | OrchestratorNode]] = {}
    found: list[tuple[ReduceNode, PortNode, str]] = []
    for path, node in iter_nodes(root):
        match node:
            case MapNode() | ParallelNode() | OrchestratorNode():
                containers[node.id] = (path, node)
            case ReduceNode() if node.merges and node.from_ in containers:
                at, source = containers[node.from_]
                if isinstance(source, MapNode | OrchestratorNode):
                    outputs = [(f"{at}.body", source.body)]
                else:
                    outputs = [(f"{at}.branches[{i}]", b) for i, b in enumerate(source.branches)]
                for out_path, out in outputs:
                    if last := _last_step(out, out_path):
                        found.append((node, last[1], last[0]))
            case _:
                pass
    return found


def _last_step(node: Node, path: str) -> tuple[str, PortNode] | None:
    """The agent or tool node whose output is `node`'s output, if there is one."""
    match node:
        case AgentNode() | ToolNode():
            return path, node
        case SequenceNode():
            for i in reversed(range(len(node.steps))):
                if not isinstance(node.steps[i], GateNode):
                    return _last_step(node.steps[i], f"{path}.steps[{i}]")
            return None
        case _:
            return None


def port_issues(root: Node) -> list[ValidationIssue]:
    """Why the typed ports under `root` cannot work, in run order: a schema that is not a port's
    schema (`invalid_schema`, on the field), and a consumer whose `input_schema` requires what the
    previous step's `output_schema` does not give (`port_mismatch`, on the consumer). The second
    check is light: required properties must be declared, with the same top-level type."""
    issues: list[ValidationIssue] = []
    broken: set[str] = set()
    for path, node in iter_nodes(root):
        if not isinstance(node, AgentNode | ToolNode):
            continue
        for side, schema in (("input", node.input_schema), ("output", node.output_schema)):
            if schema is None or (problem := schema_problem(schema)) is None:
                continue
            broken.add(node.id)
            issues.append(
                ValidationIssue(
                    code="invalid_schema",
                    path=f"{path}.{side}_schema",
                    node_id=node.id,
                    message=f"{node.type} {node.id!r} at {path}: {side}_schema: {problem}",
                )
            )
    for producer, consumer, path in port_edges(root):
        out, wanted = output_schema(producer), consumer.input_schema
        if out is None or wanted is None or {producer.id, consumer.id} & broken:
            continue
        if why := _port_mismatch(out, wanted, producer.id):
            message = f"{consumer.type} {consumer.id!r} at {path}: input_schema {why}"
            issues.append(
                ValidationIssue(
                    code="port_mismatch", path=path, node_id=consumer.id, message=message
                )
            )
    for reduce, source, path in merge_sources(root):
        if source.output_schema is None or source.id in broken:
            continue
        findings = _properties(source.output_schema).get("findings")
        if findings is None or (_types(findings) and "array" not in _types(findings)):
            message = (
                f"{source.type} {source.id!r} at {path}: reduce {reduce.id!r} merges its output "
                "as a findings report, but its output_schema has no `findings` array"
            )
            issues.append(
                ValidationIssue(code="port_mismatch", path=path, node_id=source.id, message=message)
            )
    return in_run_order(root, issues)


def _port_mismatch(
    out: dict[str, JsonValue], wanted: dict[str, JsonValue], producer: str
) -> str | None:
    given = _properties(out)
    expected = _properties(wanted)
    required = wanted.get("required")
    for name in required if isinstance(required, list) else []:
        if not isinstance(name, str):
            continue
        if name not in given:
            return f"requires {name!r}, which the output_schema of {producer!r} does not declare"
        has, needs = _types(given[name]), _types(expected.get(name))
        if "number" in needs:
            needs.add("integer")
        if has and needs and not has & needs:
            return (
                f"wants {name!r} as {' or '.join(sorted(needs))}, but the output_schema of "
                f"{producer!r} gives {' or '.join(sorted(has))}"
            )
    return None


def _properties(schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    properties = schema.get("properties")
    return properties if isinstance(properties, dict) else {}


def _types(schema: JsonValue) -> set[str]:
    """A property schema's top-level `type`s; empty when it does not say."""
    if not isinstance(schema, dict):
        return set()
    match schema.get("type"):
        case str() as one:
            return {one}
        case list() as many:
            return {t for t in many if isinstance(t, str)}
        case _:
            return set()


def structure_issues(root: Node) -> list[ValidationIssue]:
    """Why the spec under `root` cannot run anywhere, in run order: duplicate node ids, the loop,
    map, parallel and router rules, references to other nodes, a gate before every publisher, the
    rules for creating the repo, typed ports and run artifacts."""
    issues = duplicate_id_issues(root) + loop_issues(root) + map_issues(root)
    issues += parallel_issues(root) + router_issues(root) + orchestrator_issues(root)
    issues += publish_gate_issues(root) + create_repo_issues(root)
    issues += port_issues(root) + artifact_issues(root) + subflow_issues(root)
    issues += gate_issues(root)
    return in_run_order(root, issues)


def gate_issues(root: Node) -> list[ValidationIssue]:
    """Why the gates under `root` cannot run (6.7): a `select.preselect` that is not a valid
    condition over `item` (`invalid_expression`), and `on_reject: end` on a gate that is not a
    step of the root sequence (`invalid_gate`): only there does ending skip to the run's end."""
    top = {id(step) for step in root.steps} if isinstance(root, SequenceNode) else {id(root)}
    issues: list[ValidationIssue] = []
    for path, node in iter_nodes(root):
        if not isinstance(node, GateNode):
            continue
        if node.select is not None and node.select.preselect is not None:
            try:
                compile_item_condition(node.select.preselect)
            except ExpressionError as e:
                message = f"gate {node.id!r} at {path}: invalid select.preselect: {e}"
                issues.append(
                    ValidationIssue(
                        code="invalid_expression",
                        path=f"{path}.select.preselect",
                        node_id=node.id,
                        message=message,
                    )
                )
        if node.on_reject == "end" and id(node) not in top:
            message = (
                f'gate {node.id!r} at {path}: on_reject "end" needs the gate to be a step of '
                'the root sequence; use "cancel" here'
            )
            issues.append(
                ValidationIssue(
                    code="invalid_gate", path=f"{path}.on_reject", node_id=node.id, message=message
                )
            )
    return issues


def subflow_issues(root: Node) -> list[ValidationIssue]:
    """Why the subflows under `root` cannot run, in run order, as far as their own fields say: an
    `input` that is not a valid expression (`invalid_expression`, on the `input`). What they call
    is checked once resolved (`expand_workflow`)."""
    issues: list[ValidationIssue] = []
    for path, node in iter_nodes(root):
        if not isinstance(node, SubflowNode) or node.input is None:
            continue
        try:
            compile_value(node.input)
        except ExpressionError as e:
            message = f"subflow {node.id!r} at {path}: invalid input: {e}"
            issues.append(
                ValidationIssue(
                    code="invalid_expression",
                    path=f"{path}.input",
                    node_id=node.id,
                    message=message,
                )
            )
    return issues


def in_run_order(root: Node, issues: list[ValidationIssue]) -> list[ValidationIssue]:
    """`issues` sorted by where their node runs under `root` (depth first); an issue on a node's
    field (`root.steps[1].output_schema`) sorts with its node. The sort is stable, and issues on
    no node come first."""
    order = {path: i for i, (path, _) in enumerate(iter_nodes(root))}

    def key(issue: ValidationIssue) -> int:
        return order.get(issue.path, order.get(issue.path.rpartition(".")[0], -1))

    return sorted(issues, key=key)


def writer_node_ids(root: Node, write_tools: Collection[str] = WRITE_TOOLS) -> set[str]:
    """The ids of the nodes under `root` that may call one of `write_tools` (each gets its own
    worktree and branch), but those in an orchestrator's body: they write per task
    (`task_writer_orchestrators`)."""
    tasked = task_node_ids(root)
    return {
        node.id
        for _, node in iter_nodes(root)
        if node.id not in tasked and any(tool in write_tools for tool in node_tools(node))
    }


def task_writer_orchestrators(root: Node, write_tools: Collection[str] = WRITE_TOOLS) -> set[str]:
    """The ids of the orchestrators under `root` whose body holds a node that may call one of
    `write_tools`: each task's writer gets its own worktree and branch, named by
    `task_writer_key`, made on its first call."""
    return {
        node.id
        for _, node in iter_nodes(root)
        if isinstance(node, OrchestratorNode)
        and any(set(write_tools) & set(node_tools(inner)) for _, inner in iter_nodes(node.body))
    }


class WorkflowInput(_Base):
    """What a run of the workflow is given to work on: the first step's input. A workflow that
    needs it (a change to make, a question to answer) says so with `required`, and `label`,
    `description` and `example` tell the person starting a run what to write."""

    required: bool = Field(default=False, description="A run cannot start with an empty input.")
    label: str = Field(
        min_length=1,
        max_length=80,
        description='What the input is, as a field label, e.g. "What should the team change?".',
    )
    description: str | None = Field(
        default=None, max_length=300, description="One more sentence of help under the field."
    )
    example: str | None = Field(
        default=None, max_length=300, description="An example input, shown in the empty field."
    )


class WorkflowSpec(_Base):
    """A versioned workflow document with a single root node."""

    spec_version: Literal["0"]
    id: NodeId
    name: NonEmptyStr
    description: str | None = None
    budget_usd: float | None = Field(
        default=None,
        ge=BUDGET_MIN_USD,
        le=BUDGET_MAX_USD,
        description="USD a run of this workflow may spend, a hard stop once reached. A run's own "
        "budget replaces it; unset, the workspace's default applies (or none).",
    )
    input: WorkflowInput | None = Field(
        default=None,
        description="What a run is given to work on, and whether it must be given; unset, the "
        "input is optional.",
    )
    input_schema: PortSchema | None = Field(
        default=None,
        description="The workflow's typed input (6.6): a subflow that calls it checks its input "
        "against this, and the step before it must declare what it requires.",
    )
    output_schema: PortSchema | None = Field(
        default=None,
        description="The workflow's typed output (6.6): a subflow that calls it checks the called "
        "workflow's output against this, and the step after it reads it as typed.",
    )
    root: Node

    @model_validator(mode="after")
    def _can_run(self) -> Self:
        # A spec that calls other workflows (6.5) is checked once they are resolved, on the
        # expanded tree (`expand_workflow`): what it reads or publishes may come from them.
        if any(isinstance(node, SubflowNode) for _, node in iter_nodes(self.root)):
            return self
        if issues := structure_issues(self.root):
            raise ValueError("; ".join(messages(issues)))
        return self
