"""An orchestrator in a loop at runtime (6.9): a reviewer's rejection makes the hub plan again on
top of the merged work, and an approval ends the loop; on the fake runtime with a fake
integrator."""

import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import cast
from uuid import uuid4

import pytest
from pydantic import JsonValue

from agentic_engine.artifacts import InMemoryArtifactStore
from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.graph import WorkflowRunResult, resume_workflow, run_workflow
from agentic_engine.graph.compile import hub_instructions, hub_iteration_instructions, plan_key
from agentic_engine.policy import PLATFORM_POLICY, Policy
from agentic_engine.spec import OrchestratorNode, WorkflowSpec, iter_nodes
from agentic_runtime import AgentRequest, AgentRun, Message
from agentic_runtime.fake import ECHO_USAGE, Delay, FakeRuntime, Script

from .test_orchestrator import HUB, Desk, Review, agent, orchestrator, plan, saver, spec, task_of
from .test_orchestrator_integrate import WRITER, Merger, writing
from .test_orchestrator_replan import Replanner

REVIEWER = "reviewer"


class ReviewedTeam(Replanner):
    """A `Replanner` whose reviewer answers `verdicts` in turn, the last one again if asked
    more often."""

    def __init__(
        self,
        plans: Sequence[str],
        verdicts: Sequence[str],
        delays: Mapping[str, float] | None = None,
        scripts: Mapping[str, Script] | None = None,
        tools: Desk | None = None,
    ) -> None:
        super().__init__(plans, delays=delays, scripts=scripts, tools=tools)
        self._verdicts = list(verdicts)
        self.reviews: list[AgentRequest] = []

    def start(self, request: AgentRequest) -> AgentRun:
        if request.node_id != REVIEWER:
            return super().start(request)
        verdict = self._verdicts[min(len(self.reviews), len(self._verdicts) - 1)]
        self.reviews.append(request)
        self.requests.append(request)
        return FakeRuntime({REVIEWER: [Message(text=verdict), ECHO_USAGE]}).start(request)


def review_loop(*after: Mapping[str, object], max_iterations: int = 3) -> WorkflowSpec:
    """A loop around a writing orchestrator and a reviewer, until the reviewer says OK."""
    loop = {
        "type": "loop",
        "id": "review",
        "body": {
            "type": "sequence",
            "id": "pass",
            "steps": [orchestrator(WRITER), agent(REVIEWER)],
        },
        "until": 'last.startsWith("OK")',
        "max_iterations": max_iterations,
    }
    return spec(loop, *after)


async def run(
    flow: WorkflowSpec,
    team: ReviewedTeam,
    merger: Merger | None = None,
    sink: InMemoryEventSink | None = None,
    desk: Desk | None = None,
    policy: Policy = PLATFORM_POLICY,
    review: Review | None = None,
) -> WorkflowRunResult:
    return await run_workflow(
        flow,
        team,
        "the repo",
        sink=sink,
        checkpointer=saver(),
        policy=policy,
        artifacts=InMemoryArtifactStore(),
        tools=desk,
        review=review,
        integrator=merger,
    )


def payloads(sink: InMemoryEventSink, type: str) -> list[dict[str, JsonValue]]:
    return [e.payload for e in sink.events if e.type == type and e.node_id == HUB]


def hubs(team: ReviewedTeam) -> list[AgentRequest]:
    return [r for r in team.requests if r.node_id == HUB]


async def test_a_rejection_makes_the_hub_plan_again_on_top_of_the_merged_work() -> None:
    """Done when (6.9): a reviewer's rejection inside a loop makes the orchestrator plan again on
    top of the merged work, and an approval goes on to one branch to publish."""
    desk, merger, sink = Desk(), Merger(), InMemoryEventSink()
    team = ReviewedTeam(
        [plan("a", "b"), plan("c", reason="Address the review.")],
        ["CHANGES: b misses a test", "OK"],
        scripts=writing("a", "b", "c"),
        tools=desk,
    )

    result = await run(review_loop(), team, merger, sink, desk)

    assert result.status == "completed", result.results[HUB].error
    loop = result.results["review"]
    assert loop.data == {"stop_reason": "condition", "iterations": 2}
    # Iteration 2's hub gets the review and iteration 1's tasks, as data.
    first, second = hubs(team)
    node = _hub(review_loop())
    assert first.instructions.startswith(hub_instructions(node))
    assert second.instructions.startswith(hub_iteration_instructions(node))
    given = json.loads(second.input)
    assert given["input"] == "CHANGES: b misses a test"
    assert given["iteration"] == 2
    assert [(t["id"], t["iteration"], t["status"], t["output"]) for t in given["previous"]] == [
        ("a", 1, "completed", "fixed a"),
        ("b", 1, "completed", "fixed b"),
    ]
    # Its task starts from the integration branch, and the branch holds both iterations' work.
    assert merger.started == [["fix.c"]]
    assert merger.keys == [["fix.a", "fix.b"], ["fix.a", "fix.b", "fix.c"]]
    data = result.results[HUB].data
    assert data is not None
    assert data["writers"] == [HUB] and data["merged"] == ["a", "b", "c"]
    # Its output is all the work on the branch, so the reviewer sees every iteration's.
    assert result.results[HUB].text == "fixed a\n\nfixed b\n\nfixed c"
    assert data["iteration"] == 2 and data["tasks"] == [
        {"id": "c", "title": "Fix c", "instructions": "Fix module c."}
    ]
    # Each iteration's orchestrator events say which iteration they are of.
    planned = [
        (
            p["iteration"],
            [cast(dict[str, JsonValue], t)["id"] for t in cast(list[JsonValue], p["tasks"])],
        )
        for p in payloads(sink, "plan_made")
    ]
    assert planned == [(1, ["a", "b"]), (2, ["c"])]
    ended = sorted(
        (str(p["iteration"]), str(p["task_id"])) for p in payloads(sink, "task_completed")
    )
    assert ended == [("1", "a"), ("1", "b"), ("2", "c")]
    assert [(p["iteration"], p["merged"]) for p in payloads(sink, "branch_integrated")] == [
        (1, ["a", "b"]),
        (2, ["a", "b", "c"]),
    ]
    assert [p.get("iteration") for p in payloads(sink, "node_completed")] == [None, None]


def _hub(flow: WorkflowSpec) -> OrchestratorNode:
    found = next(n for _, n in iter_nodes(flow.root) if n.id == HUB)
    assert isinstance(found, OrchestratorNode)
    return found


async def test_a_gate_after_the_loop_shows_the_one_integration_branch() -> None:
    desk, merger, review = Desk(), Merger(), Review()
    team = ReviewedTeam(
        [plan("a"), plan("b")], ["CHANGES", "OK"], scripts=writing("a", "b"), tools=desk
    )
    gate = {"type": "gate", "id": "approve", "title": "Approve the work"}

    result = await run(review_loop(gate), team, merger, desk=desk, review=review)

    assert result.status == "waiting" and result.waiting_at == "approve"
    [asked] = review.asked
    assert HUB in asked and not any(w.startswith(f"{HUB}.") for w in asked)


async def test_an_approval_in_the_first_iteration_plans_once() -> None:
    desk, merger = Desk(), Merger()
    team = ReviewedTeam([plan("a")], ["OK"], scripts=writing("a"), tools=desk)

    result = await run(review_loop(), team, merger, desk=desk)

    assert result.status == "completed"
    assert len(hubs(team)) == 1 and merger.started == []
    assert result.results["review"].data == {"stop_reason": "condition", "iterations": 1}


async def test_max_iterations_ends_the_loop() -> None:
    desk, merger = Desk(), Merger()
    team = ReviewedTeam(
        [plan("a"), plan("b"), plan("c")], ["CHANGES"], scripts=writing("a", "b", "c"), tools=desk
    )

    result = await run(review_loop(max_iterations=2), team, merger, desk=desk)

    assert result.status == "completed"
    assert result.results["review"].data == {"stop_reason": "max_iterations", "iterations": 2}
    assert len(hubs(team)) == 2
    data = result.results[HUB].data
    assert data is not None and data["merged"] == ["a", "b"]


async def test_a_task_id_from_an_earlier_iteration_is_refused() -> None:
    desk, merger, sink = Desk(), Merger(), InMemoryEventSink()
    team = ReviewedTeam([plan("a"), plan("a")], ["CHANGES"], scripts=writing("a"), tools=desk)

    result = await run(review_loop(), team, merger, sink, desk)

    assert result.status == "failed"
    assert result.stopped_at == HUB
    assert result.results[HUB].error == f"the hub of {HUB!r} planned task 'a' again"
    assert result.results[HUB].data == {"iteration": 2}


async def test_an_empty_plan_in_a_later_iteration_completes_with_the_work_so_far() -> None:
    desk, merger = Desk(), Merger()
    team = ReviewedTeam([plan("a"), plan()], ["CHANGES", "OK"], scripts=writing("a"), tools=desk)

    result = await run(review_loop(), team, merger, desk=desk)

    assert result.status == "completed"
    data = result.results[HUB].data
    assert data is not None
    assert data["tasks"] == [] and data["merged"] == ["a"] and data["writers"] == [HUB]


async def test_every_iterations_agents_count_on_agents_spawned() -> None:
    # Iteration 1: hub, a and b, reviewer (4). Iteration 2: hub and c take it to 6, over 5.
    policy = PLATFORM_POLICY.model_copy(update={"agents_spawned": 5})
    desk, merger, sink = Desk(), Merger(), InMemoryEventSink()
    team = ReviewedTeam(
        [plan("a", "b"), plan("c")], ["CHANGES"], scripts=writing("a", "b", "c"), tools=desk
    )

    result = await run(review_loop(), team, merger, sink, desk, policy=policy)

    assert result.status == "failed" and result.stopped_at == HUB
    [over] = payloads(sink, "policy_limit_exceeded")
    assert over == {"limit": "agents_spawned", "value": 5, "observed": 6}
    assert merger.started == []


def test_plans_are_kept_per_iteration() -> None:
    assert plan_key(HUB, None) == HUB
    assert plan_key(HUB, 2) == f"{HUB}#2"


class SecondIterationTaskDone(InMemoryEventSink):
    """Flags once task `task_id` of iteration 2 ended."""

    def __init__(self, task_id: str) -> None:
        super().__init__()
        self.task_id = task_id
        self.done = asyncio.Event()

    async def emit(self, event: RunEvent) -> None:
        await super().emit(event)
        if (
            event.type == "task_completed"
            and event.payload.get("iteration") == 2
            and event.payload["task_id"] == self.task_id
        ):
            self.done.set()


async def test_a_run_cut_off_in_iteration_2_resumes_there_without_asking_the_hub_again() -> None:
    """AC-8 inside a looped orchestrator: iteration 1's plan and merges are kept, and iteration
    2's plan is not asked for again; only its unfinished task runs."""
    flow, checkpointer, run_id = review_loop(), saver(), uuid4()
    desk, merger = Desk(), Merger()
    slow = {f"{HUB}.c": [Delay(60), *writing("c")[f"{HUB}.c"]]}
    first = ReviewedTeam(
        [plan("a"), plan("b", "c")],
        ["CHANGES"],
        scripts={**writing("a", "b"), **slow},
        tools=desk,
    )
    sink = SecondIterationTaskDone("b")
    task = asyncio.create_task(
        run_workflow(
            flow,
            first,
            "go",
            run_id=run_id,
            sink=sink,
            checkpointer=checkpointer,
            tools=desk,
            integrator=merger,
        )
    )
    await asyncio.wait_for(sink.done.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    second = ReviewedTeam(
        [plan("x"), plan("y")], ["OK"], scripts=writing("a", "b", "c"), tools=desk
    )
    result = await resume_workflow(
        flow,
        second,
        "go",
        run_id=run_id,
        sink=sink,
        checkpointer=checkpointer,
        next_seq=sink.events[-1].seq + 1,
        attempt=2,
        tools=desk,
        integrator=merger,
    )

    assert result.status == "completed", result.results[HUB].error
    assert hubs(second) == []
    assert [task_of(r) for r in second.workers if r.node_id != REVIEWER] == ["c"]
    data = result.results[HUB].data
    assert data is not None and data["merged"] == ["a", "b", "c"]
    assert result.results["review"].data == {"stop_reason": "condition", "iterations": 2}


async def test_a_run_cut_off_once_iteration_2s_tasks_ended_goes_on_to_the_review() -> None:
    flow, checkpointer, run_id = review_loop(), saver(), uuid4()
    desk, merger = Desk(), Merger()
    first = ReviewedTeam(
        [plan("a"), plan("b", "c")], ["CHANGES"], scripts=writing("a", "b", "c"), tools=desk
    )
    sink = SecondIterationTaskDone("c")
    task = asyncio.create_task(
        run_workflow(
            flow,
            first,
            "go",
            run_id=run_id,
            sink=sink,
            checkpointer=checkpointer,
            tools=desk,
            integrator=merger,
        )
    )
    await asyncio.wait_for(sink.done.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    second = ReviewedTeam([plan("x")], ["OK"], scripts=writing("a", "b", "c"), tools=desk)
    result = await resume_workflow(
        flow,
        second,
        "go",
        run_id=run_id,
        sink=sink,
        checkpointer=checkpointer,
        next_seq=sink.events[-1].seq + 1,
        attempt=2,
        tools=desk,
        integrator=merger,
    )

    assert result.status == "completed", result.results[HUB].error
    assert [r.node_id for r in second.requests] == [REVIEWER]
    assert result.results["review"].data == {"stop_reason": "condition", "iterations": 2}
