"""Runs a workflow spec end to end on an `AgentRuntime`, and resumes one that was cut off or
paused at a gate."""

import asyncio
from collections.abc import Callable
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from pydantic import JsonValue

from agentic_engine.agent import sum_usage
from agentic_engine.events import (
    GATE_WAITING,
    NODE_STARTED,
    RUN_CANCELLED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_RESUMED,
    RUN_STARTED,
    EventSink,
    NullEventSink,
    RunEventLog,
)
from agentic_engine.gate import GateDecision
from agentic_engine.graph.checkpoint import Checkpointer, thread_config
from agentic_engine.graph.compile import CompiledWorkflow, compile_workflow
from agentic_engine.graph.state import (
    RunState,
    WorkflowRunResult,
    WorkflowRunStatus,
    initial_state,
)
from agentic_engine.spec import WorkflowSpec
from agentic_runtime import AgentRuntime, ToolExecutor

RUN_END = {"completed": RUN_COMPLETED, "failed": RUN_FAILED, "cancelled": RUN_CANCELLED}


async def run_workflow(
    spec: WorkflowSpec,
    runtime: AgentRuntime,
    input: str = "",
    *,
    run_id: UUID | None = None,
    sink: EventSink | None = None,
    checkpointer: Checkpointer | None = None,
    tools: ToolExecutor | None = None,
) -> WorkflowRunResult:
    """Compile `spec`, run it with `input` for the first node, and summarise the outcome.

    A node that fails or is cancelled stops the run; its status becomes the run's status. If the
    caller is cancelled, the in-flight agent run is cancelled and `CancelledError` propagates.
    A gate pauses the run: it ends `waiting`, after `node_started` and `gate_waiting` (payload
    `title`, `prompt`, `artifact`) for the gate, and `resume_workflow` continues it with the
    decision.

    Every step is written to `sink` in order: `run_started`, then per node `node_started`, its
    agent events and `node_<status>`, then `run_<status>`. An exception from the graph is logged
    as `run_failed` and re-raised.

    With `checkpointer`, the state is saved after each node in the thread of `run_id`, so
    `resume_workflow` can carry on after the last completed node.

    `tool` nodes call `tools`: give it the executor the runtime's agents use, so both reach the
    same per-run tools. A spec with a gate needs `checkpointer`.
    """
    log = RunEventLog(run_id or uuid4(), sink or NullEventSink())
    await _start(log, spec, input)
    return await _finish(
        log,
        lambda: compile_workflow(spec, runtime, log, checkpointer, tools),
        initial_state(input),
        thread_config(log.run_id),
    )


async def resume_workflow(
    spec: WorkflowSpec,
    runtime: AgentRuntime,
    input: str = "",
    *,
    run_id: UUID,
    sink: EventSink,
    checkpointer: Checkpointer,
    next_seq: int,
    attempt: int,
    tools: ToolExecutor | None = None,
    decision: GateDecision | None = None,
) -> WorkflowRunResult:
    """Carry on a run that an earlier attempt started, from its last checkpoint.

    Nodes that completed before are not run again; a node that was cut off runs again from its
    start. Writes `run_resumed` (payload `attempt`, `completed_nodes`) at `next_seq`, then the
    same events as `run_workflow`. A run with no checkpoint yet starts again from `input`, and
    one whose graph had already ended just reports its outcome.

    A run paused at a gate continues with `decision`: the gate logs `gate_decided`, then approve
    goes on to the next node and reject ends the run `cancelled`. Without a decision the run
    pauses at the gate again, and the pause is announced again.
    """
    log = RunEventLog(run_id, sink, next_seq=next_seq)
    graph = compile_workflow(spec, runtime, log, checkpointer, tools)
    config = thread_config(run_id)
    snapshot = await graph.aget_state(config)
    saved = snapshot.values
    results = saved.get("results", {})
    completed = [n for n in saved.get("order", []) if results[n].status == "completed"]
    await log.emit(RUN_RESUMED, payload={"attempt": attempt, "completed_nodes": completed})
    if not saved:
        return await _finish(log, lambda: graph, initial_state(input), config)
    if not snapshot.next:
        return await _report(log, RunState(**saved))
    paused = any(task.interrupts for task in snapshot.tasks)
    resume = decision.model_dump(mode="json") if paused and decision else None
    start: Command[Any] | None = Command(resume=resume) if resume is not None else None
    return await _finish(log, lambda: graph, start, config)


async def _finish(
    log: RunEventLog,
    build: Callable[[], CompiledWorkflow],
    start: RunState | Command[Any] | None,
    config: RunnableConfig,
) -> WorkflowRunResult:
    """Build the graph and invoke it from `start` (`None` continues from the checkpoint, a
    `Command` continues a paused gate), then report the end, or the pause at a gate. A failure
    to build is logged like one from the graph."""
    try:
        graph = build()
        final = await graph.ainvoke(start, config)
        paused = await _paused_gate(graph, config)
    except asyncio.CancelledError:
        await log.emit(RUN_CANCELLED, payload={"reason": "caller cancelled"})
        raise
    except Exception as exc:
        await log.emit(RUN_FAILED, payload={"error": f"{type(exc).__name__}: {exc}"})
        raise
    if paused is not None:
        return await _wait(log, *paused)
    return await _report(log, final)


async def _paused_gate(
    graph: CompiledWorkflow, config: RunnableConfig
) -> tuple[RunState, str, dict[str, JsonValue]] | None:
    """If the run stopped at a gate: its state, the gate's id and what the gate asks."""
    if graph.checkpointer is None:
        return None
    snapshot = await graph.aget_state(config)
    for task in snapshot.tasks:
        if task.interrupts:
            request = cast(dict[str, JsonValue], task.interrupts[0].value)
            return RunState(**snapshot.values), task.name, request
    return None


async def _wait(
    log: RunEventLog, state: RunState, gate_id: str, request: dict[str, JsonValue]
) -> WorkflowRunResult:
    await log.emit(NODE_STARTED, node_id=gate_id)
    await log.emit(GATE_WAITING, node_id=gate_id, payload=request)
    return _result(log, state, "waiting", waiting_at=gate_id)


async def _report(log: RunEventLog, final: RunState) -> WorkflowRunResult:
    order = final["order"]
    stopped_at = next((i for i in order if final["results"][i].status != "completed"), None)
    status = final["results"][stopped_at].status if stopped_at else "completed"
    end: dict[str, JsonValue] = {"stopped_at": stopped_at} if stopped_at else {}
    await log.emit(RUN_END[status], payload=end)
    return _result(log, final, status, stopped_at=stopped_at)


def _result(
    log: RunEventLog,
    state: RunState,
    status: WorkflowRunStatus,
    *,
    stopped_at: str | None = None,
    waiting_at: str | None = None,
) -> WorkflowRunResult:
    results = {node_id: state["results"][node_id] for node_id in state["order"]}
    return WorkflowRunResult(
        run_id=log.run_id,
        status=status,
        text=state["last_text"],
        order=state["order"],
        results=results,
        usage=sum_usage(r.usage for r in results.values()),
        stopped_at=stopped_at,
        waiting_at=waiting_at,
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
