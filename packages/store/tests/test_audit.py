"""The audit log: each action writes one row with the change it records, and listing it."""

import json
import os
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.events import RunEvent
from agentic_engine.gate import FileChange, FileEdit, GateDecision
from agentic_engine.graph import checkpoint_serde, run_workflow
from agentic_engine.policy import PolicyOverrides
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import ModelPrice
from agentic_runtime.fake import FakeRuntime
from agentic_secrets import KEY_BYTES, LocalKeyProvider
from agentic_store import (
    AuditEvent,
    InvalidCursorError,
    InvalidEditsError,
    PolicyViolationError,
    PostgresEventSink,
    RunEndedError,
    RunNotWaitingError,
    Workspace,
    WorkspaceNotFoundError,
    create_rerun,
    create_run,
    delete_connection,
    list_audit_events,
    put_connection,
    put_github_connection,
    record_approval,
    replace_policy_overrides,
    replace_price_overrides,
    request_cancel,
)

pytestmark = pytest.mark.integration

KEYS = LocalKeyProvider(os.urandom(KEY_BYTES))
SPECS = Path(__file__).resolve().parents[2] / "engine" / "tests" / "fixtures" / "specs" / "valid"
PAGE = FileChange(node_id="writer", path="docs/a.md", status="added", editable=True, after="# A\n")
PRICE = ModelPrice(
    input=Decimal(3),
    output=Decimal(15),
    cache_write_5m=Decimal("3.75"),
    cache_write_1h=Decimal(6),
    cache_read=Decimal("0.3"),
)


def two_step_spec() -> WorkflowSpec:
    return parse_spec(json.loads((SPECS / "two-step-sequence.json").read_text(encoding="utf-8")))


def gated_spec() -> WorkflowSpec:
    """The gate fixture without its `repo.*` tools, so it runs with no sandbox."""
    data = json.loads((SPECS / "gate-approval.json").read_text(encoding="utf-8"))
    data["root"]["steps"][0]["tools"] = []
    data["root"]["steps"][2] = {"type": "agent", "id": "list", "role": "L", "instructions": "Go."}
    return parse_spec(data)


class ShownReview:
    async def changes(self, ran: Sequence[str]) -> list[FileChange]:
        return [PAGE]

    async def apply(self, gate_id: str, edits: Sequence[FileEdit]) -> dict[str, str]:
        return {"writer": "0" * 40}


async def new_workspace(sessions: async_sessionmaker[AsyncSession]) -> UUID:
    workspace_id = uuid4()
    async with sessions.begin() as session:
        session.add(Workspace(id=workspace_id, name=f"ws-{workspace_id.hex[:6]}"))
    return workspace_id


async def rows(sessions: async_sessionmaker[AsyncSession], workspace_id: UUID) -> list[AuditEvent]:
    async with sessions() as session:
        return list(
            await session.scalars(
                select(AuditEvent)
                .where(AuditEvent.workspace_id == workspace_id)
                .order_by(AuditEvent.id)
            )
        )


async def actions(sessions: async_sessionmaker[AsyncSession], workspace_id: UUID) -> list[str]:
    return [r.action for r in await rows(sessions, workspace_id)]


async def paused_run(sessions: async_sessionmaker[AsyncSession], workspace_id: UUID) -> UUID:
    spec = gated_spec()
    run_id = await create_run(sessions, spec, "go", workspace_id=workspace_id)
    result = await run_workflow(
        spec,
        FakeRuntime(),
        "go",
        run_id=run_id,
        sink=PostgresEventSink(sessions),
        checkpointer=InMemorySaver(serde=checkpoint_serde()),
        review=ShownReview(),
    )
    assert result.status == "waiting"
    return run_id


async def test_a_run_is_audited_from_creation_to_its_end(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await new_workspace(sessions)
    run_id = await create_run(
        sessions, two_step_spec(), "go", workspace_id=workspace_id, template_id="generate-docs"
    )
    await run_workflow(
        two_step_spec(), FakeRuntime(), "go", run_id=run_id, sink=PostgresEventSink(sessions)
    )

    created, ended = await rows(sessions, workspace_id)
    assert (created.action, created.actor_type, created.actor_id, created.run_id) == (
        "run.created",
        "user",
        None,
        run_id,
    )
    assert created.details == {"template_id": "generate-docs", "repo_url": None, "budget_usd": None}
    assert (ended.action, ended.actor_type, ended.run_id) == ("run.ended", "system", run_id)
    assert ended.details["status"] == "completed"
    assert ended.details["failure_reason"] is None


async def test_a_rerun_and_a_cancel_are_audited_once(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await new_workspace(sessions)
    run_id = await create_run(sessions, two_step_spec(), "go", workspace_id=workspace_id)
    await request_cancel(sessions, run_id)
    await request_cancel(sessions, run_id)  # asking again records nothing
    await PostgresEventSink(sessions).emit(
        RunEvent(
            run_id=run_id,
            seq=1,
            type="run_cancelled",
            payload={"reason": "cancelled by user"},
            created_at=datetime.now(UTC),
        )
    )
    with pytest.raises(RunEndedError):
        await request_cancel(sessions, run_id)
    rerun_id = await create_rerun(sessions, run_id, Decimal("2.5"))

    audited = await rows(sessions, workspace_id)
    assert [r.action for r in audited] == [
        "run.created",
        "run.cancel_requested",
        "run.ended",
        "run.rerun",
    ]
    assert audited[1].details == {"status": "queued"}
    assert audited[2].details["status"] == "cancelled"
    assert audited[3].run_id == rerun_id
    assert audited[3].details["rerun_of"] == str(run_id)
    assert audited[3].details["budget_usd"] == "2.5"


async def test_a_run_refused_by_policy_is_not_audited(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await new_workspace(sessions)
    await replace_policy_overrides(sessions, workspace_id, PolicyOverrides(loop_iterations=2))
    spec = json.loads((SPECS / "review-loop.json").read_text(encoding="utf-8"))  # 3 iterations

    with pytest.raises(PolicyViolationError):
        await create_run(sessions, parse_spec(spec), "go", workspace_id=workspace_id)

    assert await actions(sessions, workspace_id) == ["policy.updated"]


async def test_gate_decisions_are_audited_with_paths_not_contents(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await new_workspace(sessions)
    approved = await paused_run(sessions, workspace_id)
    rejected = await paused_run(sessions, workspace_id)
    edit = FileEdit(node_id="writer", path="docs/a.md", content="# Secret draft\n")

    with pytest.raises(InvalidEditsError):
        await record_approval(
            sessions,
            approved,
            "gate",
            GateDecision(decision="reject", edits=[edit]),
        )
    await record_approval(
        sessions, approved, "gate", GateDecision(decision="approve", comment="ok", edits=[edit])
    )
    with pytest.raises(RunNotWaitingError):
        await record_approval(sessions, approved, "gate", GateDecision(decision="approve"))
    await record_approval(sessions, rejected, "gate", GateDecision(decision="reject"))

    decisions = [r for r in await rows(sessions, workspace_id) if r.action.startswith("gate.")]
    assert [(r.action, r.run_id, r.node_id) for r in decisions] == [
        ("gate.approved", approved, "gate"),
        ("gate.rejected", rejected, "gate"),
    ]
    assert decisions[0].details == {
        "comment": "ok",
        "edited_files": 1,
        "edited_paths": ["docs/a.md"],
    }
    assert "Secret draft" not in json.dumps(decisions[0].details)
    assert decisions[1].details == {"comment": None, "edited_files": 0, "edited_paths": []}


async def test_connections_are_audited_with_hints_not_secrets(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await new_workspace(sessions)
    secret = "sk-ant-very-secret-1234"
    await put_connection(sessions, KEYS, workspace_id, "claude", SecretStr(secret))
    await put_connection(sessions, KEYS, workspace_id, "claude", SecretStr(secret))
    await put_github_connection(sessions, workspace_id, 42, "acme", "Organization")
    assert await delete_connection(sessions, workspace_id, "claude")
    assert not await delete_connection(sessions, workspace_id, "claude")  # nothing to remove
    assert await delete_connection(sessions, workspace_id, "github")

    audited = await rows(sessions, workspace_id)
    assert [(r.action, r.details) for r in audited] == [
        ("connection.added", {"provider": "claude", "key_hint": "1234", "replaced": False}),
        ("connection.added", {"provider": "claude", "key_hint": "1234", "replaced": True}),
        ("connection.added", {"provider": "github", "account_login": "acme", "replaced": False}),
        (
            "connection.removed",
            {"provider": "claude", "key_hint": "1234", "account_login": None},
        ),
        (
            "connection.removed",
            {"provider": "github", "key_hint": None, "account_login": "acme"},
        ),
    ]
    assert all(secret not in json.dumps(r.details) for r in audited)


async def test_settings_changes_are_audited_only_when_something_changed(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await new_workspace(sessions)
    limits = PolicyOverrides(agents_alive=4, budget_usd=Decimal(10))
    await replace_policy_overrides(sessions, workspace_id, limits)
    await replace_policy_overrides(sessions, workspace_id, limits)
    await replace_price_overrides(sessions, workspace_id, {"a": PRICE, "b": PRICE})
    await replace_price_overrides(sessions, workspace_id, {"a": PRICE, "b": PRICE})
    cheaper = PRICE.model_copy(update={"input": Decimal(1)})
    await replace_price_overrides(sessions, workspace_id, {"b": cheaper, "c": PRICE})

    policy, first_prices, second_prices = await rows(sessions, workspace_id)
    assert policy.action == "policy.updated"
    assert policy.details["before"] == PolicyOverrides().model_dump(mode="json")
    assert policy.details["after"] == limits.model_dump(mode="json")
    assert (first_prices.action, first_prices.details) == (
        "pricing.updated",
        {"added": ["a", "b"], "changed": [], "removed": []},
    )
    assert second_prices.details == {"added": ["c"], "changed": ["b"], "removed": ["a"]}


async def test_listing_pages_newest_first_and_filters(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await new_workspace(sessions)
    other = await new_workspace(sessions)
    run_ids = [
        await create_run(
            sessions, two_step_spec(), "go", workspace_id=workspace_id, template_id="t"
        )
        for _ in range(3)
    ]
    await request_cancel(sessions, run_ids[0])
    await create_run(sessions, two_step_spec(), "go", workspace_id=other)

    pages: list[Any] = []
    cursor = None
    while True:
        items, cursor = await list_audit_events(sessions, workspace_id, limit=2, cursor=cursor)
        pages.append(items)
        if cursor is None:
            break
    listed = [item for page in pages for item in page]
    assert [len(p) for p in pages] == [2, 2]
    assert [(i.action, i.run_id) for i in listed] == [
        ("run.cancel_requested", run_ids[0]),
        ("run.created", run_ids[2]),
        ("run.created", run_ids[1]),
        ("run.created", run_ids[0]),
    ]
    assert listed[0].run is not None
    assert (listed[0].run.template_id, listed[0].run.status) == ("t", "queued")

    by_action, _ = await list_audit_events(sessions, workspace_id, actions=["run.cancel_requested"])
    assert [i.run_id for i in by_action] == [run_ids[0]]
    by_run, _ = await list_audit_events(sessions, workspace_id, run_id=run_ids[1])
    assert [i.action for i in by_run] == ["run.created"]
    future = datetime.now(UTC) + timedelta(days=1)
    assert (await list_audit_events(sessions, workspace_id, since=future))[0] == []
    assert len((await list_audit_events(sessions, workspace_id, until=future))[0]) == 4


async def test_listing_refuses_unknown_workspaces_and_cursors(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(WorkspaceNotFoundError):
        await list_audit_events(sessions, uuid4())
    workspace_id = await new_workspace(sessions)
    with pytest.raises(InvalidCursorError):
        await list_audit_events(sessions, workspace_id, cursor="not-a-cursor")
