"""The orchestrator's replan policy at runtime (6.2): a failed worker makes the hub plan the
remaining work again, within limits, on the fake runtime, with no network."""

import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import cast
from uuid import uuid4

import pytest
from pydantic import JsonValue

from agentic_engine.events import InMemoryEventSink
from agentic_engine.graph import resume_workflow, run_workflow
from agentic_engine.graph.compile import hub_replan_instructions, recursion_limit, task_round
from agentic_engine.policy import PLATFORM_POLICY
from agentic_engine.spec import OrchestratorNode
from agentic_runtime import AgentRequest, AgentRun, Message
from agentic_runtime.fake import CallTool, Script

from .test_orchestrator import (
    HUB,
    Desk,
    TaskDoneSink,
    Team,
    agent,
    of,
    orchestrator,
    plan,
    run,
    saver,
    spec,
    task_of,
)


class Replanner(Team):
    """A `Team` whose hub answers `plans` in turn, the last one again if asked more often."""

    def __init__(
        self,
        plans: Sequence[str],
        delays: Mapping[str, float] | None = None,
        fail: Sequence[str] = (),
        scripts: Mapping[str, Script] | None = None,
        tools: Desk | None = None,
    ) -> None:
        super().__init__(plans[0], delays=delays, fail=fail, scripts=scripts, tools=tools)
        self._plans = list(plans)

    def start(self, request: AgentRequest) -> AgentRun:
        if request.node_id == HUB:
            self._plan = self._plans[min(len(self.hubs), len(self._plans) - 1)]
        return super().start(request)

    @property
    def hubs(self) -> list[AgentRequest]:
        return [r for r in self.requests if r.node_id == HUB]


def replanning(
    body: Mapping[str, object], max_rounds: int = 1, **fields: object
) -> dict[str, object]:
    return orchestrator(body, replan={"on": "failure", "max_rounds": max_rounds}, **fields)


def ends(sink: InMemoryEventSink) -> dict[str, tuple[JsonValue, JsonValue]]:
    """Each task's end: its status and error."""
    return {
        str(p["task_id"]): (p["status"], p.get("error"))
        for t, p in of(sink.events)
        if t == "task_completed"
    }


async def test_a_failed_worker_triggers_a_replan_and_the_orchestrator_completes() -> None:
    """Done when (6.2): a failed worker triggers a replan within limits."""
    team = Replanner(
        [plan("a", "b", "c"), plan("b2", reason="Retry b another way.")],
        delays={"a": 0.05, "c": 0.05},
        fail=["b"],
    )
    sink = InMemoryEventSink()

    result = await run(spec(replanning(agent("worker"))), team, sink)

    assert result.status == "completed", result.results[HUB].error
    assert len(team.hubs) == 2
    # The others were not cancelled: they finished, and their work is kept.
    assert ends(sink) == {
        "a": ("completed", None),
        "b": ("failed", "worker failed: cannot fix b"),
        "c": ("completed", None),
        "b2": ("completed", None),
    }
    events = dict(of(sink.events))
    assert events["replan_started"] == {
        "round": 2,
        "failed": [{"id": "b", "error": "worker failed: cannot fix b"}],
        "dropped": [],
    }
    assert events["plan_made"] == {
        "tasks": [{"id": "b2", "title": "Fix b2"}],
        "reason": "Retry b another way.",
        "round": 2,
    }
    assert events["node_completed"] == {"tasks": 4, "completed": 3, "rounds": 2}
    # The hub replans once the round settled: after every first-round task ended.
    types = [t for t, _ in of(sink.events)]
    assert types[: types.index("replan_started")].count("task_completed") == 3
    # The new round's task is indexed after the first round's.
    items = {str(e.payload.get("item")) for e in sink.events if e.node_id == "worker"}
    assert items == {"0", "1", "2", "3"}
    assert result.results[HUB].text == "worker:a\n\nworker:c\n\nworker:b2"
    data = result.results[HUB].data
    assert data is not None
    assert [cast(dict[str, JsonValue], t)["id"] for t in cast(list[JsonValue], data["tasks"])] == [
        "a",
        "c",
        "b2",
    ]
    assert data["rounds"] == 2
    assert [
        (p["id"], p["round"], p["status"]) for p in cast(list[dict[str, JsonValue]], data["plan"])
    ] == [("a", 1, "completed"), ("b", 1, "failed"), ("c", 1, "completed"), ("b2", 2, "completed")]


async def test_tasks_not_started_are_dropped_and_the_hub_is_told() -> None:
    team = Replanner([plan("a", "b", "c"), plan("d")], fail=["a"])
    sink = InMemoryEventSink()

    result = await run(spec(replanning(agent("worker"), max_concurrency=1)), team, sink)

    assert result.status == "completed"
    assert [task_of(r) for r in team.workers] == ["a", "d"]
    assert ends(sink)["b"] == ("dropped", None)
    assert ends(sink)["c"] == ("dropped", None)
    assert dict(of(sink.events))["replan_started"]["dropped"] == ["b", "c"]
    told = json.loads(team.hubs[1].input)
    assert told["input"] == "the repo"
    assert told["round"] == 2
    assert [(t["id"], t["status"], t.get("error")) for t in told["tasks"]] == [
        ("a", "failed", "worker failed: cannot fix a"),
        ("b", "dropped", None),
        ("c", "dropped", None),
    ]


async def test_the_failure_reaches_the_hub_as_data_never_as_instructions() -> None:
    team = Replanner([plan("a", "b"), plan("b2")], fail=["b"])
    node = OrchestratorNode.model_validate(replanning(agent("worker")))

    await run(spec(replanning(agent("worker"))), team)

    first, second = team.hubs
    assert second.role == first.role == "Lead"
    assert second.instructions.startswith(hub_replan_instructions(node, 3))
    assert "cannot fix" not in second.instructions
    told = json.loads(second.input)
    assert [(t["id"], t["status"], t.get("output")) for t in told["tasks"]] == [
        ("a", "completed", "worker:a"),
        ("b", "failed", None),
    ]
    assert told["tasks"][1]["error"] == "worker failed: cannot fix b"


async def test_when_the_rounds_are_used_up_the_orchestrator_fails_naming_the_task() -> None:
    team = Replanner([plan("a"), plan("a2")], fail=["a", "a2"])
    sink = InMemoryEventSink()

    result = await run(spec(replanning(agent("worker"))), team, sink)

    assert result.status == "failed"
    assert result.stopped_at == HUB
    assert len(team.hubs) == 2
    assert result.results[HUB].error == "task 'a2' worker failed: cannot fix a2 (after 1 replan)"
    assert [t for t, _ in of(sink.events)].count("replan_started") == 1


async def test_in_the_last_round_a_failure_cancels_the_others_again() -> None:
    """With no replan left, waiting for the others to finish would only add cost."""
    team = Replanner([plan("a"), plan("b", "c")], delays={"c": 5}, fail=["a", "b"])
    sink = InMemoryEventSink()

    result = await asyncio.wait_for(run(spec(replanning(agent("worker"))), team, sink), 3)

    assert result.status == "failed"
    assert ends(sink)["c"] == ("cancelled", "cancelled: another task did not complete")


async def test_the_hub_may_replan_up_to_max_rounds() -> None:
    team = Replanner([plan("a"), plan("a2"), plan("a3")], fail=["a", "a2"])
    sink = InMemoryEventSink()

    result = await run(spec(replanning(agent("worker"), max_rounds=2)), team, sink)

    assert result.status == "completed"
    assert result.results[HUB].text == "worker:a3"
    assert dict(of(sink.events))["node_completed"] == {"tasks": 3, "completed": 1, "rounds": 3}


async def test_a_replan_over_agents_spawned_stops_cleanly() -> None:
    """The hub and two tasks are 3 agents; the replan's hub 4 (the limit); its two tasks 6."""
    team = Replanner([plan("a", "b"), plan("c", "d")], fail=["b"])
    sink = InMemoryEventSink()
    policy = PLATFORM_POLICY.model_copy(update={"agents_spawned": 4})

    result = await run(spec(replanning(agent("worker"))), team, sink, policy=policy)

    assert result.status == "failed"
    assert sorted(task_of(r) for r in team.workers) == ["a", "b"]
    limits = [p for t, p in of(sink.events) if t == "policy_limit_exceeded"]
    assert limits == [{"limit": "agents_spawned", "value": 4, "observed": 6}]
    assert [t for t, _ in of(sink.events)][-1] == "node_failed"


async def test_the_replanning_hub_itself_counts_as_spawned() -> None:
    team = Replanner([plan("a", "b"), plan("c")], fail=["b"])
    sink = InMemoryEventSink()
    policy = PLATFORM_POLICY.model_copy(update={"agents_spawned": 3})

    result = await run(spec(replanning(agent("worker"))), team, sink, policy=policy)

    assert result.status == "failed"
    assert len(team.hubs) == 1
    types = [t for t, _ in of(sink.events)]
    assert types[-3:] == ["replan_started", "policy_limit_exceeded", "node_failed"]
    assert types.count("node_started") == 1


async def test_a_replan_cannot_plan_past_max_workers() -> None:
    """`max_workers` 2 with one task completed leaves room for one more."""
    team = Replanner([plan("a", "b"), plan("c", "d")], fail=["b"])
    sink = InMemoryEventSink()

    result = await run(spec(replanning(agent("worker"), max_workers=2)), team, sink)

    assert result.status == "failed"
    assert "port" in dict(of(sink.events))["node_failed"]
    assert sorted(task_of(r) for r in team.workers) == ["a", "b"]


@pytest.mark.parametrize("again", ["a", "b"], ids=["completed", "failed"])
async def test_a_replan_cannot_reuse_a_task_id(again: str) -> None:
    team = Replanner([plan("a", "b"), plan(again)], fail=["b"])
    sink = InMemoryEventSink()

    result = await run(spec(replanning(agent("worker"))), team, sink)

    assert result.status == "failed"
    assert dict(of(sink.events))["node_failed"] == {
        "error": f"the hub of {HUB!r} planned task {again!r} again"
    }


async def test_an_empty_replan_keeps_what_completed() -> None:
    team = Replanner([plan("a", "b"), plan()], fail=["b"])
    result = await run(spec(replanning(agent("worker"))), team)
    assert result.status == "completed"
    assert result.results[HUB].text == "worker:a"


async def test_an_empty_replan_with_nothing_done_fails_with_the_last_error() -> None:
    team = Replanner([plan("a"), plan()], fail=["a"])
    result = await run(spec(replanning(agent("worker"))), team)
    assert result.status == "failed"
    assert result.results[HUB].error == "task 'a' worker failed: cannot fix a (after 1 replan)"


async def test_without_replan_a_failure_still_fails_the_orchestrator() -> None:
    team = Replanner([plan("a", "b"), plan("c")], fail=["b"])
    sink = InMemoryEventSink()
    result = await run(spec(orchestrator(agent("worker"))), team, sink)
    assert result.status == "failed"
    assert len(team.hubs) == 1
    assert "replan_started" not in [t for t, _ in of(sink.events)]


async def test_a_reduce_sees_only_the_completed_tasks_by_id() -> None:
    reduce = {
        "type": "reduce",
        "id": "join",
        "from": HUB,
        "strategy": "agent",
        "agent": {"role": "Editor", "instructions": "Join."},
    }
    team = Replanner(
        [plan("a", "b"), plan("b2")], fail=["b"], scripts={"join": [Message(text="joined")]}
    )

    result = await run(spec(replanning(agent("worker")), reduce), team)

    assert result.status == "completed"
    [joiner] = [r for r in team.requests if r.node_id == "join"]
    assert [i["item"]["id"] for i in json.loads(joiner.input)] == ["a", "b2"]


async def test_a_replanned_writer_gets_a_new_branch_and_only_completed_ones_are_kept() -> None:
    desk = Desk()
    writer = agent("fixer", tools=["repo.write_file"])
    write: Script = [CallTool("repo.write_file", {"path": "a.py"}), Message(text="ok")]
    scripts: dict[str, Script] = {
        f"{HUB}.a": write,
        f"{HUB}.b2": write,
    }
    team = Replanner([plan("a", "b"), plan("b2")], fail=["b"], scripts=scripts, tools=desk)

    result = await run(spec(replanning(writer)), team, tools=desk)

    assert result.status == "completed"
    assert sorted(str(n) for _, n in desk.calls) == ["fix.a", "fix.b2"]
    assert sorted(r.node_id for r in team.workers) == ["fix.a", "fix.b", "fix.b2"]
    data = result.results[HUB].data
    assert data is not None and data["writers"] == ["fix.a", "fix.b2"]


async def test_resume_after_a_replan_never_asks_the_hub_again() -> None:
    """AC-8 across a replan: a run cut off after round 2 was planned and its task `c` finished
    runs only `d`, from the same plans."""
    flow = spec(replanning(agent("worker")))
    checkpointer, run_id = saver(), uuid4()
    first = Replanner([plan("a", "b"), plan("c", "d")], fail=["b"], delays={"d": 60})
    sink = TaskDoneSink(2)
    task = asyncio.create_task(
        run_workflow(flow, first, "go", run_id=run_id, sink=sink, checkpointer=checkpointer)
    )
    await asyncio.wait_for(sink.done.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    second = Replanner([plan("x", "y")])  # a hub asked again would plan other tasks
    result = await resume_workflow(
        flow,
        second,
        "go",
        run_id=run_id,
        sink=sink,
        checkpointer=checkpointer,
        next_seq=sink.events[-1].seq + 1,
        attempt=2,
    )

    assert result.status == "completed", result.results[HUB].error
    assert second.hubs == []
    assert [task_of(r) for r in second.workers] == ["d"]
    assert result.results[HUB].text == "worker:a\n\nworker:c\n\nworker:d"


def test_a_task_checkpointed_before_replan_is_from_the_first_round() -> None:
    assert task_round({"id": "a", "title": "A", "instructions": "Do."}) == 1
    assert task_round({"id": "a", "title": "A", "instructions": "Do.", "round": 3}) == 3


def test_each_replan_round_takes_three_more_steps() -> None:
    flow = spec(replanning(agent("worker"), max_rounds=2))
    assert recursion_limit(flow) == 3 + 6 + 10
