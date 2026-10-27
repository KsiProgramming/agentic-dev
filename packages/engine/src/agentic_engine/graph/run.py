"""Runs a workflow spec end to end on an `AgentRuntime`, and resumes one that was cut off or
paused at a gate."""

import asyncio
from collections.abc import Callable
from decimal import Decimal
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from pydantic import JsonValue

from agentic_engine.agent import sum_usage
from agentic_engine.budget import BudgetMeter, budget_meter
from agentic_engine.events import (
    GATE_WAITING,
    NODE_STARTED,
    POLICY_LIMIT_EXCEEDED,
    RUN_CANCELLED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_RESUMED,
    RUN_STARTED,
    EventSink,
    NullEventSink,
    RunEventLog,
)
from agentic_engine.gate import FileChange, GateDecision, GateReview, GateReviewError
from agentic_engine.graph.checkpoint import Checkpointer, thread_config
from agentic_engine.graph.compile import (
    CompiledWorkflow,
    compile_workflow,
    is_repo_ready,
    recursion_limit,
)
from agentic_engine.graph.state import (
    RunState,
    WorkflowRunResult,
    WorkflowRunStatus,
    initial_state,
)
from agentic_engine.policy import PLATFORM_POLICY, Policy, PolicyLimitExceeded
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
    policy: Policy = PLATFORM_POLICY,
    spent: Decimal = Decimal(0),
    review: GateReview | None = None,
) -> WorkflowRunResult:
    """Compile `spec`, run it with `input` for the first node, and summarise the outcome.

    A node that fails or is cancelled stops the run; its status becomes the run's status. If the
    caller is cancelled, the in-flight agent run is cancelled and `CancelledError` propagates.
    A cancel whose message is a `PolicyLimitExceeded` (the worker's wall-time stop) ends the run
    `failed`: `policy_limit_exceeded`, then `run_failed` with the reason as `error`. The run's
    agents are held to `policy` (see `compile_workflow`). With a budget, the run has already
    spent `spent`; once its spend reaches the budget it ends `failed` the same way, and the
    result says so.
    A gate pauses the run: it ends `waiting`, after `node_started` and `gate_waiting` (payload
    `title`, `prompt`, `artifact`, `changes`) for the gate, and `resume_workflow` continues it
    with the decision. `changes` are the files the writers that ran before the gate changed, from
    `review` (none without one), and an approval's edits are committed through it.
    A run that created its repo ends the attempt `suspended`, with no event: `resume_workflow`
    continues it, in an attempt that has the repo cloned.

    Every step is written to `sink` in order: `run_started`, then per node `node_started`, its
    agent events and `node_<status>`, then `run_<status>`. An exception from the graph is logged
    as `run_failed` and re-raised.

    With `checkpointer`, the state is saved after each node in the thread of `run_id`, so
    `resume_workflow` can carry on after the last completed node.

    `tool` nodes call `tools`: give it the executor the runtime's agents use, so both reach the
    same per-run tools. A spec with a gate needs `checkpointer`.
    """
    log = RunEventLog(run_id or uuid4(), sink or NullEventSink())
    budget = budget_meter(policy, spent)
    await _start(log, spec, input)
    return await _finish(
        log,
        lambda: compile_workflow(spec, runtime, log, checkpointer, tools, policy, budget, review),
        initial_state(input),
        _config(spec, log.run_id),
        budget,
        review,
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
    policy: Policy = PLATFORM_POLICY,
    spent: Decimal = Decimal(0),
    review: GateReview | None = None,
) -> WorkflowRunResult:
    """Carry on a run that an earlier attempt started, from its last checkpoint.

    Nodes that completed before are not run again; a node that was cut off runs again from its
    start. Writes `run_resumed` (payload `attempt`, `completed_nodes`) at `next_seq`, then the
    same events as `run_workflow`. A run with no checkpoint yet starts again from `input`, and
    one whose graph had already ended just reports its outcome.

    A run paused at a gate continues with `decision`: the gate logs `gate_decided`, then approve
    goes on to the next node and reject ends the run `cancelled`. Without a decision the run
    pauses at the gate again, and the pause is announced again. A `suspended` run (it created its
    repo) just goes on.

    `spent` is what the run's earlier attempts spent: a run that has already spent its budget
    stops before it runs another node.
    """
    log = RunEventLog(run_id, sink, next_seq=next_seq)
    budget = budget_meter(policy, spent)
    graph = compile_workflow(spec, runtime, log, checkpointer, tools, policy, budget, review)
    config = _config(spec, run_id)
    snapshot = await graph.aget_state(config)
    saved = snapshot.values
    results = saved.get("results", {})
    ran = dict.fromkeys(saved.get("order", []))  # a node in a loop runs once per iteration
    completed = [n for n in ran if results[n].status == "completed"]
    await log.emit(RUN_RESUMED, payload={"attempt": attempt, "completed_nodes": completed})
    if not saved:
        return await _finish(log, lambda: graph, initial_state(input), config, budget, review)
    if not snapshot.next:
        return await _report(log, RunState(**saved))
    asks = [i.value for task in snapshot.tasks for i in task.interrupts]
    resume: JsonValue = None
    if any(is_repo_ready(ask) for ask in asks):
        resume = True
    elif asks and decision:
        resume = decision.model_dump(mode="json")
    start: Command[Any] | None = Command(resume=resume) if resume is not None else None
    return await _finish(log, lambda: graph, start, config, budget, review)


def _config(spec: WorkflowSpec, run_id: UUID) -> RunnableConfig:
    return {**thread_config(run_id), "recursion_limit": recursion_limit(spec)}


async def _finish(
    log: RunEventLog,
    build: Callable[[], CompiledWorkflow],
    start: RunState | Command[Any] | None,
    config: RunnableConfig,
    budget: BudgetMeter | None = None,
    review: GateReview | None = None,
) -> WorkflowRunResult:
    """Build the graph and invoke it from `start` (`None` continues from the checkpoint, a
    `Command` continues a paused gate), then report the end, or the pause at a gate. A failure
    to build is logged like one from the graph. A run that has spent its `budget`, before it
    starts or as it goes, ends `failed` (`_stopped`)."""
    graph: CompiledWorkflow | None = None
    try:
        graph = build()
        if budget is not None:
            budget.check()
        final = await graph.ainvoke(start, config)
        paused = await _paused_gate(graph, config)
    except PolicyLimitExceeded as over:
        assert graph is not None, "only the graph and the budget check raise it"
        return await _stopped(log, graph, config, over)
    except asyncio.CancelledError as e:
        if over := next((a for a in e.args if isinstance(a, PolicyLimitExceeded)), None):
            await log_policy_stop(log, over)
            raise
        # `task.cancel("cancelled by user")` names why; a bare cancel is the caller's.
        reason = next((a for a in e.args if isinstance(a, str) and a), "caller cancelled")
        await log.emit(RUN_CANCELLED, payload={"reason": reason})
        raise
    except Exception as exc:
        await log.emit(RUN_FAILED, payload={"error": f"{type(exc).__name__}: {exc}"})
        raise
    if paused is not None:
        state, node_id, request = paused
        if is_repo_ready(request):
            return _result(log, state, "suspended", waiting_at=node_id)
        return await _wait(log, *paused, review)
    return await _report(log, final)


async def log_policy_stop(log: RunEventLog, over: PolicyLimitExceeded) -> None:
    """End a run that went over a policy limit: `policy_limit_exceeded`, then `run_failed` with
    the reason as `error`."""
    await log.emit(POLICY_LIMIT_EXCEEDED, node_id=over.node_id, payload=over.payload())
    await log.emit(RUN_FAILED, payload={"error": over.reason})


async def _stopped(
    log: RunEventLog, graph: CompiledWorkflow, config: RunnableConfig, over: PolicyLimitExceeded
) -> WorkflowRunResult:
    """End a run its graph stopped over a policy limit (its budget), and summarise it from its
    last checkpoint, if it has one."""
    await log_policy_stop(log, over)
    state = initial_state("")
    if graph.checkpointer is not None and (saved := (await graph.aget_state(config)).values):
        state = RunState(**saved)
    return _result(log, state, "failed", stopped_at=over.node_id)


async def _paused_gate(
    graph: CompiledWorkflow, config: RunnableConfig
) -> tuple[RunState, str, dict[str, JsonValue]] | None:
    """If the run stopped at an interrupt (a gate, or after creating its repo): its state, the
    node's id and what it asks."""
    if graph.checkpointer is None:
        return None
    snapshot = await graph.aget_state(config)
    for task in snapshot.tasks:
        if task.interrupts:
            request = cast(dict[str, JsonValue], task.interrupts[0].value)
            return RunState(**snapshot.values), task.name, request
    return None


async def _wait(
    log: RunEventLog,
    state: RunState,
    gate_id: str,
    request: dict[str, JsonValue],
    review: GateReview | None,
) -> WorkflowRunResult:
    """Announce the pause at `gate_id`, with the files the writers that completed before it
    changed. If they cannot be read, the gate pauses without them and says why
    (`changes_error`)."""
    ran = [n for n in dict.fromkeys(state["order"]) if state["results"][n].status == "completed"]
    changes: list[FileChange] = []
    error: str | None = None
    if review is not None:
        try:
            changes = await review.changes(ran)
        except GateReviewError as e:
            error = str(e)
    shown: list[JsonValue] = [c.model_dump(mode="json") for c in changes]
    payload: dict[str, JsonValue] = {**request, "changes": shown}
    if error is not None:
        payload["changes_error"] = error
    await log.emit(NODE_STARTED, node_id=gate_id)
    await log.emit(GATE_WAITING, node_id=gate_id, payload=payload)
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
        # Checkpoints saved before phase 1.9 have no `usage`.
        usage=sum_usage(state.get("usage") or [r.usage for r in results.values()]),
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
