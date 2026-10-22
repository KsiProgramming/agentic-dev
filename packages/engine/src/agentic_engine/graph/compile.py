"""Compiles a workflow spec to a LangGraph graph.

v0 supports `agent`, `tool`, `gate`, `sequence` and `loop`. Agent, tool and gate nodes become
LangGraph nodes named by their spec node id; a sequence chains its steps; a loop becomes an entry
node (its id), its body, and a check node (`<id>.check`, a name no spec node can have) that
evaluates `until` and goes back to the entry or on. A node that does not complete ends the run.

Each node writes `node_started`, its agent events (a tool node: one `tool_call` and its
`tool_result`, and `pr_opened` if it published a branch) and `node_<status>` to the run's event
log. A gate pauses the run (a LangGraph interrupt, so it needs a checkpointer); the runner writes
its `node_started` when the run stops there, and the gate writes `gate_decided` and its end once
it is continued. A loop writes `node_started` once, `loop_iteration_started` before and
`loop_condition_evaluated` after each iteration, then `node_completed` (payload `stop_reason`,
`iterations`) when it stops, or `node_failed` if its condition cannot be evaluated.
"""

import asyncio
from collections.abc import Awaitable, Callable
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import JsonValue

from agentic_engine.agent import AgentNodeResult, AgentNodeStatus, run_agent_node
from agentic_engine.events import (
    LOOP_CONDITION_EVALUATED,
    LOOP_ITERATION_STARTED,
    NODE_CANCELLED,
    NODE_COMPLETED,
    NODE_FAILED,
    NODE_STARTED,
    PR_OPENED,
    NullEventSink,
    RunEventLog,
)
from agentic_engine.expr import ExpressionError, compile_condition
from agentic_engine.gate import run_gate_node
from agentic_engine.graph.checkpoint import Checkpointer
from agentic_engine.graph.state import RunState, RunUpdate
from agentic_engine.spec import (
    PUBLISH_TOOLS,
    AgentNode,
    GateNode,
    LoopNode,
    Node,
    SequenceNode,
    ToolNode,
    WorkflowSpec,
    iter_nodes,
)
from agentic_engine.tool import run_tool_node
from agentic_runtime import AgentEvent, AgentRuntime, ToolExecutor

type CompiledWorkflow = CompiledStateGraph[RunState]
type StepNode = AgentNode | ToolNode | GateNode


class CompileError(ValueError):
    """The spec uses something this compiler does not support yet."""


def step_nodes(root: Node) -> list[StepNode]:
    """The agent, tool and gate nodes under `root` in spec order (depth first; a loop's body
    once)."""
    steps: list[StepNode] = []
    for path, node in iter_nodes(root):
        match node:
            case AgentNode() | ToolNode() | GateNode():
                steps.append(node)
            case SequenceNode() | LoopNode():
                pass
            case _:
                raise CompileError(f"node type {node.type!r} at {path} is not supported yet")
    return steps


def check_node_id(loop: LoopNode) -> str:
    """The LangGraph node that ends each iteration of `loop`. `NodeId` has no `.`, so no spec
    node can take this name."""
    return f"{loop.id}.check"


def recursion_limit(spec: WorkflowSpec) -> int:
    """LangGraph's step limit for `spec`: one step per node run, with every loop run to its
    `max_iterations`, plus a margin. A runtime backstop for the spec's own bounds: a run that
    takes more steps fails (`GraphRecursionError`) instead of going on to LangGraph's default."""

    def steps(node: Node) -> int:
        match node:
            case SequenceNode():
                return sum(steps(s) for s in node.steps)
            case LoopNode():
                return node.max_iterations * (steps(node.body) + 2)
            case AgentNode() | ToolNode() | GateNode():
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
) -> CompiledWorkflow:
    """Build the graph for `spec`. Agent nodes run on `runtime`, tool nodes call `tools`, and
    both write to `log`, if given. With `checkpointer`, the state is saved after each node, in
    the run's thread; a spec with a gate needs one, since a paused run continues from it."""
    if log is None:
        log = RunEventLog(uuid4(), NullEventSink())
    steps = step_nodes(spec.root)
    if checkpointer is None and (gate := next((n for n in steps if isinstance(n, GateNode)), None)):
        raise CompileError(f"gate {gate.id!r} needs a checkpointer to pause the run")
    builder = StateGraph(RunState)

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
                builder.add_edge(node.id, add(node.body, check))
                builder.add_node(check, _loop_check(node, log))
                builder.add_conditional_edges(
                    check, _after_check(node, then), list(dict.fromkeys([node.id, then, END]))
                )
                return node.id
            case AgentNode() | ToolNode() | GateNode():
                builder.add_node(node.id, _step(node, runtime, tools, log))
                if then == END:
                    builder.add_edge(node.id, END)
                else:
                    builder.add_conditional_edges(
                        node.id, _continue_if_completed(node.id, then), [then, END]
                    )
                return node.id

    builder.add_edge(START, add(spec.root, END))
    return builder.compile(checkpointer=checkpointer)


def _step(
    node: StepNode, runtime: AgentRuntime, tools: ToolExecutor | None, log: RunEventLog
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    async def on_event(event: AgentEvent) -> None:
        await log.agent_event(node.id, event)

    async def run(input: str) -> AgentNodeResult:
        match node:
            case ToolNode():
                return await run_tool_node(node, tools, on_event)
            case GateNode():
                return await run_gate_node(node, input, log)
            case AgentNode():
                return await run_agent_node(node, runtime, input, on_event)

    async def step(state: RunState) -> RunUpdate:
        # A gate runs again from its start when the run continues; the runner logs its start.
        if not isinstance(node, GateNode):
            await log.emit(NODE_STARTED, node_id=node.id)
        try:
            result = await run(state["last_text"])
        except asyncio.CancelledError:
            await log.emit(NODE_CANCELLED, node_id=node.id)
            raise
        if (pull := _pull_request(node, result)) is not None:
            await log.emit(PR_OPENED, node_id=node.id, payload=pull)
        payload: dict[str, JsonValue] = {"error": result.error} if result.error else {}
        await log.emit(NODE_END[result.status], node_id=node.id, payload=payload)
        return {
            "last_text": result.text,
            "results": {node.id: result},
            "order": [node.id],
            "usage": [result.usage] if result.usage else [],
        }

    return step


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


def _loop_check(loop: LoopNode, log: RunEventLog) -> Callable[[RunState], Awaitable[RunUpdate]]:
    """Ends an iteration: evaluates `until`, and records the loop's result once it stops. Until
    then the loop has no result, which sends the run back to the entry."""
    condition = compile_condition(loop.until)

    async def check(state: RunState) -> RunUpdate:
        iteration = state["iterations"][loop.id]
        results: dict[str, JsonValue] = {
            node_id: {"status": r.status, "text": r.text, "data": r.data}
            for node_id, r in state["results"].items()
        }
        try:
            met = condition.evaluate(last=state["last_text"], iteration=iteration, results=results)
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


_PULL_REQUEST_FIELDS = ("url", "number", "head", "base", "commit")


def _pull_request(node: StepNode, result: AgentNodeResult) -> dict[str, JsonValue] | None:
    """The pull request a completed publishing tool node opened, if its result names one."""
    if not (isinstance(node, ToolNode) and node.tool in PUBLISH_TOOLS):
        return None
    if result.status != "completed" or not result.data or "url" not in result.data:
        return None
    return {k: result.data[k] for k in _PULL_REQUEST_FIELDS if k in result.data}


def _continue_if_completed(node_id: str, next_id: str) -> Callable[[RunState], str]:
    def route(state: RunState) -> str:
        return next_id if state["results"][node_id].status == "completed" else END

    return route
