"""A run that asked a question waits for the answer (7.9): `answer_arrived` continues it once,
a person's decision cannot, and an unanswered wait expires with its own reason."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.agent import IssueBrief, RunContext
from agentic_engine.gate import GateDecision
from agentic_engine.graph import checkpoint_serde, resume_workflow, run_workflow
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import ToolOutput
from agentic_runtime.fake import FakeRuntime
from agentic_runtime.testing import ScriptedToolExecutor
from agentic_store import (
    ANSWER_DECIDER,
    ANSWERS_EXPIRED_REASON,
    Approval,
    NotAGateError,
    PostgresEventSink,
    Run,
    answer_arrived,
    create_run,
    expire_gates,
    pending_decision,
    record_approval,
    waiting_runs,
)

pytestmark = pytest.mark.integration

CLOUD = "00000000-0000-0000-0000-0000000c10d0"
BRIEF = IssueBrief(key="KAN-5", url="https://acme.atlassian.net/browse/KAN-5", project="KAN")
ISSUE = {"cloud_id": CLOUD, "site": "acme.atlassian.net", "key": "KAN-5", "url": BRIEF.url}


def spec() -> WorkflowSpec:
    return parse_spec(
        {
            "spec_version": "0",
            "id": "waits",
            "name": "Waits",
            "root": {
                "type": "sequence",
                "id": "main",
                "steps": [
                    {"type": "gate", "id": "post", "title": "Post?"},
                    {
                        "type": "tool",
                        "id": "ask",
                        "tool": "jira.comment",
                        "args": {"issue_from": "request", "body": "Which one?"},
                    },
                    {"type": "wait_for", "id": "wait", "title": "Waiting", "after_from": "ask"},
                    {"type": "agent", "id": "build", "role": "B", "instructions": "Go."},
                ],
            },
        }
    )


async def waiting_run(sessions: async_sessionmaker[AsyncSession]) -> UUID:
    """A run paused at `wait` (the post gate approved), on issue KAN-5."""
    workflow = spec()
    run_id = await create_run(sessions, workflow, "KAN-5", jira_issue=ISSUE)
    common = {
        "run_id": run_id,
        "sink": PostgresEventSink(sessions),
        "checkpointer": InMemorySaver(serde=checkpoint_serde()),
        "tools": ScriptedToolExecutor(
            {"jira.comment": ToolOutput(text="posted", data={"comment_id": "10001"})}
        ),
        "context": RunContext(request="KAN-5").model_copy(update={"issue": BRIEF}),
    }
    runtime = FakeRuntime({})
    first = await run_workflow(workflow, runtime, "KAN-5", **common)  # type: ignore[arg-type]
    assert first.waiting_at == "post"
    seq = await _next_seq(sessions, run_id)
    second = await resume_workflow(
        workflow,
        runtime,
        "KAN-5",
        next_seq=seq,
        attempt=2,
        decision=GateDecision(decision="approve"),
        **common,  # type: ignore[arg-type]
    )
    assert second.waiting_at == "wait"
    return run_id


async def _next_seq(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> int:
    from agentic_store import max_event_seq

    return await max_event_seq(sessions, run_id) + 1


async def test_a_waiting_run_is_found_by_its_issue_with_the_comment_it_waits_after(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await waiting_run(sessions)

    [found] = [w for w in await waiting_runs(sessions, issue_key="kan-5") if w.run_id == run_id]

    assert (found.node_id, found.issue_key, found.cloud_id) == ("wait", "KAN-5", CLOUD)
    assert found.after_comment_id == "10001"
    assert not [w for w in await waiting_runs(sessions, issue_key="KAN-6") if w.run_id == run_id]
    assert not [w for w in await waiting_runs(sessions, cloud_id="other") if w.run_id == run_id]


async def test_an_answer_queues_the_run_once_with_an_approval_by_the_platform(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await waiting_run(sessions)

    results = await asyncio.gather(
        answer_arrived(sessions, run_id, "wait"), answer_arrived(sessions, run_id, "wait")
    )

    assert sorted(results) == [False, True]
    async with sessions() as session:
        run = await session.get(Run, run_id)
        approvals = list(await session.scalars(select(Approval).where(Approval.run_id == run_id)))
    assert run is not None and run.status == "queued"
    assert [(a.node_id, a.decision, a.decided_by) for a in approvals if a.node_id == "wait"] == [
        ("wait", "approve", ANSWER_DECIDER)
    ]
    decision = await pending_decision(sessions, run_id)
    assert decision is not None and decision.decision == "approve"


async def test_an_answer_for_another_step_or_a_run_not_waiting_does_nothing(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await waiting_run(sessions)

    assert not await answer_arrived(sessions, run_id, "post")
    assert await answer_arrived(sessions, run_id, "wait")
    assert not await answer_arrived(sessions, run_id, "wait")  # it is queued now


async def test_a_person_cannot_decide_a_wait(sessions: async_sessionmaker[AsyncSession]) -> None:
    run_id = await waiting_run(sessions)

    with pytest.raises(NotAGateError):
        await record_approval(sessions, run_id, "wait", GateDecision(decision="approve"))

    async with sessions() as session:
        run = await session.get(Run, run_id)
    assert run is not None and run.status == "waiting"


async def test_an_expired_wait_ends_with_its_own_reason_and_is_never_answered(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await waiting_run(sessions)
    async with sessions.begin() as session:
        await session.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(gate_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )

    assert run_id in await expire_gates(sessions)

    async with sessions() as session:
        run = await session.get(Run, run_id)
    assert run is not None and run.cancel_reason == ANSWERS_EXPIRED_REASON
    assert not await answer_arrived(sessions, run_id, "wait")
    assert not [w for w in await waiting_runs(sessions) if w.run_id == run_id]
