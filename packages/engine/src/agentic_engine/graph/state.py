"""The LangGraph state of a workflow run, and the summary `run_workflow` returns."""

import operator
from typing import Annotated, TypedDict
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from agentic_engine.agent import AgentNodeResult, AgentNodeStatus
from agentic_runtime import Usage


def merge_results(
    left: dict[str, AgentNodeResult], right: dict[str, AgentNodeResult]
) -> dict[str, AgentNodeResult]:
    """Reducer for `RunState.results`: a node's update adds its result by node id."""
    return {**left, **right}


class RunState(TypedDict):
    """What flows through the compiled graph.

    `last_text` starts as the run input and is replaced by each node's output, which the next
    node receives as its `AgentRequest.input` (data, never instructions).
    """

    input: str
    last_text: str
    results: Annotated[dict[str, AgentNodeResult], merge_results]
    order: Annotated[list[str], operator.add]


class RunUpdate(TypedDict, total=False):
    """A node's partial update to `RunState`."""

    last_text: str
    results: dict[str, AgentNodeResult]
    order: list[str]


def initial_state(input: str) -> RunState:
    return RunState(input=input, last_text=input, results={}, order=[])


class WorkflowRunResult(BaseModel):
    """The outcome of a run. `stopped_at` names the node that did not complete, if any."""

    model_config = ConfigDict(frozen=True)

    run_id: UUID
    status: AgentNodeStatus
    text: str
    order: list[str]
    results: dict[str, AgentNodeResult]
    usage: Usage | None
    stopped_at: str | None = None
