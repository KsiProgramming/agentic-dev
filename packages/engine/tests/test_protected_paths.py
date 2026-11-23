"""Protected paths and `start_from` in a run (13.5, lessons rules 1 and 7): what the implementer of
a test-first flow receives (its tools, its context, its branch's start), that a write to a frozen
test is refused, counted and leaves the work as it was, and that a restart keeps the frozen set."""

import asyncio
import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import JsonValue

from agentic_engine.agent import RunContext
from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.gate import GateDecision
from agentic_engine.graph import checkpoint_serde, resume_workflow, run_workflow
from agentic_engine.integrate import (
    BranchIntegrator,
    Integration,
    IntegrationError,
    MergeRequest,
    StartedBranch,
)
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import (
    AgentRequest,
    Message,
    ProtectedPaths,
    ReadableWriters,
    ToolOutput,
    refusal_text,
)
from agentic_runtime.fake import ECHO_USAGE, CallTool, Delay, FakeRuntime, Script
from agentic_runtime.testing import ScriptedToolExecutor

CONTEXT = RunContext(repo="acme/shop", request="Make the cart tests pass.")
TESTS = ["tests/test_cart.py", "tests/test_totals.py"]
WRITE = ["repo.read_file", "repo.write_file", "repo.commit"]


def flow(*, orchestrated: bool = False, start_from: str | None = "test_writer") -> WorkflowSpec:
    start: dict[str, Any] = {} if start_from is None else {"start_from": start_from}
    implementer: dict[str, Any] = (
        {
            "type": "orchestrator",
            "id": "team",
            "hub": {"role": "Lead", "instructions": "Plan.", "tools": ["repo.read_file"]},
            "body": {
                "type": "agent",
                "id": "engineer",
                "role": "Engineer",
                "instructions": "Do the task.",
                "tools": WRITE,
            },
            "max_workers": 2,
            "max_concurrency": 1,
            **start,
        }
        if orchestrated
        else {
            "type": "agent",
            "id": "implementer",
            "role": "Implementer",
            "instructions": "Make the approved tests pass, without changing them.",
            "tools": WRITE,
            **start,
        }
    )
    return parse_spec(
        {
            "spec_version": "0",
            "id": "test-first",
            "name": "Test first",
            "protect": {"paths": ["**/conftest.py"]},
            "root": {
                "type": "sequence",
                "id": "main",
                "steps": [
                    {
                        "type": "agent",
                        "id": "test_writer",
                        "role": "Test writer",
                        "instructions": "Write the tests.",
                        "tools": WRITE,
                    },
                    {"type": "gate", "id": "approve_tests", "title": "Approve the tests?"},
                    implementer,
                    {"type": "gate", "id": "final", "title": "Open a pull request?"},
                ],
            },
        }
    )


class Integrator(BranchIntegrator):
    """Stands in for the sandbox: it records each `start_writer` and names the files frozen."""

    def __init__(self, files: Sequence[str] = TESTS, error: str | None = None) -> None:
        self.files = list(files)
        self.error = error
        self.started: list[tuple[str, str, bool]] = []
        self.merged = 0

    async def integrate(self, orchestrator_id: str, sources: Sequence[MergeRequest]) -> Integration:
        self.merged += 1
        return Integration(
            branch=f"agent/run/{orchestrator_id}",
            head="1" * 40,
            merged=[s.key for s in sources],
        )

    async def start_tasks(self, orchestrator_id: str, keys: Sequence[str]) -> None:
        pass

    async def start_writer(
        self, node_id: str, source: str, *, orchestrator: bool = False
    ) -> StartedBranch:
        if self.error is not None:
            raise IntegrationError(self.error)
        self.started.append((node_id, source, orchestrator))
        return StartedBranch(start="a" * 40, files=self.files)


class Tools(ScriptedToolExecutor):
    """The repo tools as the engine hands them over: a write or commit that touches a protected
    path is refused through the run's `ProtectedPaths`, like `agentic_tools.repo` does."""

    def __init__(self, protected: ProtectedPaths) -> None:
        super().__init__(
            {
                "repo.read_file": "1\tdef test_cart(): pass",
                "repo.write_file": "wrote it",
                "repo.commit": "abc1234 on agent/run/x: done",
            }
        )
        self.protected = protected
        self.written: list[tuple[str | None, str]] = []

    async def call(
        self, name: str, arguments: dict[str, JsonValue], *, node_id: str | None = None
    ) -> ToolOutput:
        path = arguments.get("path")
        if name == "repo.write_file" and isinstance(path, str) and node_id is not None:
            if (rule := self.protected.rule_for(node_id, path)) is not None:
                await self.protected.refused(node_id, name, path, rule)
                return ToolOutput(text=refusal_text(path, rule), is_error=True)
            self.written.append((node_id, path))
        return await super().call(name, arguments, node_id=node_id)


def scripts(*, implementer: Script | None = None) -> dict[str, Script]:
    return {
        "test_writer": [
            CallTool("repo.write_file", {"path": "tests/test_cart.py", "content": "x"}),
            CallTool("repo.commit", {"message": "Add tests"}),
            Message(text="Added the tests."),
            ECHO_USAGE,
        ],
        "implementer": implementer
        or [
            CallTool("repo.read_file", {"path": "tests/test_cart.py"}),
            CallTool("repo.write_file", {"path": "tests/test_cart.py", "content": "weaker"}),
            CallTool("repo.write_file", {"path": "src/cart.py", "content": "code"}),
            CallTool("repo.commit", {"message": "Implement"}),
            Message(text="Made the tests pass."),
            ECHO_USAGE,
        ],
    }


def saver() -> InMemorySaver:
    return InMemorySaver(serde=checkpoint_serde())


class Run:
    """One run of `flow`, which can be cut off and resumed in a new attempt."""

    def __init__(self, spec: WorkflowSpec | None = None, integrator: Integrator | None = None):
        self.spec = spec or flow()
        self.integrator = integrator or Integrator()
        self.checkpoints = saver()
        self.run_id: UUID = uuid4()
        self.sink = InMemoryEventSink()
        self.attempt = 1
        self.protected = ProtectedPaths()
        self.tools = Tools(self.protected)
        self.runtime = FakeRuntime(scripts(), tools=self.tools)

    def attempt_again(self, runtime_scripts: dict[str, Script] | None = None) -> None:
        """A new attempt: new objects, told everything from the checkpointed state."""
        self.attempt += 1
        self.protected = ProtectedPaths()
        self.tools = Tools(self.protected)
        self.runtime = FakeRuntime(runtime_scripts or scripts(), tools=self.tools)

    def readable(self) -> ReadableWriters:
        return ReadableWriters(lambda node: f"agent/run/{node}")

    async def start(self) -> Any:
        return await run_workflow(
            self.spec,
            self.runtime,
            "go",
            run_id=self.run_id,
            sink=self.sink,
            checkpointer=self.checkpoints,
            tools=self.tools,
            context=CONTEXT,
            integrator=self.integrator,
            readable=self.readable(),
            protected=self.protected,
        )

    async def resume(self, decision: GateDecision | None = None) -> Any:
        return await resume_workflow(
            self.spec,
            self.runtime,
            "go",
            run_id=self.run_id,
            sink=self.sink,
            checkpointer=self.checkpoints,
            next_seq=self.sink.events[-1].seq + 1,
            attempt=self.attempt,
            decision=decision,
            tools=self.tools,
            context=CONTEXT,
            integrator=self.integrator,
            readable=self.readable(),
            protected=self.protected,
        )

    def events(self, type: str) -> list[RunEvent]:
        return [e for e in self.sink.events if e.type == type]

    def request(self, node_id: str) -> AgentRequest:
        return next(r for r in self.runtime.requests if r.node_id == node_id)

    async def to_final_gate(self) -> Any:
        first = await self.start()
        assert first.waiting_at == "approve_tests"
        return await self.resume(GateDecision(decision="approve", decided_by="ada"))


APPROVE = GateDecision(decision="approve", decided_by="ada")


async def test_the_implementer_starts_from_the_approved_tests_and_is_told_what_is_frozen() -> None:
    run = Run()

    waiting = await run.to_final_gate()

    assert waiting.status == "waiting" and waiting.waiting_at == "final"
    assert run.integrator.started == [("implementer", "test_writer", False)]
    asked = run.request("implementer")
    assert asked.tools == WRITE  # it can still write, elsewhere
    assert "# Protected paths" in asked.context
    assert (
        "- Approved at `approve_tests` from `test_writer`, on your branch already: "
        "`tests/test_cart.py`, `tests/test_totals.py`"
    ) in asked.context
    assert "- By this workflow: `**/conftest.py`" in asked.context
    assert "- By the platform (CI and analyzer config): `.github/workflows/**`" in asked.context
    started = next(e for e in run.events("node_started") if e.node_id == "implementer")
    protected = started.payload["protected"]
    assert isinstance(protected, dict)
    assert protected["frozen"] == TESTS
    assert (protected["frozen_from"], protected["gate"]) == ("test_writer", "approve_tests")
    assert (
        "**/conftest.py" in protected["patterns"]
        and ".github/workflows/**" in protected["patterns"]
    )
    # The test writer is told the platform's list too, and has nothing frozen.
    first = run.request("test_writer").context
    assert "# Protected paths" in first and "Approved at" not in first


async def test_a_write_to_a_frozen_test_is_refused_counted_and_changes_nothing() -> None:
    run = Run()

    await run.to_final_gate()

    refused = run.events("protected_path_refused")
    assert [(e.node_id, e.payload) for e in refused] == [
        (
            "implementer",
            {
                "tool": "repo.write_file",
                "path": "tests/test_cart.py",
                "rule": {"kind": "frozen", "writer": "test_writer", "gate": "approve_tests"},
            },
        )
    ]
    # Only the test writer's own write and the implementer's source file went through.
    assert run.tools.written == [
        ("test_writer", "tests/test_cart.py"),
        ("implementer", "src/cart.py"),
    ]
    no_content = [str(e.payload) for e in refused]
    assert not any("weaker" in text for text in no_content)


async def test_the_platform_list_refuses_ci_for_every_writer_without_a_protect_block() -> None:
    spec = flow(start_from=None)
    run = Run(spec)
    run.runtime = FakeRuntime(
        scripts(
            implementer=[
                CallTool("repo.write_file", {"path": ".github/workflows/ci.yml", "content": "x"}),
                Message(text="Tried."),
                ECHO_USAGE,
            ]
        ),
        tools=run.tools,
    )

    await run.to_final_gate()

    assert [e.payload["rule"] for e in run.events("protected_path_refused")] == [
        {"kind": "default", "pattern": ".github/workflows/**"}
    ]
    assert run.integrator.started == []  # no `start_from`: nothing to start
    assert (
        "protected"
        in next(e for e in run.events("node_started") if e.node_id == "implementer").payload
    )


async def test_a_node_that_cannot_start_from_the_work_fails_without_an_agent() -> None:
    run = Run(integrator=Integrator(error="test_writer has no work to start implementer from"))
    first = await run.start()
    assert first.waiting_at == "approve_tests"

    result = await run.resume(APPROVE)

    assert result.status == "failed" and result.stopped_at == "implementer"
    assert [r.node_id for r in run.runtime.requests] == ["test_writer"]
    failed = next(e for e in run.events("node_failed") if e.node_id == "implementer")
    assert "cannot start from the work of 'test_writer'" in str(failed.payload["error"])


async def test_an_orchestrator_started_from_the_tests_starts_its_hub_and_tasks_from_them() -> None:
    spec = flow(orchestrated=True)
    run = Run(spec)
    plan = json.dumps(
        {
            "tasks": [{"id": "t1", "title": "Cart", "instructions": "Implement the cart."}],
            "reason": "one",
        }
    )
    run.runtime = FakeRuntime(
        {
            **scripts(),
            "team": [Message(text=plan), ECHO_USAGE],
            "team.t1": [
                CallTool("repo.write_file", {"path": "tests/test_totals.py", "content": "weaker"}),
                CallTool("repo.write_file", {"path": "src/cart.py", "content": "code"}),
                CallTool("repo.commit", {"message": "Implement"}),
                Message(text="done"),
                ECHO_USAGE,
            ],
        },
        tools=run.tools,
    )

    waiting = await run.to_final_gate()

    assert waiting.waiting_at == "final", waiting
    assert run.integrator.started == [("team", "test_writer", True)]
    refused = run.events("protected_path_refused")
    assert [(e.node_id, e.payload["path"], e.payload["task"]) for e in refused] == [
        ("team", "tests/test_totals.py", "team.t1")
    ]
    started = next(
        e for e in run.events("node_started") if e.node_id == "team.t1" or e.node_id == "engineer"
    )
    assert started.payload["protected"]["frozen"] == TESTS  # type: ignore[index]


async def test_a_restart_during_the_step_keeps_the_frozen_set_and_the_start_point() -> None:
    run = Run()
    first = await run.start()
    assert first.waiting_at == "approve_tests"
    run.runtime = FakeRuntime(scripts(implementer=[Delay(60), ECHO_USAGE]), tools=run.tools)
    task = asyncio.create_task(run.resume(APPROVE))
    for _ in range(500):
        if any(e.type == "node_started" and e.node_id == "implementer" for e in run.sink.events):
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # A new attempt: new tool objects and a fresh `ProtectedPaths`; the checkpoint holds the rest.
    run.attempt_again()
    result = await run.resume(None)

    assert result.waiting_at == "final"
    assert run.integrator.started == [("implementer", "test_writer", False)] * 2
    asked = run.request("implementer")
    assert "`tests/test_cart.py`, `tests/test_totals.py`" in asked.context
    assert [e.payload["path"] for e in run.events("protected_path_refused")] == [
        "tests/test_cart.py"
    ]
