"""Rerun from a step (12.4): a new run that starts from another run's checkpoint taken before one
of its top-level steps, so the steps before it are neither run nor charged again.

A run's top-level steps are the steps of its root sequence (nested sequences flattened), or the
root itself when it is not a sequence; a container (loop, map, parallel, orchestrator, router,
subflow) is one step and runs whole again. Each branch version a run saves records the top-level
step it was saved in (`BranchSaver.save(step=...)`), so the code as it was before a step is the
latest version of each branch saved in the steps before it.

The new run has its own LangGraph thread (its run id), seeded with a copy of the original's
latest checkpoint whose next node is the step (`seed_rerun`). Pending writes are not copied, so
the step runs whole. What the copy must not carry over is reset: the usage and the agents
spawned (the new run is charged and limited for its own work only), and the original's run id in
its integration branches' names is replaced by the new run's.
"""

import copy
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import Checkpoint, CheckpointMetadata

from agentic_engine.graph.checkpoint import Checkpointer, thread_config
from agentic_engine.graph.compile import CompiledWorkflow
from agentic_engine.graph.steps import StepNotFoundError, steps_before, top_level_steps, top_step_of
from agentic_engine.spec import WorkflowSpec

__all__ = [
    "StepNotFoundError",
    "StepNotReachedError",
    "carried_state",
    "checkpoint_before",
    "seed_rerun",
    "steps_before",
    "top_level_steps",
    "top_step_of",
]


class StepNotReachedError(ValueError):
    """The original run never reached the step, so there is no checkpoint to start from."""


async def checkpoint_before(
    graph: CompiledWorkflow, checkpointer: Checkpointer, run_id: UUID, node_id: str
) -> tuple[Checkpoint, CheckpointMetadata] | None:
    """The original run's latest checkpoint whose next node is the top-level step `node_id`,
    with its metadata, or `None` for the first step (a rerun from it starts from the run's input
    with no checkpoint). Raises `StepNotReachedError` if the run never got there."""
    history = [s async for s in graph.aget_state_history(thread_config(run_id))]
    if not history:
        raise StepNotReachedError(f"run {run_id} has no checkpoint")
    for snapshot in history:  # newest first
        if node_id in snapshot.next:
            if not snapshot.values.get("order") and not snapshot.values.get("results"):
                return None  # nothing ran before it
            found = await checkpointer.aget_tuple(snapshot.config)
            assert found is not None, "a listed checkpoint can be read"
            return found.checkpoint, found.metadata
    raise StepNotReachedError(f"run {run_id} never reached step {node_id!r}")


def carried_state(checkpoint: Checkpoint, source_run: UUID, target_run: UUID) -> Checkpoint:
    """A copy of `checkpoint` for the new run: its usage and agents spawned reset, and the
    original's run id in branch names replaced by the new run's."""
    copied = copy.deepcopy(checkpoint)
    values: dict[str, Any] = copied["channel_values"]
    if "usage" in values:
        values["usage"] = []
    if "spawned" in values:
        values["spawned"] = 0
    if "integrated" in values:
        values["integrated"] = {
            key: _renamed(entry, source_run, target_run)
            for key, entry in values["integrated"].items()
        }
    return copied


def _renamed(entry: Mapping[str, Any], source: UUID, target: UUID) -> dict[str, Any]:
    branch = entry.get("branch")
    if isinstance(branch, str):
        return {**entry, "branch": branch.replace(f"/{source}/", f"/{target}/")}
    return dict(entry)


async def seed_rerun(
    spec: WorkflowSpec,
    graph: CompiledWorkflow,
    checkpointer: Checkpointer,
    *,
    source_run: UUID,
    target_run: UUID,
    node_id: str,
) -> dict[str, Any] | None:
    """Seed `target_run`'s thread with `source_run`'s checkpoint before the top-level step
    `node_id` of `spec`, and return the state it carries (its channel values), or `None` when
    there is nothing to carry (the first step) or the thread already has a checkpoint (an earlier
    attempt seeded it). `graph` is the target run's compiled graph, whose structure is the
    original's (a rerun edits parameters only). Raises `StepNotFoundError` or
    `StepNotReachedError`."""
    if not steps_before(spec, node_id):
        return None
    if await checkpointer.aget_tuple(thread_config(target_run)) is not None:
        return None
    found = await checkpoint_before(graph, checkpointer, source_run, node_id)
    if found is None:
        return None
    checkpoint, metadata = found
    carried = carried_state(checkpoint, source_run, target_run)
    config: RunnableConfig = {"configurable": {"thread_id": str(target_run), "checkpoint_ns": ""}}
    forked: CheckpointMetadata = {**metadata, "source": "fork"}
    await checkpointer.aput(config, carried, forked, dict(carried["channel_versions"]))
    return carried["channel_values"]
