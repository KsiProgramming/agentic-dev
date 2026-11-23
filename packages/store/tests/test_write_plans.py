"""What approving does (13.8), as the store records it: the pending gate carries the plans of the
writes it guards, and the audit log names the system for a write that was not as planned or whose
plan went stale. A write that is as planned leaves no audit row."""

from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.gate import GateDecision
from agentic_engine.graph import checkpoint_serde, resume_workflow, run_workflow
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import Message, ToolOutput
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime
from agentic_runtime.testing import ScriptedToolExecutor, plan_answer
from agentic_store import PostgresEventSink, create_run, pending_gate
from agentic_store.models import AuditEvent

pytestmark = pytest.mark.integration

BODY = "The fix is in **#42**."


def spec() -> WorkflowSpec:
    return parse_spec(
        {
            "spec_version": "0",
            "id": "plans",
            "name": "Plans",
            "root": {
                "type": "sequence",
                "id": "main",
                "steps": [
                    {"type": "gate", "id": "approve", "title": "Post it?"},
                    {
                        "type": "tool",
                        "id": "post",
                        "tool": "jira.comment",
                        "args": {"issue": "API-1", "body": BODY},
                    },
                ],
            },
        }
    )


class Tools(ScriptedToolExecutor):
    """Plans a comment on API-1; the write answers `answer`."""

    def __init__(self, answer: ToolOutput) -> None:
        super().__init__({"jira.comment": answer})

    async def call(
        self, name: str, arguments: dict[str, JsonValue], *, node_id: str | None = None
    ) -> ToolOutput:
        if arguments.get("plan") is True:
            return plan_answer(name, arguments, fields={"key": "API-1", "text": BODY})
        return await super().call(name, arguments, node_id=node_id)


async def approved(
    sessions: async_sessionmaker[AsyncSession], answer: ToolOutput
) -> tuple[Any, list[Any]]:
    workflow = spec()
    run_id = await create_run(sessions, workflow, "go")
    tools = Tools(answer)
    common: dict[str, Any] = {
        "run_id": run_id,
        "sink": PostgresEventSink(sessions),
        "checkpointer": InMemorySaver(serde=checkpoint_serde()),
        "tools": tools,
    }
    runtime = FakeRuntime({"writer": [Message(text="x"), ECHO_USAGE]})
    await run_workflow(workflow, runtime, "go", **common)
    shown = await pending_gate(sessions, run_id)
    await resume_workflow(
        workflow,
        runtime,
        "go",
        next_seq=100,
        attempt=2,
        decision=GateDecision(decision="approve"),
        **common,
    )
    async with sessions() as session:
        rows = list(
            await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.run_id == run_id, AuditEvent.action.like("write.%")
                )
            )
        )
    return shown, rows


async def test_the_pending_gate_carries_the_plans_it_showed(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    shown, _ = await approved(sessions, ToolOutput(text="ok", data={"key": "API-1", "text": BODY}))

    (plan,) = shown.plans
    assert (plan.node_id, plan.tool, plan.action) == ("post", "jira.comment", "comment")
    assert plan.body == BODY
    assert plan.target.label == "API-1"


async def test_a_write_as_planned_leaves_no_audit_row(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    _, rows = await approved(sessions, ToolOutput(text="ok", data={"key": "API-1", "text": BODY}))

    assert rows == []


async def test_a_write_that_differs_is_audited_as_the_system(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    _, rows = await approved(sessions, ToolOutput(text="ok", data={"key": "API-2", "text": BODY}))

    (row,) = rows
    assert (row.action, row.actor_type, row.node_id) == ("write.not_as_planned", "system", "post")
    assert row.details == {"gate": "approve", "tool": "jira.comment", "fields": ["key"]}
    assert BODY not in str(row.details)  # a plan's text is data, kept in the events


async def test_a_plan_the_tool_refused_as_stale_is_audited(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    stale = ToolOutput(
        text="Error executing tool comment: plan_stale: API-1 is now in project DOCS", is_error=True
    )

    _, rows = await approved(sessions, stale)

    (row,) = rows
    assert (row.action, row.actor_type) == ("write.plan_stale", "system")
    assert row.details["tool"] == "jira.comment"
