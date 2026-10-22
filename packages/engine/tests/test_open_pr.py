"""Publishing behind a gate (phase 1.8): a run with `writer → gate → github.openPR` pauses at the
gate, opens the pull request only after approval, and records it as `pr_opened`. The tool runs
on a fake executor; the real one is `agentic_tools.github`."""

from collections.abc import Sequence
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import JsonValue, TypeAdapter

from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.gate import GateDecision
from agentic_engine.graph import checkpoint_serde, resume_workflow, run_workflow
from agentic_engine.spec import Node, WorkflowSpec, parse_spec, publish_gate_errors
from agentic_runtime import Message, ToolDefinition, ToolOutput
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime

NODE: TypeAdapter[Node] = TypeAdapter(Node)
PULL: dict[str, JsonValue] = {
    "url": "https://github.com/acme/hello/pull/7",
    "number": 7,
    "head": "agent/run/writer",
    "base": "main",
    "commit": "a" * 40,
}


class FakePublisher:
    """A `ToolExecutor` offering `github.openPR`; records the calls it gets."""

    def __init__(self, output: ToolOutput | None = None) -> None:
        self.calls: list[tuple[str, dict[str, JsonValue], str | None]] = []
        self.output = output or ToolOutput(text="opened #7", data=PULL)

    def definitions(self) -> Sequence[ToolDefinition]:
        return [ToolDefinition(name="github.openPR")]

    async def call(
        self, name: str, arguments: dict[str, JsonValue], *, node_id: str | None = None
    ) -> ToolOutput:
        self.calls.append((name, arguments, node_id))
        return self.output


def spec(*steps: dict[str, JsonValue]) -> WorkflowSpec:
    return parse_spec(
        {
            "spec_version": "0",
            "id": "publish",
            "name": "Publish",
            "root": {"type": "sequence", "id": "main", "steps": list(steps)},
        }
    )


WRITER: dict[str, JsonValue] = {
    "type": "agent",
    "id": "writer",
    "role": "W",
    "instructions": "Write.",
    "tools": ["repo.write_file", "repo.commit"],
}
GATE: dict[str, JsonValue] = {"type": "gate", "id": "gate", "title": "Publish?"}
PUBLISH: dict[str, JsonValue] = {
    "type": "tool",
    "id": "publish",
    "tool": "github.openPR",
    "args": {"from_node": "writer", "title": "Add notes"},
}


class Run:
    def __init__(self, tools: FakePublisher) -> None:
        self.spec = spec(WRITER, GATE, PUBLISH)
        self.tools = tools
        self.runtime = FakeRuntime({"writer": [Message(text="notes written"), ECHO_USAGE]})
        self.run_id = uuid4()
        self.sink = InMemoryEventSink()
        self.checkpointer = InMemorySaver(serde=checkpoint_serde())

    async def start(self) -> str:
        result = await run_workflow(
            self.spec,
            self.runtime,
            "go",
            run_id=self.run_id,
            sink=self.sink,
            checkpointer=self.checkpointer,
            tools=self.tools,
        )
        return result.status

    async def decide(self, decision: GateDecision) -> str:
        result = await resume_workflow(
            self.spec,
            self.runtime,
            "go",
            run_id=self.run_id,
            sink=self.sink,
            checkpointer=self.checkpointer,
            next_seq=self.sink.events[-1].seq + 1,
            attempt=2,
            tools=self.tools,
            decision=decision,
        )
        return result.status

    def types(self, events: list[RunEvent] | None = None) -> list[tuple[str, str | None]]:
        return [(e.type, e.node_id) for e in (events or self.sink.events)]


async def test_the_pull_request_is_opened_only_after_approval() -> None:
    tools = FakePublisher()
    run = Run(tools)

    assert await run.start() == "waiting"
    assert tools.calls == []
    paused = len(run.sink.events)

    assert await run.decide(GateDecision(decision="approve", decided_by="ada")) == "completed"

    assert tools.calls == [
        ("github.openPR", {"from_node": "writer", "title": "Add notes"}, "publish")
    ]
    after = run.types(run.sink.events[paused:])
    assert after[after.index(("node_started", "publish")) :] == [
        ("node_started", "publish"),
        ("tool_call", "publish"),
        ("tool_result", "publish"),
        ("pr_opened", "publish"),
        ("node_completed", "publish"),
        ("run_completed", None),
    ]
    (opened,) = [e for e in run.sink.events if e.type == "pr_opened"]
    assert opened.payload == PULL
    assert [e.seq for e in run.sink.events] == list(range(1, len(run.sink.events) + 1))


async def test_a_rejected_gate_publishes_nothing() -> None:
    tools = FakePublisher()
    run = Run(tools)
    await run.start()

    assert await run.decide(GateDecision(decision="reject", comment="no")) == "cancelled"

    assert tools.calls == []
    assert "pr_opened" not in {e.type for e in run.sink.events}


async def test_a_failed_publish_fails_the_run_without_pr_opened() -> None:
    tools = FakePublisher(ToolOutput(text="the branch already exists on GitHub", is_error=True))
    run = Run(tools)
    await run.start()

    assert await run.decide(GateDecision(decision="approve")) == "failed"

    assert "pr_opened" not in {e.type for e in run.sink.events}
    (failed,) = [e for e in run.sink.events if e.type == "node_failed"]
    assert failed.payload == {"error": "the branch already exists on GitHub"}


@pytest.mark.parametrize(
    ("steps", "message"),
    [
        ((WRITER, GATE, PUBLISH), None),
        ((WRITER, PUBLISH), "must come after a gate that follows 'writer'"),
        ((GATE, WRITER, PUBLISH), "must come after a gate that follows 'writer'"),
        (
            (WRITER, GATE, {**PUBLISH, "args": {"title": "x"}}),
            "needs `from_node`, the writer to publish",
        ),
        (
            ({**WRITER, "tools": ["repo.read_file"]}, GATE, PUBLISH),
            "`from_node` 'writer' is not a writer",
        ),
        (
            (
                WRITER,
                GATE,
                {**PUBLISH, "args": {"from_node": "later", "title": "x"}},
                WRITER | {"id": "later"},
            ),
            "`from_node` 'later' is not a node that runs before it",
        ),
    ],
)
def test_publish_gate_errors(steps: tuple[dict[str, JsonValue], ...], message: str | None) -> None:
    # The node tree alone, without the spec-level check that calls this.
    root = NODE.validate_python({"type": "sequence", "id": "main", "steps": list(steps)})

    errors = publish_gate_errors(root)

    if message is None:
        assert errors == []
    else:
        assert len(errors) == 1 and message in errors[0], errors


def test_a_nested_gate_counts_in_run_order() -> None:
    nested = spec(
        WRITER,
        {"type": "sequence", "id": "review", "steps": [GATE]},
        PUBLISH,
    )

    assert publish_gate_errors(nested.root) == []
