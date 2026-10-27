"""Creating the run's repo behind a gate (phase 1.12): `gate → github.createRepo` creates the repo
only after approval, records it as `repo_created`, and then ends the attempt `suspended`. The
next attempt (which the worker gives the cloned repo) goes on with no decision. The tool runs on
a fake executor; the real one is `agentic_tools.github`."""

from collections.abc import Sequence
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from pydantic import JsonValue

from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.gate import GateDecision
from agentic_engine.graph import WorkflowRunResult, checkpoint_serde, resume_workflow, run_workflow
from agentic_engine.graph.compile import recursion_limit
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import Message, ToolDefinition, ToolOutput
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime

REPO: dict[str, JsonValue] = {
    "full_name": "acme/docs-new",
    "url": "https://github.com/acme/docs-new",
    "default_branch": "main",
    "private": True,
    "created": True,
}

SPEC = parse_spec(
    {
        "spec_version": "0",
        "id": "new-repo",
        "name": "New repo",
        "root": {
            "type": "sequence",
            "id": "main",
            "steps": [
                {"type": "gate", "id": "approve_repo", "title": "Create acme/docs-new?"},
                {
                    "type": "tool",
                    "id": "create_repo",
                    "tool": "github.createRepo",
                    "args": {"name": "docs-new", "private": True},
                },
                {"type": "agent", "id": "writer", "role": "W", "instructions": "Go."},
            ],
        },
    }
)


class FakeCreator:
    """A `ToolExecutor` offering `github.createRepo`; records the calls it gets."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, JsonValue]]] = []

    def definitions(self) -> Sequence[ToolDefinition]:
        return [ToolDefinition(name="github.createRepo")]

    async def call(
        self, name: str, arguments: dict[str, JsonValue], *, node_id: str | None = None
    ) -> ToolOutput:
        self.calls.append((name, arguments))
        return ToolOutput(text="created acme/docs-new", data=REPO)


class Run:
    def __init__(self, spec: WorkflowSpec = SPEC) -> None:
        self.spec = spec
        self.runtime = FakeRuntime({"writer": [Message(text="docs"), ECHO_USAGE]})
        self.tools = FakeCreator()
        self.run_id = uuid4()
        self.sink = InMemoryEventSink()
        self.checkpointer = InMemorySaver(serde=checkpoint_serde())
        self.attempt = 1

    async def start(self) -> WorkflowRunResult:
        return await run_workflow(
            self.spec,
            self.runtime,
            "go",
            run_id=self.run_id,
            sink=self.sink,
            checkpointer=self.checkpointer,
            tools=self.tools,
        )

    async def resume(self, decision: GateDecision | None = None) -> WorkflowRunResult:
        self.attempt += 1
        return await resume_workflow(
            self.spec,
            self.runtime,
            "go",
            run_id=self.run_id,
            sink=self.sink,
            checkpointer=self.checkpointer,
            next_seq=self.sink.events[-1].seq + 1,
            attempt=self.attempt,
            tools=self.tools,
            decision=decision,
        )

    def types(self, since: int = 0) -> list[tuple[str, str | None]]:
        return [(e.type, e.node_id) for e in self.sink.events[since:] if _shown(e)]


def _shown(event: RunEvent) -> bool:
    return event.type.startswith(("node_", "run_", "gate_", "repo_"))


async def test_the_repo_is_created_only_after_approval_then_the_attempt_suspends() -> None:
    run = Run()

    paused = await run.start()
    assert (paused.status, paused.waiting_at) == ("waiting", "approve_repo")
    assert run.tools.calls == []

    seen = len(run.sink.events)
    suspended = await run.resume(GateDecision(decision="approve"))

    assert (suspended.status, suspended.waiting_at) == ("suspended", "create_repo.ready")
    assert run.tools.calls == [("github.createRepo", {"name": "docs-new", "private": True})]
    assert run.types(seen) == [
        ("run_resumed", None),
        ("gate_decided", "approve_repo"),
        ("node_completed", "approve_repo"),
        ("node_started", "create_repo"),
        ("repo_created", "create_repo"),
        ("node_completed", "create_repo"),
    ]
    (created,) = [e for e in run.sink.events if e.type == "repo_created"]
    assert created.payload == REPO


async def test_the_next_attempt_goes_on_with_no_decision() -> None:
    run = Run()
    await run.start()
    await run.resume(GateDecision(decision="approve"))
    seen = len(run.sink.events)

    done = await run.resume()

    assert done.status == "completed"
    assert len(run.tools.calls) == 1  # not created again
    assert run.types(seen) == [
        ("run_resumed", None),
        ("node_started", "writer"),
        ("node_completed", "writer"),
        ("run_completed", None),
    ]
    # The writer gets the creating node's output.
    assert run.runtime.requests[-1].input == "created acme/docs-new"


async def test_a_rejection_creates_nothing() -> None:
    run = Run()
    await run.start()

    done = await run.resume(GateDecision(decision="reject", comment="no"))

    assert done.status == "cancelled"
    assert run.tools.calls == []
    assert not [e for e in run.sink.events if e.type == "repo_created"]


async def test_a_failed_creation_ends_the_run_without_suspending() -> None:
    run = Run()

    async def refuse(
        name: str, arguments: dict[str, JsonValue], *, node_id: str | None = None
    ) -> ToolOutput:
        return ToolOutput(text="repo acme/docs-new already exists", is_error=True)

    run.tools.call = refuse  # type: ignore[method-assign]
    await run.start()

    done = await run.resume(GateDecision(decision="approve"))

    assert done.status == "failed"
    assert not [e for e in run.sink.events if e.type == "repo_created"]


def test_the_ready_step_counts_towards_the_recursion_limit() -> None:
    # gate, create (+ ready), writer, plus the margin.
    assert recursion_limit(SPEC) == 4 + 10
