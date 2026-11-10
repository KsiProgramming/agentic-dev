"""AC-2 end to end on the engine (6.8): the "Plan, build and review" flow (a parallel, an
orchestrator in a review loop, a gate and a pull request) runs on the fake runtime with a fake
integrator. The reviewer sends the work back once, the gate is approved and one pull request is
opened. The tests check what every agent receives (lessons rule 1), not only the outcome."""

import json
from collections.abc import Sequence
from uuid import uuid4

from pydantic import JsonValue

from agentic_engine.agent import RunContext
from agentic_engine.artifacts import InMemoryArtifactStore
from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.gate import FileChange, FileEdit, GateDecision
from agentic_engine.graph import WorkflowRunResult, resume_workflow, run_workflow
from agentic_engine.spec import READ_TOOLS, WorkflowSpec
from agentic_engine.templates import PlanBuildReviewParams, build_plan_build_review_spec
from agentic_runtime import AgentRequest, AgentRun, Message, ToolOutput
from agentic_runtime.fake import ECHO_USAGE, CallTool, Delay, FakeRuntime, Step
from agentic_runtime.testing import ScriptedToolExecutor

from .test_gate import saver
from .test_orchestrator_integrate import Merger

REQUEST = "Add input validation to the signup form, with tests."
CHANGES = json.dumps({"verdict": "changes", "feedback": "The email check has no test."})
OK = json.dumps({"verdict": "ok", "feedback": "Ready."})
PULL: dict[str, JsonValue] = {
    "url": "https://github.com/acme/shop/pull/12",
    "number": 12,
    "head": "agent/run/implement",
    "base": "main",
    "commit": "c" * 40,
}


def plan(*tasks: str, reason: str) -> str:
    return json.dumps(
        {
            "tasks": [
                {"id": t, "title": f"Do {t}", "instructions": f"Change {t}.py only."} for t in tasks
            ],
            "reason": reason,
        }
    )


PLANS = [plan("form", "api", reason="One task per file."), plan("tests", reason="Add the test.")]


ROLES = {
    "Code analyst": "code_analyst",
    "Test analyst": "test_analyst",
    "Lead engineer": "implement",
    "Software engineer": "engineer",
    "Release writer": "synthesizer",
    "Senior reviewer": "reviewer",
}
"""Each agent of the flow by its role: after `implement` merged its tasks, the readers' requests
go out as `implement` (lessons rule 5), so the node id alone does not say which agent it is."""


class Team:
    """The flow's agents: analysts and the synthesizer answer a note, the lead `PLANS` in turn,
    each engineer writes its task's file, and the reviewer reads a file and answers `verdicts` in
    turn."""

    def __init__(self, tools: ScriptedToolExecutor, verdicts: Sequence[str] = (CHANGES, OK)):
        self.tools = tools
        self.verdicts = list(verdicts)
        self.requests: list[AgentRequest] = []

    def start(self, request: AgentRequest) -> AgentRun:
        agent = ROLES[request.role]
        self.requests.append(request)
        asked = len(self.of(agent))
        script: list[Step]
        if agent == "implement":
            script = [Message(text=PLANS[min(asked - 1, len(PLANS) - 1)])]
        elif agent == "engineer":
            task = request.node_id.removeprefix("implement.")
            # A fixed order of events: form's engineer ends before api's.
            delay = Delay({"form": 0.05, "api": 0.15}.get(task, 0.05))
            script = [delay, CallTool("repo.write_file", {"path": f"{task}.py", "content": "x"})]
            script.append(Message(text=f"Changed {task}.py."))
        elif agent == "reviewer":
            verdict = self.verdicts[min(asked - 1, len(self.verdicts) - 1)]
            script = [CallTool("repo.read_file", {"path": "form.py"}), Message(text=verdict)]
        elif agent == "synthesizer":
            script = [CallTool("repo.read_file", {"path": "form.py"})]
            script.append(Message(text=f"## Signup validation (pass {asked})"))
        else:
            script = [Delay(0.05 if agent == "code_analyst" else 0.1)]
            script.append(Message(text=f"{agent}: notes on the signup form."))
        node = request.node_id
        return FakeRuntime({node: [*script, ECHO_USAGE]}, tools=self.tools).start(request)

    def of(self, agent: str) -> list[AgentRequest]:
        """The requests of `agent` (a key of `ROLES`' values), in order."""
        return [r for r in self.requests if ROLES[r.role] == agent]


class Review:
    """A gate review that records which writers each gate was asked about."""

    def __init__(self) -> None:
        self.asked: list[list[str]] = []

    async def changes(self, ran: Sequence[str]) -> list[FileChange]:
        self.asked.append(list(ran))
        return [
            FileChange(node_id=n, path="form.py", status="modified", editable=True, after="x")
            for n in ran
            if n == "implement"
        ]

    async def apply(self, gate_id: str, edits: Sequence[FileEdit]) -> dict[str, str]:
        return {}


class Ac2Run:
    """One run of the flow, across its pause at the gate."""

    def __init__(self, spec: WorkflowSpec | None = None, verdicts: Sequence[str] = (CHANGES, OK)):
        self.spec = spec or build_plan_build_review_spec(PlanBuildReviewParams())
        self.tools = ScriptedToolExecutor(
            {
                "repo.read_file": "x = 1",
                "repo.write_file": "wrote",
                "github.openPR": ToolOutput(text="opened #12", data=PULL),
            }
        )
        self.team = Team(self.tools, verdicts)
        self.merger = Merger()
        self.review = Review()
        self.sink = InMemoryEventSink()
        self.checkpointer = saver()
        self.artifacts = InMemoryArtifactStore()
        self.context = RunContext(repo="acme/shop", request=REQUEST)
        self.run_id = uuid4()
        self.attempt = 1

    async def start(self) -> WorkflowRunResult:
        return await run_workflow(
            self.spec,
            self.team,
            REQUEST,
            run_id=self.run_id,
            sink=self.sink,
            checkpointer=self.checkpointer,
            tools=self.tools,
            review=self.review,
            artifacts=self.artifacts,
            integrator=self.merger,
            context=self.context,
        )

    async def decide(self, decision: GateDecision) -> WorkflowRunResult:
        self.attempt += 1
        return await resume_workflow(
            self.spec,
            self.team,
            REQUEST,
            run_id=self.run_id,
            sink=self.sink,
            checkpointer=self.checkpointer,
            next_seq=self.sink.events[-1].seq + 1,
            attempt=self.attempt,
            tools=self.tools,
            decision=decision,
            review=self.review,
            artifacts=self.artifacts,
            integrator=self.merger,
            context=self.context,
        )

    async def to_the_end(self) -> WorkflowRunResult:
        paused = await self.start()
        assert paused.status == "waiting" and paused.waiting_at == "approve_pr", {
            k: r.error for k, r in paused.results.items() if r.error
        }
        return await self.decide(GateDecision(decision="approve"))

    def calls_by(self, name: str) -> list[str | None]:
        """The node id each call to tool `name` went out as, in order."""
        return [
            n for (t, _), n in zip(self.tools.calls, self.tools.node_ids, strict=True) if t == name
        ]

    def last(self, kind: str) -> RunEvent:
        return next(e for e in reversed(self.sink.events) if e.type == kind)


async def test_the_flow_runs_two_passes_and_opens_one_pull_request() -> None:
    """Done when (6.8), on the engine: the drawn flow runs as drawn. Both analysts run, the
    reviewer sends the work back once, the second pass builds on the first, and after the gate
    one pull request is opened from the integration branch with the synthesizer's description."""
    run = Ac2Run()

    done = await run.to_the_end()

    assert done.status == "completed", {k: r.error for k, r in done.results.items() if r.error}
    assert done.results["review_loop"].data == {"stop_reason": "condition", "iterations": 2}
    assert run.merger.merged == ["implement.form", "implement.api", "implement.tests"]
    [call] = [args for name, args in run.tools.calls if name == "github.openPR"]
    assert call["from_node"] == "implement"
    body = call["body"]
    assert isinstance(body, str) and body.endswith("## Signup validation (pass 2)")
    assert run.last("pr_opened").payload == PULL


async def test_what_every_agent_receives() -> None:
    """Lessons rule 1: each agent's input, tools, context and the node its calls go out as."""
    run = Ac2Run()
    await run.to_the_end()
    team = run.team

    # Every agent is told the repo and the request, whatever its input (6.8).
    assert {r.context for r in team.requests} == {run.context.text()}
    assert f"<request>\n{REQUEST}\n</request>" in run.context.text()
    # The analysts get the request as their input and only read tools.
    for analyst in ("code_analyst", "test_analyst"):
        [request] = team.of(analyst)
        assert request.input == REQUEST
        assert set(request.tools) <= READ_TOOLS
    # Pass 1's lead gets both analyses; pass 2's the review and pass 1's tasks. Read tools only.
    first, second = team.of("implement")
    assert "code_analyst: notes" in first.input and "test_analyst: notes" in first.input
    given = json.loads(second.input)
    assert json.loads(given["input"]) == json.loads(CHANGES)
    assert [t["id"] for t in given["previous"]] == ["form", "api"]
    assert set(first.tools) <= READ_TOOLS and set(second.tools) <= READ_TOOLS
    # Each engineer gets its task, has the write tools and writes on its task's branch.
    engineers = team.of("engineer")
    assert sorted(r.node_id for r in engineers) == [
        "implement.api",
        "implement.form",
        "implement.tests",
    ]
    for request in engineers:
        assert json.loads(request.input)["task"]["id"] == request.node_id.removeprefix("implement.")
        assert {"repo.write_file", "repo.commit"} <= set(request.tools)
    assert sorted(n or "" for n in run.calls_by("repo.write_file")) == [
        "implement.api",
        "implement.form",
        "implement.tests",
    ]
    # The synthesizer and the reviewer read the integration branch (lessons rule 5).
    assert run.calls_by("repo.read_file") == ["implement"] * 4
    for agent in ("synthesizer", "reviewer"):
        assert [r.node_id for r in team.of(agent)] == ["implement", "implement"]
        assert all(set(r.tools) <= READ_TOOLS for r in team.of(agent))
    # The gate shows the integration branch as the one writer.
    [asked] = run.review.asked
    assert "implement" in asked and not any(w.startswith("implement.") for w in asked)


async def test_a_reviewer_who_never_approves_still_reaches_the_gate_after_the_last_pass() -> None:
    run = Ac2Run(build_plan_build_review_spec(PlanBuildReviewParams(max_passes=2)), [CHANGES])

    paused = await run.start()

    assert paused.status == "waiting" and paused.waiting_at == "approve_pr"
    assert paused.results["review_loop"].data == {"stop_reason": "max_iterations", "iterations": 2}


async def test_the_flow_runs_on_the_stacks_fake_agents() -> None:
    """The e2e stack's agents echo, fitted to a typed node's schema (6.8): the hub plans one task
    and the reviewer answers `ok`, so the drawn flow runs to its pull request with no script."""
    run = Ac2Run()
    run.tools = ScriptedToolExecutor(
        {
            **{name: "ok" for name in ("repo.list_files", "repo.read_file", "repo.search")},
            "repo.write_file": "wrote",
            "repo.commit": "committed",
            "github.openPR": ToolOutput(text="opened #12", data=PULL),
        }
    )
    run.team = FakeRuntime(tools=run.tools, fit_schemas=True)  # type: ignore[assignment]

    done = await run.to_the_end()

    assert done.status == "completed", {k: r.error for k, r in done.results.items() if r.error}
    assert done.results["review_loop"].data == {"stop_reason": "condition", "iterations": 1}
    assert run.merger.merged == ["implement.fake"]
    assert run.last("pr_opened").payload == PULL
