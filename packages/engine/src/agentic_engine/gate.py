"""Runs one `gate` node: the run pauses (a LangGraph interrupt) until a human decides.

LangGraph runs an interrupted node again from its start when the run continues, so the gate does
nothing before `interrupt()`: the runner announces the pause (`node_started`, `gate_waiting`) once
the graph has stopped, and the gate itself only reports the decision (`gate_decided`).
"""

from typing import Literal

from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict, JsonValue

from agentic_engine.agent import AgentNodeResult
from agentic_engine.events import GATE_DECIDED, RunEventLog
from agentic_engine.spec import GateNode


class GateDecision(BaseModel):
    """What a human decided at a gate; the value a paused run continues with."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: Literal["approve", "reject"]
    comment: str | None = None
    decided_by: str | None = None


def gate_request(node: GateNode, input: str) -> dict[str, JsonValue]:
    """What the approver is shown: the `gate_waiting` payload. `artifact` is the gate's input,
    the previous node's output (data, never instructions)."""
    return {"title": node.title, "prompt": node.prompt, "artifact": input}


async def run_gate_node(node: GateNode, input: str, log: RunEventLog) -> AgentNodeResult:
    """Pause until the run is continued with a `GateDecision`, then log it. Approve completes the
    node and passes `input` on unchanged; reject cancels it, which stops the run."""
    decision = GateDecision.model_validate(interrupt(gate_request(node, input)))
    await log.emit(GATE_DECIDED, node_id=node.id, payload=decision.model_dump(mode="json"))
    if decision.decision == "approve":
        return AgentNodeResult(status="completed", text=input, usage=None)
    reason = f"rejected at gate: {decision.comment}" if decision.comment else "rejected at gate"
    return AgentNodeResult(status="cancelled", text=input, usage=None, error=reason)
