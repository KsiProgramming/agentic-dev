"""A gate with `review` (13.6): findings at or above `block_at` send the work back to the writer
with no person; the rest reach the approver as comments on the lines they name; a lens that could
not run pauses and is named; approving may dismiss comments, and the rest become the PR's notes.
The tests assert what the writer is handed and what the gate shows (lessons 1 and 13)."""

import json
from typing import Any
from uuid import UUID, uuid4

from langgraph.checkpoint.memory import InMemorySaver

from agentic_engine.artifacts import InMemoryArtifactStore
from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.gate import GateDecision
from agentic_engine.graph import (
    WorkflowRunResult,
    checkpoint_serde,
    resume_workflow,
    run_workflow,
)
from agentic_engine.review import review_flow
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import Message, ReadableWriters
from agentic_runtime.fake import ECHO_USAGE, CallTool, FakeRuntime
from agentic_runtime.findings import Finding, build_report
from agentic_runtime.testing import ScriptedToolExecutor

LENSES = ("correctness", "security", "performance")
DIFF = (
    "writer changed 2 files (+6 -0) against the run's base abc1234:\n"
    "added src/sum.py (+4 -0)\nadded src/db.py (+2 -0)\n\n"
    "diff --git a/src/sum.py b/src/sum.py\n--- /dev/null\n+++ b/src/sum.py\n"
    "@@ -0,0 +1,4 @@\n+a\n+b\n+c\n+d\n"
    "diff --git a/src/db.py b/src/db.py\n--- /dev/null\n+++ b/src/db.py\n"
    "@@ -0,0 +1,2 @@\n+x\n+y\n"
)
APPROVE = GateDecision(decision="approve", decided_by="ada")


def finding(severity: str, category: str, path: str, line: int, message: str) -> Finding:
    return Finding(
        tool="agent", rule="r", severity=severity,  # type: ignore[arg-type]
        category=category, path=path, line=line, message=message,
    )  # fmt: skip


SQL = finding("high", "security", "src/db.py", 2, "SQL is built from a string.")
NITPICK = finding("medium", "correctness", "src/sum.py", 3, "Name the variable.")
FAR = finding("low", "performance", "README.md", 1, "Untouched file.")


def report(*findings: Finding) -> str:
    return json.dumps(build_report("agent", [], findings).model_dump(mode="json"))


def workflow(
    *, max_iterations: int = 4, max_rounds: int = 3, notes: bool = True, publish: bool = False
) -> WorkflowSpec:
    review: dict[str, Any] = {"from": "review.json", "block_at": "high", "max_rounds": max_rounds}
    if notes:
        review["notes"] = "review-notes.md"
    steps: list[dict[str, Any]] = [
        {
            "type": "agent", "id": "writer", "role": "Engineer", "instructions": "Build it.",
            "tools": ["repo.write_file", "repo.commit"],
        },
        *review_flow(of="writer", lenses=LENSES, spec_from="spec.md"),
        {"type": "gate", "id": "approve", "title": "Merge this?", "review": review},
    ]  # fmt: skip
    return parse_spec(
        {
            "spec_version": "0", "id": "review", "name": "Review",
            "root": {"type": "sequence", "id": "main", "steps": [
                {"type": "tool", "id": "spec", "tool": "repo.list_files", "writes": "spec.md"},
                {
                    "type": "loop", "id": "build", "max_iterations": max_iterations,
                    "until": 'results.approve.data.decision != "changes"',
                    "body": {"type": "sequence", "id": "round", "steps": steps},
                },
                *(
                    [{"type": "tool", "id": "publish", "tool": "github.openPR",
                      "args": {"from_node": "writer", "title": "Add sum", "body": "Adds sum.",
                               "notes_from": "review-notes.md"}}]
                    if publish else []
                ),
            ]},
        }
    )  # fmt: skip


class Tools(ScriptedToolExecutor):
    def __init__(self) -> None:
        super().__init__(
            {
                "repo.write_file": "wrote",
                "repo.commit": "abc on agent/x: done",
                "repo.list_files": "# Spec",
                "repo.diff": DIFF,
            }
        )


class PassRuntime:
    """A fake runtime whose node answers a different script on each of its runs (the last one
    repeats): `FakeRuntime` replays a node's whole script every time."""

    def __init__(self, scripts: dict[str, list[list[Any]]], tools: Tools) -> None:
        self._scripts = scripts
        self._tools = tools
        self.requests: list[Any] = []

    def start(self, request: Any) -> Any:
        self.requests.append(request)
        runs = [r for r in self.requests if r.node_id == request.node_id]
        options = self._scripts[request.node_id]
        script = options[min(len(runs), len(options)) - 1]
        return FakeRuntime({request.node_id: script}, tools=self._tools).start(request)


class Run:
    """One run across its pauses. `answers` is what each lens reports on each pass."""

    def __init__(self, workflow: WorkflowSpec, answers: dict[str, list[str]]) -> None:
        self.spec = workflow
        self.tools = Tools()
        self.readable = ReadableWriters(lambda node: f"agent/run/{node}")
        self.artifacts = InMemoryArtifactStore()
        writer: list[Any] = [
            CallTool("repo.write_file", {"path": "src/sum.py", "content": "x"}),
            CallTool("repo.commit", {"message": "work"}),
            Message(text="Done."),
            ECHO_USAGE,
        ]
        self.runtime = PassRuntime(
            {"writer": [writer]}
            | {
                f"review_{lens}": [
                    [Message(text=t), ECHO_USAGE] for t in answers.get(lens, [report()])
                ]
                for lens in LENSES
            },
            self.tools,
        )
        self.run_id: UUID = uuid4()
        self.sink = InMemoryEventSink()
        self.checkpointer = InMemorySaver(serde=checkpoint_serde())
        self.attempt = 1

    async def start(self) -> WorkflowRunResult:
        return await run_workflow(
            self.spec, self.runtime, "Add sum().", run_id=self.run_id, sink=self.sink,
            checkpointer=self.checkpointer, tools=self.tools, readable=self.readable,
            artifacts=self.artifacts,
        )  # fmt: skip

    async def resume(self, decision: GateDecision) -> WorkflowRunResult:
        self.attempt += 1
        return await resume_workflow(
            self.spec, self.runtime, "Add sum().", run_id=self.run_id, sink=self.sink,
            checkpointer=self.checkpointer, next_seq=self.sink.events[-1].seq + 1,
            attempt=self.attempt, decision=decision, tools=self.tools, readable=self.readable,
            artifacts=self.artifacts,
        )  # fmt: skip

    def events(self, kind: str) -> list[RunEvent]:
        return [e for e in self.sink.events if e.type == kind]

    def writes(self) -> list[Any]:
        return [r for r in self.runtime.requests if r.node_id == "writer"]


async def test_a_high_finding_sends_the_work_back_with_no_person_and_the_writer_is_told() -> None:
    run = Run(workflow(), {"security": [report(SQL), report()]})

    first = await run.start()

    assert first.status == "waiting"  # only once: on the second pass, after the fix
    sent = run.events("gate_decided")[0].payload
    assert (sent["decision"], sent["source"], sent["review"]) == ("changes", "review", True)
    assert "decided_by" not in sent
    first_in, second_in = (r.input for r in run.writes())
    assert first_in == "# Spec"  # the spec step before the loop
    assert "## Review" in second_in
    assert "high src/db.py:2 [security]: SQL is built from a string." in second_in
    # Medium and low never go back: only what blocks.
    assert "Name the variable" not in second_in


async def test_findings_below_block_at_pause_as_comments_on_the_lines_they_name() -> None:
    run = Run(workflow(), {"correctness": [report(NITPICK, FAR)]})

    result = await run.start()

    assert result.status == "waiting"
    assert run.events("gate_decided") == []
    shown = run.events("gate_waiting")[0].payload["review"]
    assert (shown["from"], shown["block_at"], shown["rounds_left"]) == ("review.json", "high", 3)
    near, far = shown["comments"]
    assert (near["path"], near["line"], near["node_id"], near["in_diff"]) == (
        "src/sum.py", 3, "writer", True,
    )  # fmt: skip
    assert (far["path"], far["node_id"], far["in_diff"], far["blocking"]) == (
        "README.md", None, False, False,
    )  # fmt: skip
    assert near["lenses"] == ["correctness"]
    assert shown["counts"]["medium"] == 1


async def test_a_blocking_finding_with_no_round_left_is_shown_marked_blocking() -> None:
    run = Run(workflow(max_rounds=1), {"security": [report(SQL), report(SQL)]})

    result = await run.start()

    assert result.status == "waiting"
    assert len(run.events("gate_decided")) == 1  # the one round was used
    shown = run.events("gate_waiting")[0].payload["review"]
    assert shown["rounds_left"] == 0
    assert [c["blocking"] for c in shown["comments"]] == [True]


async def test_the_review_never_sends_the_work_back_on_the_loops_last_pass() -> None:
    """Two passes: pass 1 is sent back; pass 2 is the last, so the gate pauses even with rounds
    left, and the run does not end unapproved (lessons 13)."""
    run = Run(workflow(max_iterations=2, max_rounds=5), {"security": [report(SQL), report(SQL)]})

    result = await run.start()

    assert result.status == "waiting"
    assert len(run.events("gate_decided")) == 1
    assert run.events("gate_waiting")[0].payload["review"]["rounds_left"] == 0


async def test_a_lens_that_could_not_run_pauses_and_is_named_even_with_a_high_finding() -> None:
    run = Run(workflow(), {"security": [report(SQL)], "performance": ["not json"]})

    result = await run.start()

    assert result.status == "waiting"
    assert run.events("gate_decided") == []  # not the writer's fault: a person decides
    shown = run.events("gate_waiting")[0].payload["review"]
    assert shown["failed_lenses"] == ["performance"]


async def test_dismissals_are_stored_carried_and_left_out_of_the_notes() -> None:
    run = Run(workflow(), {"correctness": [report(NITPICK, FAR)]})
    await run.start()
    comments = run.events("gate_waiting")[0].payload["review"]["comments"]
    gone = comments[0]["fingerprint"]

    done = await run.resume(GateDecision(decision="approve", decided_by="ada", dismissed=[gone]))

    assert done.status == "completed"
    decided = run.events("gate_decided")[-1].payload
    assert decided["dismissed"] == [gone]
    notes = await run.artifacts.get("review-notes.md", 1)
    assert notes is not None
    assert "README.md" in notes.content
    assert "src/sum.py" not in notes.content  # dismissed


async def test_a_dismissal_the_gate_did_not_show_fails_the_gate() -> None:
    run = Run(workflow(), {"correctness": [report(NITPICK)]})
    await run.start()

    done = await run.resume(GateDecision(decision="approve", dismissed=["nope"]))

    assert done.status == "failed"
    assert "dismissals do not fit" in (done.results["approve"].error or "")


def test_dismissing_with_a_reject_is_refused_by_the_decision_itself() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="only an approval dismisses"):
        GateDecision(decision="reject", dismissed=["x"])


async def test_a_resume_at_the_gate_decides_the_same_and_runs_no_lens_again() -> None:
    run = Run(workflow(), {"correctness": [report(NITPICK)]})
    await run.start()
    lens_runs = len([r for r in run.runtime.requests if r.node_id.startswith("review_")])

    done = await run.resume(APPROVE)

    assert done.status == "completed"
    assert len([r for r in run.runtime.requests if r.node_id.startswith("review_")]) == lens_runs
    assert len(run.events("review_collected")) == 1


class PublishTools(Tools):
    def __init__(self) -> None:
        super().__init__()
        self._tools["github.openPR"] = "opened"  # type: ignore[attr-defined]


async def published(findings: list[Finding]) -> dict[str, Any]:
    run = Run(workflow(publish=True), {"correctness": [report(*findings)]})
    run.tools = PublishTools()
    run.runtime = PassRuntime(run.runtime._scripts, run.tools)  # pyright: ignore
    await run.start()
    done = await run.resume(APPROVE)
    assert done.status == "completed"
    return next(args for name, args in run.tools.calls if name == "github.openPR")


async def test_the_pr_body_gets_the_review_notes_and_the_tool_never_sees_notes_from() -> None:
    args = await published([NITPICK])

    assert "notes_from" not in args
    assert args["body"].startswith("Adds sum.\n\n## Review notes\n\n")
    assert "`src/sum.py:3` (correctness): Name the variable." in args["body"]


async def test_a_mention_and_html_in_a_finding_never_reach_the_pr_body_live() -> None:
    sneaky = finding("medium", "correctness", "src/sum.py", 3, "ping @octocat <b>now</b>")

    args = await published([sneaky])

    assert "@octocat" not in args["body"]  # a zero-width joiner follows the @
    zwj = chr(0x200D)
    assert f"@{zwj}octocat" in args["body"]
    assert "<b>" not in args["body"]
    assert f"ping @{zwj}octocat now" in args["body"]


async def test_the_notes_are_capped() -> None:
    many = [finding("low", "correctness", f"src/f{i}.py", 1, "x" * 400) for i in range(40)]

    args = await published(many)

    notes = args["body"].split("## Review notes\n\n", 1)[1]
    assert len(notes) < 8_100
    assert notes.endswith("(cut here: the run's review has the rest)")
