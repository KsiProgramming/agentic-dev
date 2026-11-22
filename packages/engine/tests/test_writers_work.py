"""What each agent receives when later steps read the writers' work (13.1, lessons rule 1): the
reviewer of `review-two-writers` runs after two writers in a plain sequence, with no
orchestrator. The tests check what every agent is told and what its tool calls reach, not only the
outcome."""

import asyncio
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import JsonValue

from agentic_engine.agent import RunContext
from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.graph import checkpoint_serde, resume_workflow, run_workflow
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import AgentRequest, Message, ReadableWriters, ToolOutput
from agentic_runtime.fake import ECHO_USAGE, CallTool, Delay, FakeRuntime, Script
from agentic_runtime.testing import ScriptedToolExecutor

FIXTURE = Path(__file__).parent / "fixtures" / "specs" / "valid" / "review-two-writers.json"
VERDICT = json.dumps({"verdict": "ok", "feedback": "Both writers' work is ready."})
CONTEXT = RunContext(repo="acme/shop", request="Cover parse_price with tests, then simplify it.")


def load() -> WorkflowSpec:
    return parse_spec(json.loads(FIXTURE.read_text(encoding="utf-8")))


class Tools(ScriptedToolExecutor):
    """The repo tools, which record the writers the run had told them it may read at each call."""

    def __init__(self, readable: ReadableWriters) -> None:
        super().__init__(
            {
                "repo.read_file": "1\tdef test_price(): pass",
                "repo.write_file": "wrote it",
                "repo.commit": "abc1234 on agent/run/x: done",
                "repo.diff": ToolOutput(
                    text="x changed 1 file (+1 -0) against the run's base 1234567:"
                ),
            }
        )
        self.readable = readable
        self.readable_at_call: list[tuple[str, str | None, list[str]]] = []

    async def call(
        self, name: str, arguments: dict[str, JsonValue], *, node_id: str | None = None
    ) -> ToolOutput:
        who = [w.node_id for w in self.readable.writers()]
        self.readable_at_call.append((name, node_id, who))
        return await super().call(name, arguments, node_id=node_id)


def scripts(*, reviewer: Script | None = None) -> dict[str, Script]:
    return {
        "test_writer": [
            CallTool("repo.write_file", {"path": "tests/test_price.py", "content": "x"}),
            CallTool("repo.commit", {"message": "Add tests"}),
            Message(text="Added test_price."),
            ECHO_USAGE,
        ],
        "refactorer": [
            CallTool("repo.read_file", {"path": "tests/test_price.py", "node": "test_writer"}),
            CallTool("repo.write_file", {"path": "src/price.py", "content": "y"}),
            CallTool("repo.commit", {"message": "Simplify"}),
            Message(text="Simplified parse_price."),
            ECHO_USAGE,
        ],
        "reviewer": reviewer
        or [
            CallTool("repo.diff", {"node": "test_writer"}),
            CallTool("repo.diff", {"node": "refactorer"}),
            Message(text=VERDICT),
            ECHO_USAGE,
        ],
    }


def readable() -> ReadableWriters:
    return ReadableWriters(lambda node: f"agent/run/{node}")


def started(sink: InMemoryEventSink, node_id: str) -> RunEvent:
    return next(e for e in sink.events if e.type == "node_started" and e.node_id == node_id)


def request(runtime: FakeRuntime, node_id: str) -> AgentRequest:
    return next(r for r in runtime.requests if r.node_id == node_id)


async def run_all() -> tuple[FakeRuntime, InMemoryEventSink, Tools]:
    state = readable()
    tools = Tools(state)
    runtime = FakeRuntime(scripts(), tools=tools)
    sink = InMemoryEventSink()
    result = await run_workflow(
        load(), runtime, "go", sink=sink, tools=tools, context=CONTEXT, readable=state
    )
    assert result.status == "completed"
    return runtime, sink, tools


async def test_the_first_writer_is_told_about_no_writer() -> None:
    runtime, sink, _ = await run_all()

    assert "Work before you" not in request(runtime, "test_writer").context
    assert started(sink, "test_writer").payload["writers"] == []


async def test_the_second_writer_is_told_about_the_first() -> None:
    runtime, sink, _ = await run_all()

    context = request(runtime, "refactorer").context
    assert "# Work before you" in context
    assert "- `test_writer` (Test writer): a writer, on its own branch" in context
    assert "refactorer`" not in context.split("# Work before you")[1].split("Read a step")[0]
    assert "Your repo reads without `node` return your own branch, where you write." in context
    assert started(sink, "refactorer").payload["writers"] == [
        {"node_id": "test_writer", "kind": "writer"}
    ]


async def test_the_reviewer_has_repo_diff_and_is_told_about_both_writers() -> None:
    runtime, sink, _ = await run_all()

    asked = request(runtime, "reviewer")
    assert "repo.diff" in asked.tools
    work = asked.context.split("# Work before you")[1]
    assert work.index("`test_writer` (Test writer)") < work.index("`refactorer` (Refactoring")
    assert "`repo.diff` with `node` lists the files it changed" in work
    assert "return the run's checkout, the code as the run found it" in work
    assert asked.context.startswith(
        "This run works on the repository `acme/shop`"
    )  # the run's context first
    assert started(sink, "reviewer").payload["writers"] == [
        {"node_id": "test_writer", "kind": "writer"},
        {"node_id": "refactorer", "kind": "writer"},
    ]
    # The work is not the step's input: that is still the previous step's answer.
    assert asked.input == "Simplified parse_price."


async def test_the_reviewers_calls_reach_the_tools_as_the_reviewer_with_both_writers_ready() -> (
    None
):
    _, _, tools = await run_all()

    diffs = [c for c in tools.readable_at_call if c[0] == "repo.diff"]
    assert diffs == [
        ("repo.diff", "reviewer", ["test_writer", "refactorer"]),
        ("repo.diff", "reviewer", ["test_writer", "refactorer"]),
    ]
    assert [c[1:] for c in tools.readable_at_call if c[0] == "repo.read_file"] == [
        ("refactorer", ["test_writer"])
    ]
    assert [a for n, a in tools.calls if n == "repo.diff"] == [
        {"node": "test_writer"},
        {"node": "refactorer"},
    ]


def saver() -> InMemorySaver:
    return InMemorySaver(serde=checkpoint_serde())


async def test_a_run_cut_off_after_the_refactorer_resumes_with_the_same_writers() -> None:
    first_runtime, first_sink, _ = await run_all()
    checkpoints, run_id = saver(), uuid4()
    state = readable()
    tools = Tools(state)
    hang = scripts(reviewer=[Delay(60), ECHO_USAGE])
    sink = InMemoryEventSink()
    task = asyncio.create_task(
        run_workflow(
            load(),
            FakeRuntime(hang, tools=tools),
            "go",
            run_id=run_id,
            sink=sink,
            checkpointer=checkpoints,
            tools=tools,
            context=CONTEXT,
            readable=state,
        )
    )
    for _ in range(500):
        if any(e.type == "node_started" and e.node_id == "reviewer" for e in sink.events):
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    again = readable()  # a new attempt: a new object, told from the checkpointed state
    resumed_tools = Tools(again)
    runtime = FakeRuntime(scripts(), tools=resumed_tools)
    resumed_sink = InMemoryEventSink()
    result = await resume_workflow(
        load(),
        runtime,
        "go",
        run_id=_as_uuid(run_id),
        sink=resumed_sink,
        checkpointer=checkpoints,
        next_seq=len(sink.events) + 1,
        attempt=2,
        tools=resumed_tools,
        context=CONTEXT,
        readable=again,
    )

    assert result.status == "completed"
    assert [r.node_id for r in runtime.requests] == ["reviewer"]
    assert request(runtime, "reviewer").context == request(first_runtime, "reviewer").context
    assert (
        started(resumed_sink, "reviewer").payload["writers"]
        == (started(first_sink, "reviewer").payload["writers"])
    )
    diffs = [c for c in resumed_tools.readable_at_call if c[0] == "repo.diff"]
    assert [c[2] for c in diffs] == [["test_writer", "refactorer"]] * 2


def _as_uuid(value: UUID) -> UUID:
    return value
