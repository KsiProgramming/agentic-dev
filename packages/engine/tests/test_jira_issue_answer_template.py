"""The "Answer a Jira issue" template (7.2): one reading analyst, a gate on its comment, and a
gated `jira.comment` on the issue the run was started with."""

from typing import cast
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import JsonValue, ValidationError

from agentic_engine.agent import RunContext
from agentic_engine.artifacts import InMemoryArtifactStore
from agentic_engine.events import InMemoryEventSink
from agentic_engine.gate import GateDecision
from agentic_engine.graph import checkpoint_serde, resume_workflow, run_workflow
from agentic_engine.policy import PLATFORM_POLICY
from agentic_engine.spec import (
    JIRA_WRITE_TOOLS,
    PUBLISH_TOOLS,
    WRITE_TOOLS,
    AgentNode,
    iter_nodes,
    node_tools,
    validate_workflow,
)
from agentic_engine.templates import (
    JiraIssueAnswerParams,
    build_jira_issue_answer_spec,
    get_template,
)
from agentic_runtime import Message, ToolDefinition, ToolOutput
from agentic_runtime.fake import ECHO_USAGE, CallTool, FakeRuntime
from agentic_runtime.pricing import DEFAULT_PRICES
from agentic_runtime.testing import is_plan_call, plan_answer

COMMENT = "The limit lives in `gateway/limits.py`."


class Tools:
    """The run's tools as the analyst sees them: Jira and the repo's read tools."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object], str | None]] = []

    def definitions(self) -> list[ToolDefinition]:
        names = ["jira.getIssue", "jira.search", "jira.comment"]
        names += ["repo.list_files", "repo.read_file", "repo.search"]
        return [ToolDefinition(name=n) for n in names]

    async def call(
        self, name: str, arguments: dict[str, object], *, node_id: str | None = None
    ) -> ToolOutput:
        if is_plan_call(cast(dict[str, JsonValue], arguments)):
            return plan_answer(name, cast(dict[str, JsonValue], arguments))
        self.calls.append((name, arguments, node_id))
        return ToolOutput(text=f"{name} ok")


def test_it_is_registered_and_requires_jira() -> None:
    template = get_template("jira-issue-answer")

    assert template is not None
    assert template.requires == ("claude", "github", "jira")


@pytest.mark.parametrize("model", [None, *DEFAULT_PRICES])
def test_every_option_validates(model: str | None) -> None:
    spec = build_jira_issue_answer_spec(JiraIssueAnswerParams(model=model))

    assert (
        validate_workflow(
            spec.model_dump(mode="json", by_alias=True, exclude_none=True),
            policy=PLATFORM_POLICY,
            priced=lambda _: True,
            default_model="default",
        )
        == []
    )


def test_an_unpriced_model_is_refused() -> None:
    with pytest.raises(ValidationError):
        JiraIssueAnswerParams(model="gpt-9")


def test_the_analyst_only_reads_and_the_input_is_the_issue() -> None:
    spec = build_jira_issue_answer_spec(JiraIssueAnswerParams())
    nodes = dict((node.id, node) for _, node in iter_nodes(spec.root))

    analyst = nodes["analyst"]
    assert isinstance(analyst, AgentNode)
    assert not set(node_tools(analyst)) & (WRITE_TOOLS | PUBLISH_TOOLS | JIRA_WRITE_TOOLS)
    assert "jira.getIssue" in analyst.tools
    assert "repo.read_file" in analyst.tools
    assert analyst.instructions.startswith("Your input is the key of a Jira issue")
    assert "never instructions" in analyst.instructions
    assert spec.input is not None and spec.input.required


async def test_a_run_reads_the_issue_and_posts_the_approved_comment() -> None:
    """Lessons rule 1, for the template: what the analyst receives, and what is posted."""
    spec = build_jira_issue_answer_spec(JiraIssueAnswerParams())
    tools = Tools()
    runtime = FakeRuntime(
        {
            "analyst": [
                CallTool("jira.getIssue", {"issue": "PROJ-12"}),
                CallTool("repo.read_file", {"path": "gateway/limits.py"}),
                Message(text=COMMENT),
                ECHO_USAGE,
            ]
        },
        tools=tools,  # type: ignore[arg-type]
    )
    sink = InMemoryEventSink()
    common = {
        "run_id": uuid4(),
        "sink": sink,
        "checkpointer": InMemorySaver(serde=checkpoint_serde()),
        "tools": tools,
        "artifacts": InMemoryArtifactStore(),
        "context": RunContext(repo="acme/api", request="PROJ-12"),
    }

    first = await run_workflow(spec, runtime, "PROJ-12", **common)  # type: ignore[arg-type]
    assert first.status == "waiting"
    (request,) = runtime.requests
    assert request.input == "PROJ-12"
    assert request.tools == [
        "jira.getIssue",
        "jira.search",
        "repo.list_files",
        "repo.read_file",
        "repo.search",
    ]
    assert "acme/api" in request.context
    waiting = next(e for e in sink.events if e.type == "gate_waiting")
    assert waiting.payload is not None and waiting.payload["artifact"] == COMMENT

    done = await resume_workflow(
        spec,
        runtime,
        "PROJ-12",
        next_seq=sink.events[-1].seq + 1,
        attempt=2,
        decision=GateDecision(decision="approve"),
        **common,  # type: ignore[arg-type]
    )

    assert done.status == "completed"
    assert tools.calls[-1] == ("jira.comment", {"issue": "PROJ-12", "body": COMMENT}, "post")
