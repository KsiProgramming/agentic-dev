"""The LangGraph state of a workflow run, and the summary `run_workflow` returns."""

import operator
from typing import Annotated, Literal, TypedDict
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue

from agentic_engine.agent import AgentNodeResult, AgentNodeStatus
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
    """Reducer for `RunState.map_results`: an item's update adds its result by map id, then by
    item index, so a map's items can finish in any order and at the same time."""
    merged = dict(left)
    for map_id, items in right.items():
        merged[map_id] = {**merged.get(map_id, {}), **items}
    return merged


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
    """

    input: str
    last_text: str
    results: Annotated[dict[str, AgentNodeResult], merge_results]
    order: Annotated[list[str], operator.add]
    iterations: Annotated[dict[str, int], merge_counts]
    usage: Annotated[list[Usage], operator.add]
    map_results: Annotated[dict[str, dict[str, AgentNodeResult]], merge_map_results]
    spawned: Annotated[int, operator.add]


class RunUpdate(TypedDict, total=False):
    """A node's partial update to `RunState`."""

    last_text: str
    results: dict[str, AgentNodeResult]
    order: list[str]
    iterations: dict[str, int]
    usage: list[Usage]
    map_results: dict[str, dict[str, AgentNodeResult]]
    spawned: int


class MapItem(TypedDict):
    """What a map sends the worker that runs its body for one item."""

    index: int
    item: JsonValue
    item_input: str


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
