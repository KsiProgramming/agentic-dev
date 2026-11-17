"""Runs a `repo.commitArtifacts` tool node (7.5): the run artifacts it reads are committed onto
an earlier writer's branch (`into`, an orchestrator's integration branch), as `<dir>/<name>`, so
the pull request carries them and the gate before it shows them in the diff.

The engine runs it, not a tool server: the files are the run's own artifacts, and the commit
goes through the run's `GateReview`, the path a gate's edits take, so the engine never runs git
and committing the same files again makes no commit (a resumed run).
"""

import re
import unicodedata
from collections.abc import Mapping
from typing import Final

from pydantic import JsonValue

from agentic_engine.agent import AgentNodeResult, IssueBrief, OnAgentEvent
from agentic_engine.artifacts import ArtifactRef, ArtifactStore
from agentic_engine.gate import FileEdit, GateReview, GateReviewError
from agentic_engine.spec import COMMIT_DIR_PLACEHOLDER, ToolNode, commit_dir_problem
from agentic_runtime import ToolCall, ToolResult

MAX_SLUG = 40
"""The longest slug of an issue's summary in a folder name (`<KEY>-<slug>`)."""

_ISSUE_KEY: Final = re.compile(r"^[A-Za-z][A-Za-z0-9_]*-[1-9][0-9]{0,9}$")


def summary_slug(summary: str) -> str:
    """`summary` as lowercase ASCII words joined by `-`, cut on a word at `MAX_SLUG` characters;
    empty when it has no ASCII letters or digits."""
    ascii_text = unicodedata.normalize("NFKD", summary).encode("ascii", "ignore").decode()
    slug = ""
    for word in re.findall(r"[a-z0-9]+", ascii_text.lower()):
        longer = f"{slug}-{word}" if slug else word
        if len(longer) > MAX_SLUG:
            break
        slug = longer
    return slug


def issue_folder(issue: IssueBrief | None, request: str | None) -> str | None:
    """The run's Jira issue as a folder name: `<KEY>-<slug of its summary>`, or `<KEY>` when the
    summary gives no slug. The key is the brief's, else the run's request when it is one issue
    key; `None` when the run has no issue."""
    if issue is not None:
        slug = summary_slug(issue.summary)
        return f"{issue.key}-{slug}" if slug else issue.key
    key = (request or "").strip()
    return key.upper() if _ISSUE_KEY.match(key) else None


def commit_folder(folder: str, issue: IssueBrief | None, request: str | None) -> str:
    """`dir` with its placeholder put in place, without leading or trailing slashes. Raises
    `ValueError` when it names the issue and the run has none, or is not a safe folder."""
    if (problem := commit_dir_problem(folder)) is not None:
        raise ValueError(problem)
    if COMMIT_DIR_PLACEHOLDER in folder:
        named = issue_folder(issue, request)
        if named is None:
            raise ValueError(
                f"`dir` names {COMMIT_DIR_PLACEHOLDER}, but the run was not started from a Jira "
                "issue"
            )
        folder = folder.replace(COMMIT_DIR_PLACEHOLDER, named)
    return folder.strip("/")


def commit_message(issue: IssueBrief | None, request: str | None) -> str:
    """The message of the commit: names the issue when the run has one."""
    named = issue.key if issue is not None else issue_folder(None, request)
    return f"Add Spec Kit files for {named}" if named else "Add the run's spec files"


async def run_commit_node(
    node: ToolNode,
    review: GateReview | None,
    artifacts: ArtifactStore,
    refs: Mapping[str, ArtifactRef],
    issue: IssueBrief | None,
    request: str | None,
    on_event: OnAgentEvent | None = None,
) -> AgentNodeResult:
    """Commit the artifacts `node` reads onto the branch of `into`, as `<dir>/<name>`, and report
    it as a `tool_call` and a `tool_result`, as any tool node. Its `data` is `{into, dir, paths,
    commit}`. A run with no sandbox, an artifact not written, a bad `dir` or a commit that fails
    fails the node; it never raises."""
    call = ToolCall(call_id=f"{node.id}_call", name=node.tool, arguments=dict(node.args))
    if on_event is not None:
        await on_event(call)
    into = str(node.args.get("into"))
    data: dict[str, JsonValue] | None = None
    try:
        if review is None:
            raise ValueError("this run has no repository to commit to")
        folder = commit_folder(str(node.args.get("dir", "")), issue, request)
        edits: list[FileEdit] = []
        for name in node.reads:
            ref = refs.get(name)
            stored = await artifacts.get(name, ref.version) if ref is not None else None
            if stored is None:
                raise ValueError(f"artifact {name!r} was not written")
            edits.append(FileEdit(node_id=into, path=f"{folder}/{name}", content=stored.content))
        tips = await review.commit(edits, commit_message(issue, request))
        paths: list[JsonValue] = [edit.path for edit in edits]
        data = {"into": into, "dir": folder, "paths": paths, "commit": tips.get(into)}
        text = f"Committed {', '.join(e.path for e in edits)} on the branch of {into!r}."
        error = None
    except (ValueError, GateReviewError) as e:
        text = error = f"cannot commit the artifacts: {e}"
    result = ToolResult(call_id=call.call_id, output=text, is_error=error is not None)
    if on_event is not None:
        await on_event(result)
    return AgentNodeResult(
        status="failed" if error else "completed",
        text=text,
        usage=None,
        tool_calls=[call],
        events=[call, result],
        error=error,
        data=data,
    )
