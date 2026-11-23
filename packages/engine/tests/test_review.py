"""Independent review agents (13.6). As lessons rule 1 asks, the tests assert what each lens
*receives* (its input, tools, context and where its reads go), not only the graph's shape."""

import json
from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

from agentic_engine.agent import RunContext
from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.graph import WorkflowRunResult, checkpoint_serde, run_workflow
from agentic_engine.policy import PLATFORM_POLICY
from agentic_engine.review import LENSES, review_flow
from agentic_engine.spec import WorkflowSpec, parse_spec, validate_workflow
from agentic_runtime import AgentRequest, Message, ReadableWriters
from agentic_runtime.fake import ECHO_USAGE, CallTool, FakeRuntime
from agentic_runtime.findings import Finding, build_report
from agentic_runtime.testing import ScriptedToolExecutor

REQUEST = "Add sum()."
DIFF = (
    "writer changed 1 file (+3 -0) against the run's base abc1234:\n"
    "added src/sum.py (+3 -0)\n\n"
    "diff --git a/src/sum.py b/src/sum.py\n+def sum(a, b):\n+    return a + b\n"
)
SPEC_TEXT = "# Spec\n\nsum adds two numbers."
LENS_IDS = ("correctness", "security", "performance")


def finding(severity: str, category: str, path: str = "src/sum.py", line: int = 2) -> Finding:
    return Finding(
        tool="agent", rule="r", severity=severity,  # type: ignore[arg-type]
        category=category, path=path, line=line, message="Look.",
    )  # fmt: skip


def report(*findings: Finding) -> str:
    built = build_report("agent", [], findings)
    return json.dumps(built.model_dump(mode="json"))


def workflow(lenses: tuple[str, ...] = LENS_IDS, **flow: Any) -> WorkflowSpec:
    steps: list[dict[str, Any]] = [
        {"type": "tool", "id": "spec", "tool": "repo.list_files", "writes": "spec.md"},
        {
            "type": "agent", "id": "writer", "role": "Engineer", "instructions": "Build it.",
            "tools": ["repo.write_file", "repo.commit"], "writes": "work.md",
        },
        *review_flow(of=flow.pop("of", None), lenses=lenses, spec_from="spec.md", **flow),
    ]  # fmt: skip
    return parse_spec(
        {"spec_version": "0", "id": "review", "name": "Review",
         "root": {"type": "sequence", "id": "main", "steps": steps}}
    )  # fmt: skip


class Tools(ScriptedToolExecutor):
    def __init__(self) -> None:
        super().__init__(
            {
                "repo.write_file": "wrote",
                "repo.commit": "abc on agent/x: done",
                "repo.list_files": SPEC_TEXT,
                "repo.diff": DIFF,
            }
        )


class Review:
    def __init__(self, workflow: WorkflowSpec, answers: dict[str, str] | None = None) -> None:
        self.tools = Tools()
        self.readable = ReadableWriters(lambda node: f"agent/run/{node}")
        scripts: dict[str, list[Any]] = {
            "writer": [
                CallTool("repo.write_file", {"path": "src/sum.py", "content": "x"}),
                CallTool("repo.commit", {"message": "work"}),
                Message(text="WRITER-NARRATIVE: I did everything right."),
                ECHO_USAGE,
            ]
        }
        for lens in LENSES:
            scripts[f"review_{lens}"] = [Message(text=report()), ECHO_USAGE]
        for node, text in (answers or {}).items():
            scripts[node] = [Message(text=text), ECHO_USAGE]
        self.runtime = FakeRuntime(scripts, tools=self.tools)
        self.sink = InMemoryEventSink()
        self.workflow = workflow

    async def run(self) -> WorkflowRunResult:
        return await run_workflow(
            self.workflow, self.runtime, REQUEST, run_id=uuid4(), sink=self.sink,
            checkpointer=InMemorySaver(serde=checkpoint_serde()), tools=self.tools,
            readable=self.readable, context=RunContext(repo="acme/shop", request=REQUEST),
        )  # fmt: skip

    def request(self, node_id: str) -> AgentRequest:
        return next(r for r in self.runtime.requests if r.node_id == node_id)

    def started(self, node_id: str) -> RunEvent:
        return next(
            e for e in self.sink.events if e.type == "node_started" and e.node_id == node_id
        )


def test_a_review_flow_validates() -> None:
    assert validate_workflow(
        workflow().model_dump(mode="json", by_alias=True),
        policy=PLATFORM_POLICY, priced=frozenset({"default"}).__contains__,
        default_model="default",
    ) == []  # fmt: skip


async def test_a_lens_receives_the_spec_the_change_and_the_evidence_and_nothing_else() -> None:
    run = Review(workflow())

    result = await run.run()

    assert result.status == "completed"
    for lens in LENS_IDS:
        got = run.request(f"review_{lens}").input
        assert "## Spec\n\n# Spec\n\nsum adds two numbers." in got
        assert "## Change\n\nwriter changed 1 file (+3 -0)" in got
        assert "return a + b" in got
        assert "## Evidence\n\nnone" in got  # no gate collected a pack: the heading says so
        # Neither the writer's answer nor the previous step's output reaches a lens.
        assert "WRITER-NARRATIVE" not in got
        assert got.startswith("Reviewing `writer`'s work.")


async def test_a_lens_has_only_the_read_tools_and_is_told_the_request() -> None:
    run = Review(workflow())

    await run.run()

    for lens in LENS_IDS:
        request = run.request(f"review_{lens}")
        assert sorted(request.tools) == [
            "repo.diff", "repo.list_files", "repo.list_modules", "repo.read_file", "repo.search",
        ]  # fmt: skip
        assert not any(t.startswith("artifacts.") for t in request.tools)
        assert REQUEST in request.context  # lessons 8: it still knows the goal
        assert "committed work, the code you are reviewing" in request.context
        assert request.output_schema is not None  # the engine types its findings
        assert f'category` "{LENSES[lens].category}"' in request.instructions


async def test_a_lens_reads_the_writers_work_and_its_start_says_what_it_was_given() -> None:
    run = Review(workflow())

    await run.run()

    assert run.readable.review_of("review_security") == "writer"
    review = run.started("review_security").payload["review"]
    assert review == {
        "of": "writer", "spec": "spec.md", "spec_version": 1,
        "diff": {"files": 1, "added": 3, "removed": 0}, "evidence": False,
    }  # fmt: skip
    # The engine asked for the change as the reviewed writer's, once per lens.
    diffs = [args for name, args in run.tools.calls if name == "repo.diff"]
    assert diffs == [{"node": "writer"}] * 3


async def test_of_names_the_reviewed_writer() -> None:
    run = Review(workflow(of="writer"))

    await run.run()

    assert run.started("review_correctness").payload["review"]["of"] == "writer"  # type: ignore[index]


async def test_the_merged_report_has_every_lens_finding_once() -> None:
    same = finding("medium", "security")
    run = Review(
        workflow(),
        {
            "review_security": report(same, finding("high", "security", line=9)),
            "review_correctness": report(same),
        },
    )

    result = await run.run()

    merged = json.loads(result.text)
    assert merged["scanner"] == "merged"
    assert len(merged["findings"]) == 2
    assert merged["counts"]["high"] == 1


async def test_a_lens_that_could_not_run_is_a_failed_check_not_a_failed_run() -> None:
    run = Review(workflow(), {"review_performance": "not json at all"})

    result = await run.run()

    assert result.status == "completed"
    checks = json.loads(result.text)["checks"]
    assert [c["tool"] for c in checks if c["kind"] == "branch"] == ["review_performance"]


def test_a_review_with_no_writer_before_it_is_refused_when_the_spec_is_read() -> None:
    with pytest.raises(ValidationError, match="no writer runs before this node"):
        parse_spec(
            {"spec_version": "0", "id": "x", "name": "X",
             "root": {"type": "sequence", "id": "main",
                      "steps": [*review_flow(lenses=("correctness",))]}}
        )  # fmt: skip
