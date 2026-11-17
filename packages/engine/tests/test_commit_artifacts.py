"""`repo.commitArtifacts` (7.5): the run artifacts a tool node reads are committed onto an earlier
writer's branch, as `<dir>/<name>`, so the pull request carries them and its gate shows them."""

from collections.abc import Sequence
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agentic_engine.agent import IssueBrief, RunContext
from agentic_engine.artifacts import InMemoryArtifactStore
from agentic_engine.commit import commit_folder, issue_folder, summary_slug
from agentic_engine.events import InMemoryEventSink
from agentic_engine.gate import FileChange, FileEdit, GateReviewError
from agentic_engine.graph import checkpoint_serde, run_workflow
from agentic_engine.policy import PLATFORM_POLICY
from agentic_engine.spec import parse_spec, validate_workflow
from agentic_runtime import AgentRequest, AgentRun, Message
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime

BRIEF = IssueBrief(
    key="PROJ-12",
    url="https://x.atlassian.net/browse/PROJ-12",
    project="PROJ",
    summary="Add CSV export!",
)


def agent(id: str, **fields: Any) -> dict[str, Any]:
    return {"type": "agent", "id": id, "role": "R", "instructions": "Go.", **fields}


def commit(**args: Any) -> dict[str, Any]:
    fields = {"into": "writer", "dir": "specs/{issue}", **args}
    return {
        "type": "tool",
        "id": "commit_specs",
        "tool": "repo.commitArtifacts",
        "args": fields,
        "reads": ["spec.md", "plan.md"],
    }


def steps(*steps: dict[str, Any]) -> dict[str, Any]:
    return {
        "spec_version": "0",
        "id": "wf",
        "name": "Workflow",
        "input": {"required": True, "label": "Issue"},
        "root": {"type": "sequence", "id": "main", "steps": list(steps)},
    }


WRITER = agent("writer", tools=["repo.write_file", "repo.commit"])
SPEC = agent("spec_writer", writes="spec.md")
PLAN = agent("planner", writes="plan.md")
GATE = {"type": "gate", "id": "approve", "title": "Open the PR?"}
PUBLISH = {
    "type": "tool",
    "id": "publish",
    "tool": "github.openPR",
    "args": {"from_node": "writer", "title": "T"},
}


def issues(raw: dict[str, Any]) -> list[tuple[str, str, str]]:
    found = validate_workflow(raw, policy=PLATFORM_POLICY, priced=lambda _: True, default_model="m")
    return [(i.code, i.path, i.message) for i in found]


def test_a_commit_before_the_gate_that_shows_the_branch_is_fine() -> None:
    assert issues(steps(SPEC, PLAN, WRITER, commit(), GATE, PUBLISH)) == []


def test_a_commit_after_the_gate_needs_another_gate_before_the_publish() -> None:
    found = issues(steps(SPEC, PLAN, WRITER, GATE, commit(), PUBLISH))
    assert [(code, path) for code, path, _ in found] == [("publish_without_gate", "root.steps[5]")]


@pytest.mark.parametrize(
    ("node", "message"),
    [
        (commit(into="nobody"), "`into` must name an earlier step"),
        (commit(into="spec_writer"), "'spec_writer' is not a writer"),
        (commit(dir="../escape"), "'..'"),
        (commit(dir="/abs"), "not a relative path"),
        (commit(dir="specs/{key}"), "placeholder other than {issue}"),
        (commit(dir="a/.git/b"), "'.git'"),
        (commit(extra=1), "takes `into` and `dir` only"),
        ({**commit(), "reads": []}, "give it `reads`"),
    ],
)
def test_a_commit_names_an_earlier_writer_and_a_safe_folder(
    node: dict[str, Any], message: str
) -> None:
    found = issues(steps(SPEC, PLAN, WRITER, node, GATE, PUBLISH))
    assert len(found) == 1
    assert found[0][0] == "reference" and message in found[0][2]


def test_only_a_tool_node_of_the_root_sequence_commits() -> None:
    by_agent = agent("a", tools=["repo.commitArtifacts"])
    nested = {"type": "sequence", "id": "inner", "steps": [commit()]}
    assert "can only be called by a tool node" in issues(steps(SPEC, PLAN, WRITER, by_agent))[0][2]
    assert "step of the root sequence" in issues(steps(SPEC, PLAN, WRITER, nested))[0][2]


def test_the_folder_is_the_issue_key_and_a_slug_of_its_summary() -> None:
    assert summary_slug("Add CSV export!") == "add-csv-export"
    assert summary_slug("Café — naïve façade") == "cafe-naive-facade"
    assert summary_slug("一二三") == ""
    assert len(summary_slug("word " * 30)) <= 40
    assert issue_folder(BRIEF, None) == "PROJ-12-add-csv-export"
    assert issue_folder(BRIEF.model_copy(update={"summary": "!!"}), None) == "PROJ-12"
    assert issue_folder(None, " proj-7 ") == "PROJ-7"
    assert issue_folder(None, "not a key") is None
    assert commit_folder("specs/{issue}/", BRIEF, None) == "specs/PROJ-12-add-csv-export"
    with pytest.raises(ValueError, match="not started from a Jira issue"):
        commit_folder("specs/{issue}", None, "a change")


class Review:
    """A writer branch kept as a dict, as the gate review keeps one."""

    def __init__(self) -> None:
        self.files: dict[str, str] = {}
        self.commits: list[tuple[str, list[FileEdit]]] = []
        self.fail: Exception | None = None

    async def changes(self, ran: Sequence[str]) -> list[FileChange]:
        return [
            FileChange(node_id="writer", path=path, status="added", editable=True, after=text)
            for path, text in self.files.items()
            if "writer" in ran
        ]

    async def apply(self, gate_id: str, edits: Sequence[FileEdit]) -> dict[str, str]:
        return await self.commit(edits, f"Edit at gate {gate_id}")

    async def commit(self, edits: Sequence[FileEdit], message: str) -> dict[str, str]:
        if self.fail is not None:
            raise self.fail
        self.commits.append((message, list(edits)))
        self.files.update({e.path: e.content for e in edits})
        return {"writer": "abc123"}


class Answers:
    def start(self, request: AgentRequest) -> AgentRun:
        text = f"# {request.node_id}"
        return FakeRuntime({request.node_id: [Message(text=text), ECHO_USAGE]}).start(request)


async def run(review: Review | None, context: RunContext | None = None) -> Any:
    sink = InMemoryEventSink()
    result = await run_workflow(
        parse_spec(steps(SPEC, PLAN, WRITER, commit(), GATE)),
        Answers(),
        "PROJ-12",
        sink=sink,
        checkpointer=InMemorySaver(serde=checkpoint_serde()),
        review=review,
        artifacts=InMemoryArtifactStore(),
        context=context or RunContext(request="PROJ-12", issue=BRIEF),
    )
    return result, sink


async def test_the_artifacts_are_committed_on_the_writers_branch_and_shown_at_the_gate() -> None:
    review = Review()

    result, sink = await run(review)

    assert result.status == "waiting"
    [(message, edits)] = review.commits
    assert message == "Add Spec Kit files for PROJ-12"
    assert [(e.node_id, e.path, e.content) for e in edits] == [
        ("writer", "specs/PROJ-12-add-csv-export/spec.md", "# spec_writer"),
        ("writer", "specs/PROJ-12-add-csv-export/plan.md", "# planner"),
    ]
    assert result.results["commit_specs"].data == {
        "into": "writer",
        "dir": "specs/PROJ-12-add-csv-export",
        "paths": ["specs/PROJ-12-add-csv-export/spec.md", "specs/PROJ-12-add-csv-export/plan.md"],
        "commit": "abc123",
    }
    waiting = next(e for e in sink.events if e.type == "gate_waiting")
    shown = [c["path"] for c in waiting.payload["changes"]]
    assert shown == ["specs/PROJ-12-add-csv-export/spec.md", "specs/PROJ-12-add-csv-export/plan.md"]
    call = next(e for e in sink.events if e.type == "tool_call" and e.node_id == "commit_specs")
    assert call.payload["name"] == "repo.commitArtifacts"


@pytest.mark.parametrize(
    ("review", "context", "error"),
    [
        (None, None, "this run has no repository to commit to"),
        (Review(), RunContext(request="a change"), "not started from a Jira issue"),
    ],
)
async def test_a_commit_that_cannot_be_made_fails_the_step(
    review: Review | None, context: RunContext | None, error: str
) -> None:
    result, _ = await run(review, context)

    assert result.status == "failed"
    assert result.stopped_at == "commit_specs"
    assert error in (result.results["commit_specs"].error or "")


async def test_a_commit_the_sandbox_refuses_fails_the_step() -> None:
    review = Review()
    review.fail = GateReviewError("could not commit on agent/x/writer")

    result, _ = await run(review)

    assert result.status == "failed"
    assert "could not commit on agent/x/writer" in (result.results["commit_specs"].error or "")
