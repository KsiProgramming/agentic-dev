"""A gate whose checks send the work back (13.3), as the store records it: the pending gate carries
the evidence pack, the audit log names the system (not a person) for the send-back, and no approval
row pretends someone decided."""

from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.graph import checkpoint_serde, run_workflow
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import Message, ToolOutput
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime
from agentic_runtime.testing import ScriptedToolExecutor
from agentic_store import (
    Approval,
    PostgresEventSink,
    create_run,
    pending_gate,
)
from agentic_store.models import AuditEvent

pytestmark = pytest.mark.integration


def spec() -> WorkflowSpec:
    return parse_spec(
        {
            "spec_version": "0",
            "id": "evidence",
            "name": "Evidence",
            "root": {
                "type": "loop",
                "id": "build",
                "until": 'results.check.data.decision != "changes"',
                "max_iterations": 4,
                "body": {
                    "type": "sequence",
                    "id": "round",
                    "steps": [
                        {
                            "type": "agent",
                            "id": "writer",
                            "role": "W",
                            "instructions": "Go.",
                            "tools": ["repo.write_file", "repo.commit"],
                        },
                        {
                            "type": "gate",
                            "id": "check",
                            "title": "Merge?",
                            "evidence": {"node": "writer", "max_rounds": 2},
                        },
                    ],
                },
            },
        }
    )


def report_with(status: str) -> ToolOutput:
    module: dict[str, JsonValue] = {
        "path": ".", "ecosystem": "node", "runner": "jest", "status": status, "build": "ran",
        "passed": 2, "failed": 1 if status == "failed" else 0, "skipped": 0,
        "failures": [{"name": "sum > adds", "file": "a.test.js", "message": "expected 3"}]
        if status == "failed" else [],
    }  # fmt: skip
    return ToolOutput(text="t", data={"tool": "build.test", "checks": [module]})


class Tools(ScriptedToolExecutor):
    def __init__(self) -> None:
        super().__init__({"repo.write_file": "wrote", "repo.commit": "ok"})
        self.answers = [report_with("failed"), report_with("passed")]

    async def call(
        self, name: str, arguments: dict[str, JsonValue], *, node_id: str | None = None
    ) -> ToolOutput:
        if name == "build.test":
            return self.answers.pop(0)
        if name == "scan.lint":
            return ToolOutput(text="l", data={"tool": "lint", "findings": [], "checks": []})
        return await super().call(name, arguments, node_id=node_id)


async def test_a_send_back_is_audited_as_the_system_and_the_pack_reaches_the_gate(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    workflow = spec()
    run_id = await create_run(sessions, workflow, "go")
    tools = Tools()

    result = await run_workflow(
        workflow,
        FakeRuntime({"writer": [Message(text="done"), ECHO_USAGE] * 2}, tools=tools),
        "go",
        run_id=run_id,
        sink=PostgresEventSink(sessions),
        checkpointer=InMemorySaver(serde=checkpoint_serde()),
        tools=tools,
    )

    assert result.status == "waiting"
    async with sessions() as session:
        audits: list[Any] = list(
            await session.scalars(select(AuditEvent).where(AuditEvent.run_id == run_id))
        )
        approvals = list(await session.scalars(select(Approval).where(Approval.run_id == run_id)))
    sent = [a for a in audits if a.action == "gate.sent_back_by_checks"]
    assert len(sent) == 1
    assert (sent[0].actor_type, sent[0].node_id) == ("system", "check")
    assert sent[0].details == {"checks": ["Tests"]}
    assert approvals == []  # no person decided anything
    shown = (await pending_gate(sessions, run_id)).evidence
    assert shown is not None
    assert {c.kind: c.status for c in shown.checks} == {
        "build": "passed",
        "tests": "passed",
        "analyzers": "passed",
    }
    assert shown.rounds_left == 1
