"""Runs a workflow spec end to end on an `AgentRuntime`."""

from agentic_engine.agent import sum_usage
from agentic_engine.graph.compile import compile_workflow
from agentic_engine.graph.state import WorkflowRunResult, initial_state
from agentic_engine.spec import WorkflowSpec
from agentic_runtime import AgentRuntime


async def run_workflow(
    spec: WorkflowSpec, runtime: AgentRuntime, input: str = ""
) -> WorkflowRunResult:
    """Compile `spec`, run it with `input` for the first node, and summarise the outcome.

    A node that fails or is cancelled stops the run; its status becomes the run's status. If the
    caller is cancelled, the in-flight agent run is cancelled and `CancelledError` propagates.
    """
    final = await compile_workflow(spec, runtime).ainvoke(initial_state(input))
    order = final["order"]
    results = {node_id: final["results"][node_id] for node_id in order}
    stopped_at = next((i for i in order if results[i].status != "completed"), None)
    return WorkflowRunResult(
        status=results[stopped_at].status if stopped_at else "completed",
        text=final["last_text"],
        order=order,
        results=results,
        usage=sum_usage(r.usage for r in results.values()),
        stopped_at=stopped_at,
    )
