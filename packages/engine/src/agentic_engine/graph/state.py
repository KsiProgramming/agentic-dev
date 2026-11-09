"""The LangGraph state of a workflow run, and the summary `run_workflow` returns."""

import operator
from typing import Annotated, Literal, NotRequired, TypedDict
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from agentic_engine.agent import AgentNodeResult, AgentNodeStatus
from agentic_engine.artifacts import ArtifactRef
from agentic_runtime import Usage


def merge_results(
    left: dict[str, AgentNodeResult], right: dict[str, AgentNodeResult]
) -> dict[str, AgentNodeResult]:
    """Reducer for `RunState.results`: a node's update adds its result by node id."""
    return {**left, **right}


def merge_counts(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    """Reducer for `RunState.iterations`: a loop's update sets its count by loop id."""
    return {**left, **right}


def merge_map_results(
    left: dict[str, dict[str, AgentNodeResult]], right: dict[str, dict[str, AgentNodeResult]]
) -> dict[str, dict[str, AgentNodeResult]]:
    """Reducer for `RunState.map_results` and `RunState.parallel_results`: an item's (a
    branch's) update adds its result by map (parallel) id, then by item index (branch id), so a
    map's items and a parallel's branches can finish in any order and at the same time."""
    merged = dict(left)
    for map_id, items in right.items():
        merged[map_id] = {**merged.get(map_id, {}), **items}
    return merged


def merge_artifacts(
    left: dict[str, ArtifactRef], right: dict[str, ArtifactRef]
) -> dict[str, ArtifactRef]:
    """Reducer for `RunState.artifacts`: a write replaces the name's ref with its new version."""
    return {**left, **right}


def merge_routes(
    left: dict[str, str | None], right: dict[str, str | None]
) -> dict[str, str | None]:
    """Reducer for `RunState.routes`: a router's choice replaces its last one (a loop's)."""
    return {**left, **right}


def merge_plans(
    left: dict[str, list[JsonValue]], right: dict[str, list[JsonValue]]
) -> dict[str, list[JsonValue]]:
    """Reducer for `RunState.plans`: an orchestrator's plan, by its id."""
    return {**left, **right}


class RunState(TypedDict):
    """What flows through the compiled graph.

    `last_text` starts as the run input and is replaced by each node's output, which the next
    node receives as its `AgentRequest.input` (data, never instructions).

    `results` holds each node's latest result; `order` lists every node run, so a node inside a
    loop appears once per iteration. `iterations` counts each loop's started iterations, and
    `usage` collects the usage of every node run, which `results` alone would undercount.

    `spawned` counts the agents the run has started, for its `agents_spawned` limit: one per
    agent node run (a loop's once per iteration), and a map's items' agents all at once when the
    map starts. Checkpoints saved before phase 3.2 have none, which counts as 0.

    `map_results` holds, per map, the result of its body for each item, keyed by the item's index
    as a string (checkpoints keep string keys). The nodes inside a map body are not in `results`
    or `order`: their ids repeat for every item.

    `parallel_results` holds, per parallel, the outcome of each branch, keyed by the branch's id.
    The nodes inside a branch are in `results` too, as their ids do not repeat, but not in
    `order`: a branch can fail while its parallel completes, and `order` is the run's path.
    Checkpoints saved before phase 4.1 have none, which counts as empty.

    `artifacts` holds the latest version the run wrote of each run artifact, by name (4.3); the
    content is in the run's `ArtifactStore`. Checkpoints saved before phase 4.3 have none, which
    counts as empty.

    `routes` holds the route each router chose, by router id (`None` if it could not choose), so
    a resumed run goes on in that route. Checkpoints saved before phase 4.6 have none.

    `plans` holds the tasks each orchestrator's hub planned (6.1), by orchestrator id, so a
    resumed run runs the same tasks and never asks the hub again. Its workers' results are in
    `map_results`, under the orchestrator's id, by task index. Checkpoints saved before phase 6.1
    have none.

    `rounds` counts the plans each orchestrator's hub made (6.2: one more per replan), by
    orchestrator id; a replan that planned no task still counts. Checkpoints saved before phase
    6.2 have none, which counts as one plan.
    """

    input: str
    last_text: str
    results: Annotated[dict[str, AgentNodeResult], merge_results]
    order: Annotated[list[str], operator.add]
    iterations: Annotated[dict[str, int], merge_counts]
    usage: Annotated[list[Usage], operator.add]
    map_results: Annotated[dict[str, dict[str, AgentNodeResult]], merge_map_results]
    spawned: Annotated[int, operator.add]
    parallel_results: Annotated[dict[str, dict[str, AgentNodeResult]], merge_map_results]
    artifacts: Annotated[dict[str, ArtifactRef], merge_artifacts]
    routes: Annotated[dict[str, str | None], merge_routes]
    plans: Annotated[dict[str, list[JsonValue]], merge_plans]
    rounds: Annotated[dict[str, int], merge_counts]


class RunUpdate(TypedDict, total=False):
    """A node's partial update to `RunState`."""

    last_text: str
    results: dict[str, AgentNodeResult]
    order: list[str]
    iterations: dict[str, int]
    usage: list[Usage]
    map_results: dict[str, dict[str, AgentNodeResult]]
    spawned: int
    parallel_results: dict[str, dict[str, AgentNodeResult]]
    artifacts: dict[str, ArtifactRef]
    routes: dict[str, str | None]
    plans: dict[str, list[JsonValue]]
    rounds: dict[str, int]


class MapItem(TypedDict):
    """What a map sends the worker that runs its body for one item, with the run's artifacts when
    the map started (`item_artifacts`; sends from before 4.3 have none)."""

    index: int
    item: JsonValue
    item_input: str
    item_artifacts: NotRequired[dict[str, ArtifactRef]]


class ParallelBranch(TypedDict):
    """What a parallel sends the worker that runs one of its branches: the branch's index, the
    parallel's input (`input` would clash with `RunState.input`) and the run's artifacts when the
    parallel started (sends from before 4.3 have none)."""

    index: int
    branch_input: str
    branch_artifacts: NotRequired[dict[str, ArtifactRef]]


class OrchestratorTask(TypedDict):
    """What an orchestrator sends the worker that runs its body for one planned task: the task's
    index in the plan, the task (`id`, `title`, `instructions`), the body's input (`{"task",
    "input"}` as JSON) and the run's artifacts when the orchestrator started."""

    index: int
    task: JsonValue
    task_input: str
    task_artifacts: dict[str, ArtifactRef]


def initial_state(input: str) -> RunState:
    return RunState(
        input=input,
        last_text=input,
        results={},
        order=[],
        iterations={},
        usage=[],
        map_results={},
        spawned=0,
        parallel_results={},
        artifacts={},
        routes={},
        plans={},
        rounds={},
    )


type WorkflowRunStatus = AgentNodeStatus | Literal["waiting", "suspended"]


class WorkflowRunResult(BaseModel):
    """The outcome of a run, or of one stretch of it. `stopped_at` names the node that did not
    complete, if any; a `waiting` run is paused at the gate `waiting_at` until it is continued
    with a decision. A `suspended` run stopped after creating its repo, at `waiting_at` (the
    node `repo_ready_node_id` names), and goes on in a new attempt, with no decision."""

    model_config = ConfigDict(frozen=True)

    run_id: UUID
    status: WorkflowRunStatus
    text: str
    order: list[str]
    results: dict[str, AgentNodeResult]
    usage: Usage | None
    stopped_at: str | None = None
    waiting_at: str | None = None
    artifacts: dict[str, ArtifactRef] = Field(default_factory=dict[str, ArtifactRef])
