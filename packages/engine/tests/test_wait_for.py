"""The `wait_for` step (7.9): a run that asked a question holds until the platform continues it,
builds nothing meanwhile, and survives a restart while it waits (lessons rule 9)."""

from typing import Any
from uuid import UUID, uuid4

from langgraph.checkpoint.memory import InMemorySaver
from pydantic import JsonValue

from agentic_engine.agent import IssueBrief, RunContext
from agentic_engine.events import InMemoryEventSink
from agentic_engine.gate import GateDecision
from agentic_engine.graph import (
    WorkflowRunResult,
    checkpoint_serde,
    resume_workflow,
    run_workflow,
)
from agentic_engine.policy import PLATFORM_POLICY
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_engine.spec.validate import validate_workflow
from agentic_runtime import Message, ToolOutput
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime
from agentic_runtime.testing import ScriptedToolExecutor

BRIEF = IssueBrief(key="KAN-5", url="https://acme.atlassian.net/browse/KAN-5", project="KAN")
ANSWERED = GateDecision(decision="approve", decided_by="jira:comment")


def spec(*, wait: dict[str, object] | None = None, ask_id: str = "ask") -> WorkflowSpec:
    """`ask` (a `jira.comment`), then `wait`, then `build`, an agent that must not run early."""
    return parse_spec(
        {
            "spec_version": "0",
            "id": "waits",
            "name": "Waits",
            "root": {
                "type": "sequence",
                "id": "main",
                "steps": [
                    {"type": "gate", "id": "post", "title": "Post the question?"},
                    {
                        "type": "tool",
                        "id": ask_id,
                        "tool": "jira.comment",
                        "args": {"issue_from": "request", "body": "Which one?"},
                    },
                    {
                        "type": "wait_for",
                        "id": "wait",
                        "title": "Waiting for answers",
                        "after_from": "ask",
                        **(wait or {}),
                    },
                    {"type": "agent", "id": "build", "role": "B", "instructions": "Go."},
                ],
            },
        }
    )


class Run:
    """One run across its waits: the same checkpointer and sink, a new attempt each resume."""

    def __init__(self, workflow: WorkflowSpec, *, comment_id: str | None = "10001") -> None:
        data: dict[str, JsonValue] = {"comment_id": comment_id} if comment_id is not None else {}
        self.tools = ScriptedToolExecutor({"jira.comment": ToolOutput(text="posted", data=data)})
        self.runtime = FakeRuntime({"build": [Message(text="built"), ECHO_USAGE]})
        self.spec = workflow
        self.run_id: UUID = uuid4()
        self.sink = InMemoryEventSink()
        self.checkpointer = InMemorySaver(serde=checkpoint_serde())
        self.attempt = 1
        self.common = {
            "run_id": self.run_id,
            "sink": self.sink,
            "checkpointer": self.checkpointer,
            "tools": self.tools,
            "context": RunContext(request="KAN-5").model_copy(update={"issue": BRIEF}),
        }

    async def start(self) -> WorkflowRunResult:
        """Start, and approve the post gate: the run is now asking, then waiting."""
        first = await run_workflow(self.spec, self.runtime, "KAN-5", **self.common)  # type: ignore[arg-type]
        assert first.waiting_at == "post"
        return await self.resume(GateDecision(decision="approve", decided_by="ada"))

    async def resume(self, decision: GateDecision | None = ANSWERED) -> WorkflowRunResult:
        self.attempt += 1
        return await resume_workflow(
            self.spec,
            self.runtime,
            "KAN-5",
            next_seq=self.sink.events[-1].seq + 1,
            attempt=self.attempt,
            decision=decision,
            **self.common,  # type: ignore[arg-type]
        )


async def test_the_run_holds_after_the_question_and_builds_nothing() -> None:
    run = Run(spec())

    result = await run.start()

    assert result.status == "waiting"
    assert result.waiting_at == "wait"
    assert [r.node_id for r in run.runtime.requests] == []  # `build` has not started
    waiting = run.sink.events[-1]
    assert waiting.type == "gate_waiting" and waiting.node_id == "wait"
    assert waiting.payload["wait_for"] == {
        "kind": "jira_comment",
        "issue": {"key": "KAN-5", "url": BRIEF.url},
        "after_comment_id": "10001",
    }
    assert waiting.payload["ttl_s"] == 7 * 24 * 60 * 60
    assert "expires_at" in waiting.payload


async def test_an_answer_continues_the_run_to_the_next_step() -> None:
    run = Run(spec())
    await run.start()

    result = await run.resume()

    assert result.status == "completed"
    assert [r.node_id for r in run.runtime.requests] == ["build"]
    assert result.results["wait"].data == {"answered": True}


async def test_a_restart_in_the_middle_of_the_wait_still_waits() -> None:
    """A new attempt that is not an answer (a worker restart, no decision) pauses again at the
    same step, and the question is not asked twice."""
    run = Run(spec())
    await run.start()

    again = await run.resume(None)

    assert again.status == "waiting" and again.waiting_at == "wait"
    assert [r.node_id for r in run.runtime.requests] == []
    assert [name for name, _ in run.tools.calls] == ["jira.comment"]
    assert (await run.resume()).status == "completed"


async def test_the_wait_ttl_is_its_own() -> None:
    run = Run(spec(wait={"ttl_s": 3600}))

    await run.start()

    assert run.sink.events[-1].payload["ttl_s"] == 3600


async def test_a_question_with_no_comment_id_fails_before_waiting_for_ever() -> None:
    run = Run(spec(), comment_id=None)

    result = await run.start()

    assert result.status == "failed"
    assert "posted no comment" in (result.results["wait"].error or "")
    assert [r.node_id for r in run.runtime.requests] == []


async def test_a_run_with_no_issue_cannot_wait() -> None:
    run = Run(spec())
    run.common["context"] = RunContext(request="KAN-5")

    result = await run.start()

    assert result.status == "failed"
    assert "no Jira issue" in (result.results["wait"].error or "")


def test_a_wait_may_sit_in_a_loop_but_not_a_map_or_a_parallel() -> None:
    wait = {"type": "wait_for", "id": "w", "title": "T", "after_from": "ask"}
    ask = {"type": "tool", "id": "ask", "tool": "repo.list_files"}

    def codes(node: dict[str, Any]) -> set[str]:
        document = {
            "spec_version": "0",
            "id": "x",
            "name": "X",
            "root": {"type": "sequence", "id": "m", "steps": [node]},
        }
        found = validate_workflow(
            document, policy=PLATFORM_POLICY, priced=lambda _: True, default_model="default"
        )
        return {issue.code for issue in found}

    in_map = {"type": "map", "id": "c", "over": "[1]", "max_concurrency": 1, "body": wait}
    in_parallel = {"type": "parallel", "id": "c", "join": "all", "branches": [wait, ask]}
    assert any(c.startswith("not_allowed_in_") for c in codes(in_map))
    assert any(c.startswith("not_allowed_in_") for c in codes(in_parallel))
