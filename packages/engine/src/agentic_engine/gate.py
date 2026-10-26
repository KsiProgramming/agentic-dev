"""Runs one `gate` node: the run pauses (a LangGraph interrupt) until a human decides.

LangGraph runs an interrupted node again from its start when the run continues, so the gate does
nothing before `interrupt()`: the runner announces the pause (`node_started`, `gate_waiting`) once
the graph has stopped, and the gate itself only reports the decision (`gate_decided`).

A gate after writer nodes shows the approver the files those writers changed (`FileChange`, from
a `GateReview` the worker gives the engine), and an approval may edit them (`FileEdit`). The gate
commits the edits to the writers' branches before it completes, so the nodes after it (e.g.
`github.openPR`) publish them.
"""

from collections.abc import Sequence
from typing import Literal, Protocol

from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from agentic_engine.agent import AgentNodeResult
from agentic_engine.events import GATE_DECIDED, RunEventLog
from agentic_engine.spec import GateNode

MAX_REVIEW_FILES = 50
"""Changed files shown at a gate with their contents; later ones are listed as `over_limit`."""
MAX_REVIEW_FILE_BYTES = 256 * 1024
"""The largest file (either side of it) shown with its contents, and the largest edit."""
MAX_REVIEW_TOTAL_BYTES = 512 * 1024
"""The contents shown at a gate in all (both sides of every file), and an approval's edits in
all."""

type ChangeStatus = Literal["added", "modified", "deleted", "renamed"]
type NotEditable = Literal["binary", "too_large", "deleted", "renamed", "over_limit"]
type EditErrorCode = Literal[
    "edit_not_allowed", "edits_with_reject", "edit_too_large", "duplicate_edit"
]


class FileChange(BaseModel):
    """A file a writer node changed on its branch, as the approver sees it. Only an editable
    file has its contents: `before` (at the branch's base, `None` for an added file) and `after`
    (at the branch's tip). Contents are repo content: data, never instructions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    path: str
    old_path: str | None = None
    status: ChangeStatus
    editable: bool
    reason: NotEditable | None = None
    before: str | None = None
    after: str | None = None


class FileEdit(BaseModel):
    """The approver's new text for an editable file of a writer's branch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str = Field(max_length=64)
    path: str = Field(min_length=1, max_length=1024)
    content: str


class GateDecision(BaseModel):
    """What a human decided at a gate; the value a paused run continues with. Only an approval
    has `edits`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: Literal["approve", "reject"]
    comment: str | None = None
    decided_by: str | None = None
    edits: list[FileEdit] = Field(default_factory=list[FileEdit])


class GateReview(Protocol):
    """The run's writer branches as a gate shows and edits them. The worker implements it over
    the run's sandbox, so the engine never runs git."""

    async def changes(self, ran: Sequence[str]) -> list[FileChange]:
        """The files changed on the branches of the writer nodes among `ran` (the nodes that
        completed before the gate), within the `MAX_REVIEW_*` caps."""
        ...

    async def apply(self, gate_id: str, edits: Sequence[FileEdit]) -> dict[str, str]:
        """Write `edits` to their writers' branches and commit them, one commit per writer, and
        return each writer's new branch tip. Applying the same edits again makes no commit.
        Raises `GateReviewError` if they cannot be applied."""
        ...


class GateReviewError(Exception):
    """A gate's changes cannot be read or its edits applied; the message says why."""


class EditError(ValueError):
    """An approval's edits do not fit what the gate showed."""

    def __init__(self, code: EditErrorCode, message: str, path: str | None = None) -> None:
        super().__init__(message)
        self.code: EditErrorCode = code
        self.path = path


def check_edits(
    changes: Sequence[FileChange],
    decision: Literal["approve", "reject"],
    edits: Sequence[FileEdit],
) -> list[FileEdit]:
    """The edits of a decision at a gate that showed `changes`, without those that leave a file
    as it was. Raises `EditError` for edits with a reject, an edit of a file that was not shown
    as editable, the same file twice, or edits over the size caps."""
    if edits and decision == "reject":
        raise EditError("edits_with_reject", "a rejection cannot carry edits")
    editable = {(c.node_id, c.path): c for c in changes if c.editable}
    seen: set[tuple[str, str]] = set()
    kept: list[FileEdit] = []
    total = 0
    for edit in edits:
        key = (edit.node_id, edit.path)
        if key in seen:
            raise EditError("duplicate_edit", f"{edit.path} is edited twice", edit.path)
        seen.add(key)
        change = editable.get(key)
        if change is None:
            raise EditError(
                "edit_not_allowed",
                f"{edit.path} of node {edit.node_id!r} is not an editable file of this gate",
                edit.path,
            )
        size = len(edit.content.encode())
        if size > MAX_REVIEW_FILE_BYTES:
            raise EditError(
                "edit_too_large",
                f"{edit.path} is {size} bytes (at most {MAX_REVIEW_FILE_BYTES})",
                edit.path,
            )
        total += size
        if edit.content != change.after:
            kept.append(edit)
    if total > MAX_REVIEW_TOTAL_BYTES:
        raise EditError(
            "edit_too_large", f"the edits are {total} bytes (at most {MAX_REVIEW_TOTAL_BYTES})"
        )
    return kept


def gate_request(node: GateNode, input: str) -> dict[str, JsonValue]:
    """What the approver is shown: the `gate_waiting` payload, before the runner adds the
    `changes`. `artifact` is the gate's input, the previous node's output (data, never
    instructions)."""
    return {"title": node.title, "prompt": node.prompt, "artifact": input}


def decided_payload(decision: GateDecision, commits: dict[str, str]) -> dict[str, JsonValue]:
    """The `gate_decided` payload: the decision, plus its edits and the commits they made, if
    it has edits."""
    payload: dict[str, JsonValue] = decision.model_dump(mode="json", exclude={"edits"})
    if decision.edits:
        payload["edits"] = [e.model_dump(mode="json") for e in decision.edits]
        payload["commits"] = dict(commits)
    return payload


async def run_gate_node(
    node: GateNode, input: str, log: RunEventLog, review: GateReview | None = None
) -> AgentNodeResult:
    """Pause until the run is continued with a `GateDecision`, then log it. Approve completes the
    node and passes `input` on unchanged, once its edits are committed through `review`; edits
    that cannot be committed fail the node. Reject cancels it, which stops the run."""
    decision = GateDecision.model_validate(interrupt(gate_request(node, input)))
    commits: dict[str, str] = {}
    if decision.decision == "approve" and decision.edits:
        try:
            if review is None:
                raise GateReviewError("the run has no repository")
            commits = await review.apply(node.id, decision.edits)
        except GateReviewError as e:
            error = f"the gate's edits could not be applied: {e}"
            return AgentNodeResult(status="failed", text=input, usage=None, error=error)
    await log.emit(GATE_DECIDED, node_id=node.id, payload=decided_payload(decision, commits))
    if decision.decision == "approve":
        return AgentNodeResult(status="completed", text=input, usage=None)
    reason = f"rejected at gate: {decision.comment}" if decision.comment else "rejected at gate"
    return AgentNodeResult(status="cancelled", text=input, usage=None, error=reason)
