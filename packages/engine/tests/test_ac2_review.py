"""AC-2 with `review` on (13.6): the "Plan, build and review" flow with three independent lenses
in place of the reviewer. A lens finds a high-severity problem, the gate sends it back to the lead
with no person, the lead's second pass is handed it under `## Review`, and the gate then pauses
with the remaining comments. As lessons rule 1 asks, the tests assert what each agent receives."""

import json
from collections.abc import Sequence

from pydantic import JsonValue

from agentic_engine.spec import READ_TOOLS
from agentic_engine.templates import PlanBuildReviewParams, build_plan_build_review_spec
from agentic_runtime import AgentRequest, AgentRun, Message, ToolOutput
from agentic_runtime.fake import ECHO_USAGE, CallTool, FakeRuntime
from agentic_runtime.findings import Finding, build_report
from agentic_runtime.testing import ScriptedToolExecutor

from .test_ac2 import PULL, Ac2Run, Team
from .test_gate import saver  # noqa: F401  (the harness's checkpointer)

DIFF = (
    "implement changed 1 file (+3 -0) against the run's base abc1234:\n"
    "modified form.py (+3 -0)\n\n"
    "diff --git a/form.py b/form.py\n--- a/form.py\n+++ b/form.py\n@@ -1,0 +1,3 @@\n+a\n+b\n+c\n"
)
SQL = Finding(
    tool="agent", rule="sql", severity="high", category="security", path="form.py", line=2,
    message="Email is put into a SQL string.",
)  # fmt: skip
STYLE = Finding(
    tool="agent", rule="name", severity="medium", category="correctness", path="form.py", line=3,
    message="Name this.",
)  # fmt: skip


def report(*findings: Finding) -> str:
    return json.dumps(build_report("agent", [], findings).model_dump(mode="json"))


class ReviewTeam(Team):
    """The flow's agents, with the three lenses answering `answers[lens]` per pass."""

    def __init__(
        self, tools: ScriptedToolExecutor, answers: dict[str, Sequence[str]] | None = None
    ) -> None:
        super().__init__(tools)
        self.answers = answers or {}
        self.lens_requests: list[AgentRequest] = []

    def start(self, request: AgentRequest) -> AgentRun:
        if not request.role.endswith(" reviewer") or request.role == "Senior reviewer":
            return super().start(request)
        self.lens_requests.append(request)
        lens = request.node_id
        asked = len([r for r in self.lens_requests if r.node_id == lens])
        answers = self.answers.get(lens, [report()])
        text = answers[min(asked - 1, len(answers) - 1)]
        script = [CallTool("repo.read_file", {"path": "form.py"}), Message(text=text), ECHO_USAGE]
        return FakeRuntime({lens: script}, tools=self.tools).start(request)


def run_of(answers: dict[str, Sequence[str]], **options: object) -> Ac2Run:
    spec = build_plan_build_review_spec(PlanBuildReviewParams(review=True, **options))  # type: ignore[arg-type]
    run = Ac2Run(spec)
    run.tools = ScriptedToolExecutor(
        {
            "repo.read_file": "x = 1",
            "repo.write_file": "wrote",
            "repo.diff": DIFF,
            "github.openPR": ToolOutput(text="opened #12", data=PULL),
        }
    )
    run.team = ReviewTeam(run.tools, answers)
    return run


async def test_a_high_finding_goes_back_to_the_lead_and_the_rest_reach_the_gate() -> None:
    run = run_of(
        {
            "review_security": [report(SQL, STYLE), report(STYLE)],
        }
    )

    paused = await run.start()

    assert paused.status == "waiting" and paused.waiting_at == "approve_pr", {
        k: r.error for k, r in paused.results.items() if r.error
    }
    # Pass 1 was sent back with no person: the gate decided `changes` from the review.
    sent = [e.payload for e in run.sink.events if e.type == "gate_decided"]
    assert [(p["decision"], p["source"]) for p in sent] == [("changes", "review")]
    # The lead's second pass is handed the finding under `## Review`, as data.
    first, second = run.team.of("implement")
    assert "## Review" not in first.input
    given = json.loads(second.input)
    assert "## Review" in given["input"]
    assert "high form.py:2 [security]: Email is put into a SQL string." in given["input"]
    # The gate shows what is left, on the integration branch's file and line.
    shown = next(e for e in run.sink.events if e.type == "gate_waiting").payload["review"]
    [comment] = shown["comments"]
    assert (comment["node_id"], comment["path"], comment["line"], comment["in_diff"]) == (
        "implement", "form.py", 3, True,
    )  # fmt: skip
    assert shown["rounds_left"] == 1  # three passes, one send-back used, pass 3 is the last


async def test_what_every_lens_receives() -> None:
    """Lessons rule 1, for the lenses of a real template."""
    run = run_of({})
    await run.start()
    lenses = run.team.lens_requests

    assert sorted({r.node_id for r in lenses}) == [
        "review_correctness", "review_performance", "review_security",
    ]  # fmt: skip
    for request in lenses:
        # Fresh input: the spec and the diff, never the synthesizer's description.
        assert request.input.startswith("Reviewing `implement`'s work.")
        assert "## Change\n\nimplement changed 1 file" in request.input
        assert "(pass 1)" not in request.input and "Signup validation" not in request.input
        # Read-only tools, no artifacts, the findings schema, and the request as context.
        assert set(request.tools) <= READ_TOOLS and request.output_schema is not None
        assert "<request>" in request.context
        # Its tool calls go out as itself, so its reads go to the writer's refs, never the
        # orchestrator's worktree.
        assert request.node_id.startswith("review_")
    calls = list(zip(run.tools.calls, run.tools.node_ids, strict=True))
    assert "review_security" in {n for (t, _), n in calls if t == "repo.read_file"}
    assert all(a == {"node": "implement"} for (t, a), _ in calls if t == "repo.diff")


async def test_the_approved_runs_pr_body_has_the_review_notes() -> None:
    run = run_of({"review_correctness": [report(STYLE)]})
    paused = await run.start()
    assert paused.status == "waiting"

    from agentic_engine.gate import GateDecision

    done = await run.decide(GateDecision(decision="approve"))

    assert done.status == "completed", {k: r.error for k, r in done.results.items() if r.error}
    [call] = [args for name, args in run.tools.calls if name == "github.openPR"]
    body: JsonValue = call["body"]
    assert isinstance(body, str)
    assert "## Review notes" in body and "form.py:3" in body and "Name this." in body
    assert "notes_from" not in call
