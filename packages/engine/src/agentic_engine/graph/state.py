"""The LangGraph state of a workflow run, and the summary `run_workflow` returns."""

import operator
from typing import Annotated, Literal, TypedDict
from uuid import UUID

from pydantic import BaseModel, ConfigDict

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


class RunState(TypedDict):
    """What flows through the compiled graph.

    `last_text` starts as the run input and is replaced by each node's output, which the next
    node receives as its `AgentRequest.input` (data, never instructions).

    `results` holds each node's latest result; `order` lists every node run, so a node inside a
    loop appears once per iteration. `iterations` counts each loop's started iterations, and
    `usage` collects the usage of every node run, which `results` alone would undercount.
    """

    input: str
    last_text: str
    results: Annotated[dict[str, AgentNodeResult], merge_results]
    order: Annotated[list[str], operator.add]
    iterations: Annotated[dict[str, int], merge_counts]
    usage: Annotated[list[Usage], operator.add]


class RunUpdate(TypedDict, total=False):
    """A node's partial update to `RunState`."""

    last_text: str
    results: dict[str, AgentNodeResult]
    order: list[str]
    iterations: dict[str, int]
    usage: list[Usage]


def initial_state(input: str) -> RunState:
    return RunState(input=input, last_text=input, results={}, order=[], iterations={}, usage=[])


type WorkflowRunStatus = AgentNodeStatus | Literal["waiting"]


class WorkflowRunResult(BaseModel):
    """The outcome of a run, or of one stretch of it. `stopped_at` names the node that did not
    complete, if any; a `waiting` run is paused at the gate `waiting_at` until it is continued
    with a decision."""

    model_config = ConfigDict(frozen=True)

    run_id: UUID
    status: WorkflowRunStatus
    text: str
    order: list[str]
    results: dict[str, AgentNodeResult]
    usage: Usage | None
    stopped_at: str | None = None
    waiting_at: str | None = None
