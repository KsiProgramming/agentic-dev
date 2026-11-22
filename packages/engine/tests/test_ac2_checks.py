"""The "Plan, build and review" flow with `checks` (13.3): the engine builds and tests the merged
work before the gate. A failing test sends the lead back with the failures, and a passing change
reaches the gate with its pack. The tests check what the lead receives and what the checks run on
(lessons rule 1), not only the outcome."""

import json

from pydantic import JsonValue

from agentic_engine.gate import GateDecision
from agentic_engine.templates import PlanBuildReviewParams, build_plan_build_review_spec
from agentic_runtime import ToolOutput

from .test_ac2 import OK, PULL, Ac2Run
from .test_evidence_gate import FAILING, PASSING, Checks, lint


class AcChecks(Checks):
    """The flow's repo tools and the pull request, plus the checks' two tools."""

    def __init__(self, tests: list[ToolOutput]) -> None:
        super().__init__(tests, [lint()], lint())
        self._tools["repo.read_file"] = "x = 1"
        self._tools["github.openPR"] = ToolOutput(text="opened #12", data=PULL)


def checked_run(tests: list[ToolOutput]) -> tuple[Ac2Run, AcChecks]:
    spec = build_plan_build_review_spec(PlanBuildReviewParams(max_passes=3, checks=True))
    run = Ac2Run(spec, [OK])
    tools = AcChecks(tests)
    run.tools = tools
    run.team.tools = tools
    return run, tools


async def test_a_failing_test_sends_the_lead_back_and_a_passing_change_reaches_the_gate() -> None:
    run, _ = checked_run([FAILING, PASSING])

    paused = await run.start()

    assert paused.status == "waiting" and paused.waiting_at == "approve_pr", {
        k: r.error for k, r in paused.results.items() if r.error
    }
    decided = [e.payload for e in run.sink.events if e.type == "gate_decided"]
    assert [d.get("source") for d in decided] == ["checks"]  # the pass-1 send-back, no person
    waiting = [e for e in run.sink.events if e.type == "gate_waiting"]
    assert len(waiting) == 1  # the person is asked once, on pass 2
    pack = waiting[0].payload["evidence"]
    assert isinstance(pack, dict)
    assert {c["kind"]: c["status"] for c in pack["checks"]} == {  # type: ignore[index]
        "build": "passed",
        "tests": "passed",
        "analyzers": "passed",
    }
    done = await run.decide(GateDecision(decision="approve"))
    assert done.status == "completed"
    assert done.results["review_loop"].data == {"stop_reason": "condition", "iterations": 2}
    assert run.last("pr_opened").payload == PULL


async def test_the_second_pass_lead_is_handed_the_failures_and_the_checks_ran_on_the_merge() -> (
    None
):
    run, tools = checked_run([FAILING, PASSING])
    await run.start()

    first, second = run.team.of("implement")

    assert "## Tests" in json.loads(second.input)["input"]
    assert "tests failed (1 of 3)" in json.loads(second.input)["input"]
    assert "sum > adds" in json.loads(second.input)["input"]
    assert "## Tests" not in first.input
    # Each pass checked the orchestrator's integration branch, not a task's, and the base once.
    runs: list[tuple[str, dict[str, JsonValue]]] = [(n, a) for n, a, _ in tools.jobs]
    assert [a for n, a in runs if n == "build.test"] == [
        {"path": ".", "node": "implement"},
        {"path": ".", "node": "implement"},
    ]
    assert [a for n, a in runs if n == "scan.lint" and "node" not in a] == [{"path": "."}]


async def test_without_a_pass_to_go_back_to_the_last_pass_reaches_a_person() -> None:
    spec = build_plan_build_review_spec(PlanBuildReviewParams(max_passes=2, checks=True))
    run = Ac2Run(spec, [OK])
    tools = AcChecks([FAILING])
    run.tools = tools
    run.team.tools = tools

    paused = await run.start()

    # Pass 1 was sent back; pass 2 is the last, so it pauses with the failing pack.
    assert paused.status == "waiting" and paused.waiting_at == "approve_pr"
    waiting = [e for e in run.sink.events if e.type == "gate_waiting"]
    pack = waiting[-1].payload["evidence"]
    assert isinstance(pack, dict) and pack["rounds_left"] == 0
