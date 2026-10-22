"""The `gate` primitive: a run pauses at a gate and continues on a human decision (phase 1.7)."""

from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.gate import GateDecision
from agentic_engine.graph import (
    CompileError,
    WorkflowRunResult,
    checkpoint_serde,
    compile_workflow,
    resume_workflow,
    run_workflow,
)
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import Message
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime

APPROVE = GateDecision(decision="approve", decided_by="ada")
REJECT = GateDecision(decision="reject", comment="not this time")


def gated(*gates: str) -> WorkflowSpec:
    """`writer`, then each gate followed by an agent `after-<gate>`."""
    steps: list[object] = [{"type": "agent", "id": "writer", "role": "W", "instructions": "Go."}]
    for gate in gates:
        steps.append({"type": "gate", "id": gate, "title": f"Approve {gate}", "prompt": "Check."})
        steps.append({"type": "agent", "id": f"after-{gate}", "role": "A", "instructions": "Go."})
    return parse_spec(
        {
            "spec_version": "0",
            "id": "gated",
            "name": "Gated",
            "root": {"type": "sequence", "id": "main", "steps": steps},
        }
    )


def saver() -> InMemorySaver:
    return InMemorySaver(serde=checkpoint_serde())


def lifecycle(events: list[RunEvent]) -> list[tuple[str, str | None]]:
    return [(e.type, e.node_id) for e in events if e.type.startswith(("node_", "run_", "gate_"))]


class Run:
    """One run across its pauses: every attempt writes to the same sink, continuing `seq`."""

    def __init__(self, spec: WorkflowSpec, runtime: FakeRuntime | None = None) -> None:
        self.spec = spec
        self.runtime = runtime or FakeRuntime({"writer": [Message(text="draft notes"), ECHO_USAGE]})
        self.run_id: UUID = uuid4()
        self.sink = InMemoryEventSink()
        self.checkpointer = saver()
        self.attempt = 1

    async def start(self) -> WorkflowRunResult:
        return await run_workflow(
            self.spec,
            self.runtime,
            "go",
            run_id=self.run_id,
            sink=self.sink,
            checkpointer=self.checkpointer,
        )

    async def resume(self, decision: GateDecision | None) -> WorkflowRunResult:
        self.attempt += 1
        return await resume_workflow(
            self.spec,
            self.runtime,
            "go",
            run_id=self.run_id,
            sink=self.sink,
            checkpointer=self.checkpointer,
            next_seq=self.sink.events[-1].seq + 1,
            attempt=self.attempt,
            decision=decision,
        )


async def test_run_pauses_at_gate() -> None:
    """Done when (1.7, first half): a run pauses at a gate."""
    run = Run(gated("gate"))

    result = await run.start()

    assert result.status == "waiting"
    assert result.waiting_at == "gate"
    assert result.stopped_at is None
    assert result.order == ["writer"]
    assert [r.node_id for r in run.runtime.requests] == ["writer"]
    assert lifecycle(run.sink.events) == [
        ("run_started", None),
        ("node_started", "writer"),
        ("node_completed", "writer"),
        ("node_started", "gate"),
        ("gate_waiting", "gate"),
    ]
    waiting = run.sink.events[-1]
    assert waiting.payload == {
        "title": "Approve gate",
        "prompt": "Check.",
        "artifact": "draft notes",
    }


async def test_approve_continues_the_run() -> None:
    """Done when (1.7, second half): the run resumes on approval."""
    run = Run(gated("gate"))
    await run.start()
    paused_at = len(run.sink.events)

    result = await run.resume(APPROVE)

    assert result.status == "completed"
    assert result.order == ["writer", "gate", "after-gate"]
    after = run.runtime.requests[-1]
    assert (after.node_id, after.input) == ("after-gate", "draft notes")  # the gate passes it on
    assert lifecycle(run.sink.events[paused_at:]) == [
        ("run_resumed", None),
        ("gate_decided", "gate"),
        ("node_completed", "gate"),
        ("node_started", "after-gate"),
        ("node_completed", "after-gate"),
        ("run_completed", None),
    ]
    decided = next(e for e in run.sink.events if e.type == "gate_decided")
    assert decided.payload == {"decision": "approve", "comment": None, "decided_by": "ada"}
    resumed = run.sink.events[paused_at]
    assert resumed.payload == {"attempt": 2, "completed_nodes": ["writer"]}


async def test_reject_cancels_the_run_at_the_gate() -> None:
    run = Run(gated("gate"))
    await run.start()
    paused_at = len(run.sink.events)

    result = await run.resume(REJECT)

    assert result.status == "cancelled"
    assert result.stopped_at == "gate"
    assert result.results["gate"].error == "rejected at gate: not this time"
    assert [r.node_id for r in run.runtime.requests] == ["writer"]
    assert lifecycle(run.sink.events[paused_at:]) == [
        ("run_resumed", None),
        ("gate_decided", "gate"),
        ("node_cancelled", "gate"),
        ("run_cancelled", None),
    ]
    assert run.sink.events[-1].payload == {"stopped_at": "gate"}


async def test_events_have_no_gaps_or_duplicates_across_the_pause() -> None:
    run = Run(gated("gate"))
    await run.start()
    await run.resume(APPROVE)

    events = run.sink.events
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    assert {e.run_id for e in events} == {run.run_id}
    kinds = [(e.type, e.node_id) for e in events]
    assert kinds.count(("node_started", "gate")) == 1
    assert kinds.count(("gate_waiting", "gate")) == 1
    assert kinds.count(("gate_decided", "gate")) == 1


async def test_resume_without_decision_pauses_again() -> None:
    """A worker that picks a paused run up with no decision (e.g. it died right after the pause)
    leaves it waiting at the same gate and announces the pause again; nothing else runs."""
    run = Run(gated("gate"))
    await run.start()
    paused_at = len(run.sink.events)

    result = await run.resume(None)

    assert (result.status, result.waiting_at) == ("waiting", "gate")
    assert [r.node_id for r in run.runtime.requests] == ["writer"]
    assert lifecycle(run.sink.events[paused_at:]) == [
        ("run_resumed", None),
        ("node_started", "gate"),
        ("gate_waiting", "gate"),
    ]
    assert (await run.resume(APPROVE)).status == "completed"


async def test_two_gates_pause_twice() -> None:
    run = Run(gated("first", "second"))

    assert (await run.start()).waiting_at == "first"
    assert (await run.resume(APPROVE)).waiting_at == "second"
    result = await run.resume(APPROVE)

    assert result.status == "completed"
    assert result.order == ["writer", "first", "after-first", "second", "after-second"]


async def test_gate_first_shows_the_run_input() -> None:
    spec = parse_spec(
        {
            "spec_version": "0",
            "id": "gate-first",
            "name": "Gate first",
            "root": {"type": "gate", "id": "gate", "title": "Start?"},
        }
    )
    run = Run(spec)

    assert (await run.start()).waiting_at == "gate"
    assert run.sink.events[-1].payload == {"title": "Start?", "prompt": None, "artifact": "go"}
    result = await run.resume(APPROVE)
    assert (result.status, result.text) == ("completed", "go")


def test_gate_needs_a_checkpointer() -> None:
    with pytest.raises(CompileError, match="gate 'gate' needs a checkpointer"):
        compile_workflow(gated("gate"), FakeRuntime())
