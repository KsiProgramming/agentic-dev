"""The `gate` primitive: a run pauses at a gate and continues on a human decision (phase 1.7)."""

from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.gate import GateComment, GateDecision
from agentic_engine.graph import (
    CompileError,
    WorkflowRunResult,
    checkpoint_serde,
    compile_workflow,
    resume_workflow,
    run_workflow,
)
from agentic_engine.policy import PLATFORM_POLICY, Policy
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import Message
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime

APPROVE = GateDecision(decision="approve", decided_by="ada")
REJECT = GateDecision(decision="reject", comment="not this time")


def gated(*gates: str, ttl_s: int | None = None) -> WorkflowSpec:
    """`writer`, then each gate (waiting `ttl_s`, if given) followed by an agent `after-<gate>`."""
    steps: list[object] = [{"type": "agent", "id": "writer", "role": "W", "instructions": "Go."}]
    for gate in gates:
        step = {"type": "gate", "id": gate, "title": f"Approve {gate}", "prompt": "Check."}
        steps.append(step if ttl_s is None else {**step, "ttl_s": ttl_s})
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

    def __init__(
        self, spec: WorkflowSpec, runtime: FakeRuntime | None = None, policy: Policy | None = None
    ) -> None:
        self.spec = spec
        self.policy = policy or PLATFORM_POLICY
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
            policy=self.policy,
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
    expires_at = waiting.payload.pop("expires_at")
    assert waiting.payload == {
        "title": "Approve gate",
        "prompt": "Check.",
        "artifact": "draft notes",
        "ttl_s": 72 * 60 * 60,
        "changes": [],
        "run_artifacts": [],
    }
    assert isinstance(expires_at, str)
    assert datetime.fromisoformat(expires_at) - waiting.created_at == pytest.approx(
        timedelta(hours=72), abs=timedelta(seconds=1)
    )


async def test_a_gate_expires_after_the_run_policys_time_to_live() -> None:
    """Phase 11.3: a gate with no time to live of its own waits the run's `approval_ttl_s`."""
    run = Run(gated("gate"), policy=PLATFORM_POLICY.model_copy(update={"approval_ttl_s": 600}))

    await run.start()

    waiting = run.sink.events[-1]
    assert waiting.payload["ttl_s"] == 600
    expires_at = datetime.fromisoformat(str(waiting.payload["expires_at"]))
    assert expires_at - waiting.created_at == pytest.approx(
        timedelta(minutes=10), abs=timedelta(seconds=1)
    )


async def test_a_gate_sets_its_own_time_to_live() -> None:
    run = Run(gated("gate", ttl_s=5))

    await run.start()

    waiting = run.sink.events[-1]
    assert waiting.payload["ttl_s"] == 5
    expires_at = datetime.fromisoformat(str(waiting.payload["expires_at"]))
    assert expires_at - waiting.created_at == pytest.approx(
        timedelta(seconds=5), abs=timedelta(seconds=1)
    )


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
    shown = run.sink.events[-1].payload
    assert {k: v for k, v in shown.items() if k not in ("ttl_s", "expires_at")} == {
        "title": "Start?",
        "prompt": None,
        "artifact": "go",
        "changes": [],
        "run_artifacts": [],
    }
    result = await run.resume(APPROVE)
    assert (result.status, result.text) == ("completed", "go")


def test_gate_needs_a_checkpointer() -> None:
    with pytest.raises(CompileError, match="gate 'gate' needs a checkpointer"):
        compile_workflow(gated("gate"), FakeRuntime())


async def test_a_gate_in_a_loop_pauses_on_every_pass() -> None:
    """Phase 7.8: a loop's body may hold a gate; it pauses once per pass and the loop goes on."""
    spec = parse_spec(
        {
            "spec_version": "0",
            "id": "gate-in-loop",
            "name": "Gate in a loop",
            "root": {
                "type": "loop",
                "id": "revise",
                "until": "iteration >= 2",
                "max_iterations": 3,
                "body": {
                    "type": "sequence",
                    "id": "round",
                    "steps": [
                        {"type": "agent", "id": "writer", "role": "W", "instructions": "Go."},
                        {"type": "gate", "id": "check", "title": "Right?"},
                    ],
                },
            },
        }
    )
    run = Run(spec, FakeRuntime({"writer": [Message(text="draft"), ECHO_USAGE] * 2}))

    first = await run.start()
    second = await run.resume(APPROVE)
    done = await run.resume(APPROVE)

    assert [first.status, second.status, done.status] == ["waiting", "waiting", "completed"]
    assert (first.waiting_at, second.waiting_at) == ("check", "check")
    assert [e.type for e in run.sink.events].count("gate_waiting") == 2
    assert [e.type for e in run.sink.events].count("gate_decided") == 2
    assert [r.node_id for r in run.runtime.requests] == ["writer", "writer"]


def revising(on_changes: int | None = 2, max_iterations: int = 3) -> WorkflowSpec:
    """A writer and a gate in a loop that goes round while the gate sends the work back."""
    gate: dict[str, object] = {"type": "gate", "id": "check", "title": "Right?"}
    if on_changes is not None:
        gate["on_changes"] = on_changes
    return parse_spec(
        {
            "spec_version": "0",
            "id": "revising",
            "name": "Revising",
            "root": {
                "type": "loop",
                "id": "revise",
                "until": 'results.check.data.decision != "changes"',
                "max_iterations": max_iterations,
                "body": {
                    "type": "sequence",
                    "id": "round",
                    "steps": [
                        {"type": "agent", "id": "writer", "role": "W", "instructions": "Go."},
                        gate,
                    ],
                },
            },
        }
    )


async def test_a_request_for_changes_sends_the_comments_to_the_next_pass() -> None:
    """Phase 7.8: the gate completes with the comments, and the loop's next pass gets them."""
    run = Run(revising(), FakeRuntime({"writer": [Message(text="draft"), ECHO_USAGE] * 2}))
    comments = [
        GateComment(item="spec", text="Name the users."),
        GateComment(item="plan", text="List the risks."),
        GateComment(item="spec", text="Cut the scope."),
    ]

    assert (await run.start()).status == "waiting"
    second = await run.resume(GateDecision(decision="changes", comments=comments))
    done = await run.resume(APPROVE)

    assert (second.status, done.status) == ("waiting", "completed")
    assert run.runtime.requests[1].input == (
        "## spec\n\n- Name the users.\n- Cut the scope.\n\n## plan\n\n- List the risks."
    )
    decided = [e for e in run.sink.events if e.type == "gate_decided"]
    assert [e.payload["decision"] for e in decided] == ["changes", "approve"]
    assert decided[0].payload["comments"] == [c.model_dump() for c in comments]


async def test_a_gate_without_on_changes_does_not_take_a_request_for_changes() -> None:
    run = Run(
        revising(on_changes=None), FakeRuntime({"writer": [Message(text="draft"), ECHO_USAGE]})
    )
    asked = GateDecision(decision="changes", comments=[GateComment(item="spec", text="More.")])

    await run.start()
    result = await run.resume(asked)

    assert (result.status, result.stopped_at) == ("failed", "check")
    failed = [e for e in run.sink.events if e.type == "node_failed" and e.node_id == "check"]
    assert "does not take requests for changes" in str(failed[0].payload["error"])


def test_a_request_for_changes_needs_comments_and_only_it_has_them() -> None:
    with pytest.raises(ValueError, match="at least one comment"):
        GateDecision(decision="changes")
    with pytest.raises(ValueError, match="only a request for changes"):
        GateDecision(decision="approve", comments=[GateComment(item="spec", text="x")])


def test_on_changes_needs_a_loop_with_a_pass_left() -> None:
    assert revising(on_changes=2, max_iterations=3).id == "revising"
    with pytest.raises(ValueError, match="needs a pass left"):
        revising(on_changes=3, max_iterations=3)
    with pytest.raises(ValueError, match="in a loop's body"):
        parse_spec(
            {
                "spec_version": "0",
                "id": "outside",
                "name": "Outside",
                "root": {"type": "gate", "id": "check", "title": "Right?", "on_changes": 1},
            }
        )
