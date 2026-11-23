"""A refused change to a protected path is counted on the run and listed at its gate (13.5)."""

import json
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.events import PROTECTED_PATH_REFUSED, RunEvent
from agentic_engine.graph import checkpoint_serde, run_workflow
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import Message
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime
from agentic_store import (
    PostgresEventSink,
    create_run,
    get_run_summary,
    pending_gate,
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


def gated_spec() -> WorkflowSpec:
    data = json.loads(SPEC.read_text(encoding="utf-8"))
    data["root"]["steps"][0]["tools"] = []
    data["root"]["steps"][2] = {"type": "agent", "id": "list", "role": "L", "instructions": "Go."}
    return parse_spec(data)


async def test_each_refusal_is_counted_on_the_run_and_listed_at_the_gate(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    spec = gated_spec()
    run_id = await create_run(sessions, spec, "go")
    sink = PostgresEventSink(sessions)
    runtime = FakeRuntime({"writer": [Message(text="draft"), ECHO_USAGE]})
    result = await run_workflow(
        spec,
        runtime,
        "go",
        run_id=run_id,
        sink=sink,
        checkpointer=InMemorySaver(serde=checkpoint_serde()),
    )
    assert result.status == "waiting"
    summary = await get_run_summary(sessions, run_id)
    assert summary is not None and summary.protected_attempts == 0
    assert (await pending_gate(sessions, run_id)).protected_attempts == []

    last = (await _last_seq(sessions, run_id)) + 1
    for i, (node, path, kind) in enumerate(
        [
            ("writer", "tests/test_cart.py", "frozen"),
            ("writer", "tests/test_cart.py", "frozen"),
            ("writer", ".github/workflows/ci.yml", "default"),
        ]
    ):
        await _emit(sessions, run_id, last + i, node, path, kind)

    summary = await get_run_summary(sessions, run_id)
    assert summary is not None and summary.protected_attempts == 3
    attempts = (await pending_gate(sessions, run_id)).protected_attempts
    assert [(a.node_id, a.path, a.rule, a.count) for a in attempts] == [
        ("writer", "tests/test_cart.py", "frozen", 2),
        ("writer", ".github/workflows/ci.yml", "default", 1),
    ]


async def _last_seq(sessions: async_sessionmaker[AsyncSession], run_id) -> int:  # type: ignore[no-untyped-def]
    from agentic_store import max_event_seq

    return await max_event_seq(sessions, run_id)


async def _emit(sessions, run_id, seq, node, path, kind) -> None:  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime

    await PostgresEventSink(sessions).emit(
        RunEvent(
            run_id=run_id,
            seq=seq,
            type=PROTECTED_PATH_REFUSED,
            node_id=node,
            payload={"tool": "repo.write_file", "path": path, "rule": {"kind": kind}},
            created_at=datetime.now(UTC),
        )
    )
