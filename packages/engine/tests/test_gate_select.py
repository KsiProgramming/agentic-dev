"""Selection gates and ending a run at a gate (phase 6.7): a gate shows the items of a JSON run
artifact, its approval names the ones chosen, and its output is the artifact with only those."""

import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agentic_engine.artifacts import InMemoryArtifactStore
from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.gate import (
    GateDecision,
    SelectionError,
    SelectionShown,
    check_selection,
)
from agentic_engine.graph import WorkflowRunResult, checkpoint_serde, resume_workflow, run_workflow
from agentic_engine.policy import PLATFORM_POLICY
from agentic_engine.spec import WorkflowSpec, parse_spec, validate_workflow
from agentic_runtime import Message
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime


def finding(key: str, severity: str, path: str = "app.py") -> dict[str, Any]:
    return {
        "fingerprint": key,
        "tool": "agent",
        "rule": f"rule-{key}",
        "severity": severity,
        "category": "security",
        "path": path,
        "line": 3,
        "message": f"Issue {key}.",
    }


REPORT: dict[str, Any] = {
    "scanner": "merged",
    "checks": [{"path": ".", "kind": "repo", "tool": "agent", "status": "ran", "findings": 3}],
    "findings": [finding("a", "high"), finding("b", "low"), finding("c", "critical")],
    "counts": {"critical": 1, "high": 1, "medium": 0, "low": 1, "info": 0},
    "truncated": False,
}

SELECT: dict[str, Any] = {
    "artifact": "findings.json",
    "preselect": 'item.severity in ["critical", "high"]',
}


def spec(gate: dict[str, Any] | None = None, *, after: bool = True) -> WorkflowSpec:
    """`scan` writes `findings.json`, then the gate `pick` (selecting from it), then `fix`."""
    steps: list[Any] = [
        {
            "type": "agent",
            "id": "scan",
            "role": "S",
            "instructions": "Scan.",
            "writes": "findings.json",
        },
        {"type": "gate", "id": "pick", "title": "Pick findings", "select": SELECT, **(gate or {})},
    ]
    if after:
        steps.append({"type": "agent", "id": "fix", "role": "F", "instructions": "Fix."})
    return parse_spec(
        {
            "spec_version": "0",
            "id": "select",
            "name": "Select",
            "root": {"type": "sequence", "id": "main", "steps": steps},
        }
    )


class Run:
    """One run across its pauses, with one checkpointer and one artifact store for every
    attempt."""

    def __init__(self, workflow: WorkflowSpec, report: object = REPORT) -> None:
        self.spec = workflow
        text = report if isinstance(report, str) else json.dumps(report)
        self.runtime = FakeRuntime({"scan": [Message(text=text), ECHO_USAGE]})
        self.run_id: UUID = uuid4()
        self.sink = InMemoryEventSink()
        self.checkpointer = InMemorySaver(serde=checkpoint_serde())
        self.artifacts = InMemoryArtifactStore()
        self.attempt = 1

    async def start(self) -> WorkflowRunResult:
        return await run_workflow(
            self.spec,
            self.runtime,
            "go",
            run_id=self.run_id,
            sink=self.sink,
            checkpointer=self.checkpointer,
            artifacts=self.artifacts,
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
            artifacts=self.artifacts,
        )

    def last(self, kind: str) -> RunEvent:
        return next(e for e in reversed(self.sink.events) if e.type == kind)


async def test_a_selection_gate_shows_the_artifacts_items() -> None:
    run = Run(spec())

    result = await run.start()

    assert result.status == "waiting"
    assert run.last("gate_waiting").payload["select"] == {
        "artifact": "findings.json",
        "version": 1,
        "items": "findings",
        "key": "fingerprint",
        "count": 3,
        "keys": ["a", "b", "c"],
        "preselected": ["a", "c"],
        "min": 1,
    }


async def test_approving_passes_on_only_the_chosen_items() -> None:
    """Done when (6.7): the step after the gate gets the selected findings, as data, and the
    report's counts are those of the selection."""
    run = Run(spec({"writes": "selected.json"}))
    await run.start()

    result = await run.resume(GateDecision(decision="approve", selection=["c", "b"]))

    assert result.status == "completed"
    chosen = json.loads(run.runtime.requests[-1].input)
    assert run.runtime.requests[-1].node_id == "fix"
    assert [f["fingerprint"] for f in chosen["findings"]] == ["b", "c"]  # the artifact's order
    assert chosen["counts"] == {"critical": 1, "high": 0, "medium": 0, "low": 1, "info": 0}
    assert chosen["checks"] == REPORT["checks"]
    assert result.results["pick"].data == chosen
    stored = await run.artifacts.get("selected.json")
    assert stored is not None and json.loads(stored.content) == chosen
    assert run.last("gate_decided").payload["selection"] == ["c", "b"]


async def test_a_selection_that_does_not_fit_fails_the_gate() -> None:
    run = Run(spec())
    await run.start()

    result = await run.resume(GateDecision(decision="approve", selection=["zz"]))

    assert result.status == "failed"
    assert result.stopped_at == "pick"
    assert "'zz' is not an item this gate showed" in (result.results["pick"].error or "")
    assert [r.node_id for r in run.runtime.requests] == ["scan"]


async def test_on_reject_end_completes_the_run_without_the_steps_after() -> None:
    """Rejecting a gate with `on_reject: end` ends the run as completed: an audit nobody wants
    to fix still succeeded."""
    run = Run(spec({"on_reject": "end"}))
    await run.start()
    assert run.last("gate_waiting").payload["on_reject"] == "end"

    result = await run.resume(GateDecision(decision="reject", comment="not now"))

    assert result.status == "completed"
    assert result.order == ["scan", "pick"]
    assert [r.node_id for r in run.runtime.requests] == ["scan"]
    assert [e.type for e in run.sink.events][-3:] == [
        "gate_decided",
        "node_completed",
        "run_completed",
    ]


async def test_on_reject_end_holds_across_a_pause_announced_again() -> None:
    """A worker that restarts while the gate waits announces the pause again; the decision
    after it still ends the run."""
    run = Run(spec({"on_reject": "end"}))
    await run.start()
    again = await run.resume(None)
    assert again.status == "waiting"

    result = await run.resume(GateDecision(decision="reject"))

    assert result.status == "completed"
    assert [r.node_id for r in run.runtime.requests] == ["scan"]


async def test_a_plain_reject_still_cancels_the_run() -> None:
    run = Run(spec())
    await run.start()

    result = await run.resume(GateDecision(decision="reject"))

    assert result.status == "cancelled"


async def test_a_gate_whose_artifact_is_not_a_list_of_items_fails_before_it_pauses() -> None:
    run = Run(spec(), report={"scanner": "merged"})

    result = await run.start()

    assert result.status == "failed"
    assert result.results["pick"].error == "findings.json has no list 'findings'"
    assert [(e.type, e.node_id) for e in run.sink.events][-3:] == [
        ("node_started", "pick"),
        ("node_failed", "pick"),
        ("run_failed", None),
    ]


SHOWN = SelectionShown(
    artifact="findings.json",
    version=1,
    items="findings",
    key="fingerprint",
    count=3,
    keys=["a", "b", "c"],
    preselected=[],
    min=2,
)


@pytest.mark.parametrize(
    ("shown", "decision", "selection", "code"),
    [
        (None, "approve", ["a"], "selection_not_allowed"),
        (SHOWN, "reject", ["a"], "selection_not_allowed"),
        (SHOWN, "approve", None, "selection_required"),
        (SHOWN, "approve", ["a", "a"], "duplicate_selection"),
        (SHOWN, "approve", ["a", "x"], "unknown_selection"),
        (SHOWN, "approve", ["a"], "selection_too_small"),
    ],
)
def test_check_selection_refuses(
    shown: SelectionShown | None, decision: Any, selection: list[str] | None, code: str
) -> None:
    with pytest.raises(SelectionError) as raised:
        check_selection(shown, decision, selection)
    assert raised.value.code == code


def test_check_selection_keeps_a_fitting_selection() -> None:
    assert check_selection(SHOWN, "approve", ["c", "a"]) == ["c", "a"]
    assert check_selection(SHOWN, "reject", None) == []
    assert check_selection(None, "approve", None) == []


def issues(raw: dict[str, Any]) -> list[tuple[str, str]]:
    found = validate_workflow(
        raw, policy=PLATFORM_POLICY, priced=lambda _: True, default_model="default"
    )
    return [(i.code, i.path) for i in found]


def raw(steps: list[Any]) -> dict[str, Any]:
    return {
        "spec_version": "0",
        "id": "v",
        "name": "V",
        "root": {"type": "sequence", "id": "main", "steps": steps},
    }


SCAN = {"type": "agent", "id": "scan", "role": "S", "instructions": "x", "writes": "findings.json"}


def test_validation_of_selection_gates() -> None:
    unknown = {"type": "gate", "id": "g", "title": "t", "select": {"artifact": "nope.json"}}
    assert issues(raw([SCAN, unknown])) == [("artifact_unknown", "root.steps[1].select.artifact")]
    bad = {"type": "gate", "id": "g", "title": "t", "select": {**SELECT, "preselect": "item.("}}
    assert issues(raw([SCAN, bad])) == [("invalid_expression", "root.steps[1].select.preselect")]
    text = {"type": "gate", "id": "g", "title": "t", "select": {"artifact": "notes.md"}}
    assert [c for c, _ in issues(raw([SCAN, text]))] == ["schema"]
    lonely = {"type": "gate", "id": "g", "title": "t", "writes": "x.json"}
    assert [c for c, _ in issues(raw([SCAN, lonely]))] == ["schema"]


def test_on_reject_end_only_on_a_step_of_the_root_sequence() -> None:
    gate = {"type": "gate", "id": "g", "title": "t", "on_reject": "end"}
    assert issues(raw([SCAN, gate])) == []
    nested = {"type": "sequence", "id": "inner", "steps": [gate]}
    assert issues(raw([SCAN, nested])) == [("invalid_gate", "root.steps[1].steps[0].on_reject")]


def test_a_selection_gates_writes_can_be_read_after_it() -> None:
    gate = {"type": "gate", "id": "g", "title": "t", "select": SELECT, "writes": "sel.json"}
    reader = {"type": "agent", "id": "r", "role": "R", "instructions": "x", "reads": ["sel.json"]}
    assert issues(raw([SCAN, gate, reader])) == []
