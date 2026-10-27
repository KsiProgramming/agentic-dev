"""Approval expiry (phase 11.3): a gate past its time to live cancels its run."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.events import RunEventLog
from agentic_engine.gate import GateDecision
from agentic_engine.graph import checkpoint_serde, run_workflow
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import Message
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime
from agentic_store import (
    APPROVAL_EXPIRED_REASON,
    USER_CANCEL_REASON,
    AuditEvent,
    GateExpiredError,
    PostgresEventSink,
    Run,
    cancel_reason,
    create_run,
    expire_gates,
    get_run_summary,
    max_event_seq,
    record_approval,
    request_cancel,
)

pytestmark = pytest.mark.integration

SPEC = (
    Path(__file__).resolve().parents[2]
    / "engine"
    / "tests"
    / "fixtures"
    / "specs"
    / "valid"
    / "gate-approval.json"
)


def gated_spec(ttl_s: int | None = None) -> WorkflowSpec:
    """The gate fixture without its `repo.*` tools, so it runs with no sandbox."""
    data = json.loads(SPEC.read_text(encoding="utf-8"))
    data["root"]["steps"][0]["tools"] = []
    data["root"]["steps"][2] = {"type": "agent", "id": "list", "role": "L", "instructions": "Go."}
    if ttl_s is not None:
        data["root"]["steps"][1]["ttl_s"] = ttl_s
    return parse_spec(data)


async def paused_run(sessions: async_sessionmaker[AsyncSession], ttl_s: int | None = None) -> UUID:
    spec = gated_spec(ttl_s)
    run_id = await create_run(sessions, spec, "go")
    result = await run_workflow(
        spec,
        FakeRuntime({"writer": [Message(text="notes"), ECHO_USAGE]}),
        "go",
        run_id=run_id,
        sink=PostgresEventSink(sessions),
        checkpointer=InMemorySaver(serde=checkpoint_serde()),
    )
    assert result.status == "waiting"
    return run_id


async def expire_now(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> None:
    """Move the run's gate expiry into the past."""
    async with sessions.begin() as session:
        await session.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(gate_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )


async def audit_actions(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> list[str]:
    async with sessions() as session:
        rows = await session.scalars(
            select(AuditEvent.action).where(AuditEvent.run_id == run_id).order_by(AuditEvent.id)
        )
        return list(rows)


async def test_a_paused_run_knows_when_its_gate_expires(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await paused_run(sessions, ttl_s=600)

    async with sessions() as session:
        run = await session.get(Run, run_id)
    assert run is not None and run.gate_expires_at is not None and run.waiting_since is not None
    assert run.gate_expires_at - run.waiting_since == pytest.approx(
        timedelta(minutes=10), abs=timedelta(seconds=1)
    )
    row = await get_run_summary(sessions, run_id)
    assert row is not None and row.waiting_gate is not None
    assert datetime.fromisoformat(row.waiting_gate["expires_at"]) == run.gate_expires_at


async def test_a_gate_not_yet_expired_is_left_waiting(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await paused_run(sessions)

    assert run_id not in await expire_gates(sessions)

    row = await get_run_summary(sessions, run_id)
    assert row is not None and row.status == "waiting"


async def test_an_expired_gate_cancels_its_run_once(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await paused_run(sessions)
    await expire_now(sessions, run_id)

    first, second = await asyncio.gather(expire_gates(sessions), expire_gates(sessions))

    assert (first + second).count(run_id) == 1
    async with sessions() as session:
        run = await session.get(Run, run_id)
    assert run is not None
    assert (run.status, run.cancel_reason, run.worker_id) == (
        "queued",
        APPROVAL_EXPIRED_REASON,
        None,
    )
    assert run.cancel_requested_at is not None
    assert await cancel_reason(sessions, run_id) == APPROVAL_EXPIRED_REASON
    assert (await audit_actions(sessions, run_id))[-1] == "gate.expired"
    assert run_id not in await expire_gates(sessions)


async def test_the_expired_audit_entry_names_the_gate(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await paused_run(sessions)
    await expire_now(sessions, run_id)

    await expire_gates(sessions)

    async with sessions() as session:
        entry = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.run_id == run_id, AuditEvent.action == "gate.expired"
            )
        )
    assert entry is not None
    assert (entry.actor_type, entry.node_id) == ("system", "gate")
    assert entry.details["title"] == "Approve the notes"
    assert isinstance(entry.details["expires_at"], str)


async def test_a_decided_gate_never_expires(sessions: async_sessionmaker[AsyncSession]) -> None:
    run_id = await paused_run(sessions)
    await record_approval(sessions, run_id, "gate", GateDecision(decision="approve"))
    await expire_now(sessions, run_id)

    assert run_id not in await expire_gates(sessions)


async def test_an_approval_after_expiry_is_refused(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Even before the sweep has cancelled the run."""
    run_id = await paused_run(sessions)
    await expire_now(sessions, run_id)

    with pytest.raises(GateExpiredError):
        await record_approval(sessions, run_id, "gate", GateDecision(decision="approve"))


async def test_the_cancel_event_keeps_the_reason_on_the_run(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await paused_run(sessions)
    await expire_now(sessions, run_id)
    await expire_gates(sessions)

    sink = PostgresEventSink(sessions)
    next_seq = await max_event_seq(sessions, run_id) + 1
    await RunEventLog(run_id, sink, next_seq=next_seq).emit(
        "run_cancelled", payload={"reason": APPROVAL_EXPIRED_REASON, "expired": True}
    )

    row = await get_run_summary(sessions, run_id)
    assert row is not None
    assert (row.status, row.cancel_reason, row.waiting_gate) == (
        "cancelled",
        APPROVAL_EXPIRED_REASON,
        None,
    )
    async with sessions() as session:
        run = await session.get(Run, run_id)
    assert run is not None and run.gate_expires_at is None


async def test_a_user_cancel_says_so_and_keeps_an_earlier_reason(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    by_user = await paused_run(sessions)
    expired = await paused_run(sessions)
    await expire_now(sessions, expired)
    await expire_gates(sessions)

    await request_cancel(sessions, by_user)
    await request_cancel(sessions, expired)

    assert await cancel_reason(sessions, by_user) == USER_CANCEL_REASON
    assert await cancel_reason(sessions, expired) == APPROVAL_EXPIRED_REASON
