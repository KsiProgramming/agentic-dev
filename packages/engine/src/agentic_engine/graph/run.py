"""Runs a workflow spec end to end on an `AgentRuntime`."""

import asyncio
from typing import Literal
from uuid import UUID, uuid4

from pydantic import JsonValue

from agentic_engine.agent import sum_usage
from agentic_engine.events import (
    RUN_CANCELLED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_STARTED,
    EventSink,
    NullEventSink,
    RunEventLog,
)
from agentic_engine.graph.compile import compile_workflow
from agentic_engine.graph.state import WorkflowRunResult, initial_state
from agentic_engine.spec import WorkflowSpec
from agentic_runtime import AgentRuntime

RUN_END = {"completed": RUN_COMPLETED, "failed": RUN_FAILED, "cancelled": RUN_CANCELLED}


async def run_workflow(
    spec: WorkflowSpec,
    runtime: AgentRuntime,
    input: str = "",
    *,
    run_id: UUID | None = None,
    sink: EventSink | None = None,
) -> WorkflowRunResult:
    """Compile `spec`, run it with `input` for the first node, and summarise the outcome.

    A node that fails or is cancelled stops the run; its status becomes the run's status. If the
    caller is cancelled, the in-flight agent run is cancelled and `CancelledError` propagates.

    Every step is written to `sink` in order: `run_started`, then per node `node_started`, its
    agent events and `node_<status>`, then `run_<status>`. An exception from the graph is logged
    as `run_failed` and re-raised.
    """
    log = RunEventLog(run_id or uuid4(), sink or NullEventSink())
    await _start(log, spec, input)
    try:
        final = await compile_workflow(spec, runtime, log).ainvoke(initial_state(input))
    except asyncio.CancelledError:
        await log.emit(RUN_CANCELLED, payload={"reason": "caller cancelled"})
        raise
    except Exception as exc:
        await log.emit(RUN_FAILED, payload={"error": f"{type(exc).__name__}: {exc}"})
        raise

    order = final["order"]
    results = {node_id: final["results"][node_id] for node_id in order}
    stopped_at = next((i for i in order if results[i].status != "completed"), None)
    status = results[stopped_at].status if stopped_at else "completed"
    end: dict[str, JsonValue] = {"stopped_at": stopped_at} if stopped_at else {}
    await log.emit(RUN_END[status], payload=end)
    return WorkflowRunResult(
        run_id=log.run_id,
        status=status,
        text=final["last_text"],
        order=order,
        results=results,
        usage=sum_usage(r.usage for r in results.values()),
        stopped_at=stopped_at,
    )


async def record_unstarted_run(
    spec: WorkflowSpec,
    input: str,
    *,
    run_id: UUID,
    sink: EventSink,
    status: Literal["failed", "cancelled"],
    reason: str,
) -> None:
    """Log a run that ended before its first node, e.g. because its sandbox could not be created:
    `run_started`, then `run_failed` (payload `error`) or `run_cancelled` (payload `reason`)."""
    log = RunEventLog(run_id, sink)
    await _start(log, spec, input)
    key = "error" if status == "failed" else "reason"
    await log.emit(RUN_END[status], payload={key: reason})


async def _start(log: RunEventLog, spec: WorkflowSpec, input: str) -> None:
    await log.emit(
        RUN_STARTED, payload={"workflow_id": spec.id, "workflow_name": spec.name, "input": input}
    )
