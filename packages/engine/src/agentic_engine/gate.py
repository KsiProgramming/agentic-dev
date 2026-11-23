"""Runs one `gate` node: the run pauses (a LangGraph interrupt) until a human decides.

LangGraph runs an interrupted node again from its start when the run continues, so the gate does
nothing before `interrupt()`: the runner announces the pause (`node_started`, `gate_waiting`) once
the graph has stopped, and the gate itself only reports the decision (`gate_decided`).

A gate after writer nodes shows the approver the files those writers changed (`FileChange`, from
a `GateReview` the worker gives the engine), and an approval may edit them (`FileEdit`). The gate
commits the edits to the writers' branches before it completes, so the nodes after it (e.g.
`github.openPR`) publish them.

A selection gate (6.7) shows the items of a JSON run artifact (`select`), and an approval names
the ones chosen (`selection`, by each item's key): the gate's output is the artifact with only
those items. A gate with `on_reject: end` ends the run as completed when it is rejected.
"""

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Literal, Protocol, Self, cast

from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from agentic_engine.agent import AgentNodeResult
from agentic_engine.artifacts import ArtifactRef, ArtifactStore
from agentic_engine.events import GATE_DECIDED, NODE_STARTED, RunEventLog
from agentic_engine.expr import ExpressionError, compile_item_condition
from agentic_engine.policy import APPROVAL_TTL_S
from agentic_engine.spec import ANSWER_TTL_S, MAX_SELECT_ITEMS, GateNode, GateSelect, WaitForNode
from agentic_runtime.findings import SEVERITIES, FindingsReport

if TYPE_CHECKING:
    from agentic_engine.review_gate import ReviewInput

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
type DismissalErrorCode = Literal["dismiss_not_allowed", "unknown_dismissal", "duplicate_dismissal"]
type SelectionErrorCode = Literal[
    "selection_required",
    "selection_not_allowed",
    "unknown_selection",
    "duplicate_selection",
    "selection_too_small",
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
    protected: bool = False
    """The file is protected (13.5): by the platform, the workflow, or because an earlier writer's
    approved work this writer started from. The gate shows it with its `rule`."""
    rule: str | None = None
    """Where the protection comes from: `default`, `workflow` or `frozen`."""


class FileEdit(BaseModel):
    """The approver's new text for an editable file of a writer's branch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str = Field(
        max_length=104, description="The writer: a node id, or a task's writer (`fix.t1`, 6.1)."
    )
    path: str = Field(min_length=1, max_length=1024)
    content: str


class GateComment(BaseModel):
    """One comment of a request for changes (7.8): on `item`, one of the things the gate showed
    (for the spec gate `spec`, `plan` or `prototype`), and what to change. Data for the agent
    that revises, never instructions to the platform."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    item: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=4000)


MAX_DISMISSED = 100
"""The most review comments one approval dismisses (a gate shows at most 100)."""

MAX_CHANGE_COMMENTS = 20
"""The most comments one request for changes carries."""


class GateDecision(BaseModel):
    """What a human decided at a gate; the value a paused run continues with. Only an approval
    has `edits`, only a selection gate's approval a `selection`, and only a request for changes
    (7.8) has `comments`, at least one."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: Literal["approve", "reject", "changes"]
    comment: str | None = None
    comments: list[GateComment] = Field(
        default_factory=list[GateComment], max_length=MAX_CHANGE_COMMENTS
    )
    decided_by: str | None = None
    edits: list[FileEdit] = Field(default_factory=list[FileEdit])
    selection: list[str] | None = Field(
        default=None,
        max_length=MAX_SELECT_ITEMS,
        description="A selection gate's approval: the keys of the items chosen (6.7).",
    )
    dismissed: list[str] | None = Field(
        default=None,
        max_length=MAX_DISMISSED,
        description="A review gate's approval (13.6): the fingerprints of the review comments "
        "the approver dismissed, which the pull request's notes leave out.",
    )

    @model_validator(mode="after")
    def _comments_with_changes(self) -> Self:
        if self.dismissed is not None and self.decision != "approve":
            raise ValueError("only an approval dismisses review comments")
        if self.decision == "changes" and not self.comments:
            raise ValueError("a request for changes needs at least one comment")
        if self.decision != "changes" and self.comments:
            raise ValueError("only a request for changes carries comments")
        return self


class EvidenceInput(BaseModel):
    """What a gate that checks a writer's work is given (13.3): the evidence `pack` (an
    `EvidencePack` as JSON) and, when a required check failed with a round left, the failures as
    the `comments` that send the work back without a person."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pack: dict[str, JsonValue]
    comments: list[GateComment] = Field(default_factory=list[GateComment])
    proceed: bool = Field(
        default=False,
        description="The gate passes by itself: its policy is `pause: on_failure` and every "
        "required check passed (13.4).",
    )


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

    async def commit(self, edits: Sequence[FileEdit], message: str) -> dict[str, str]:
        """Write `edits` to their writers' branches and commit them with `message`, one commit
        per writer, as `apply` does for a gate (7.5: `repo.commitArtifacts`). Files that already
        hold their text make no commit. Returns each writer's branch tip; raises
        `GateReviewError` if they cannot be committed."""
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
    decision: Literal["approve", "reject", "changes"],
    edits: Sequence[FileEdit],
) -> list[FileEdit]:
    """The edits of a decision at a gate that showed `changes`, without those that leave a file
    as it was. Raises `EditError` for edits with a reject, an edit of a file that was not shown
    as editable, the same file twice, or edits over the size caps."""
    if edits and decision != "approve":
        why = "a rejection" if decision == "reject" else "a request for changes"
        raise EditError("edits_with_reject", f"{why} cannot carry edits")
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


class SelectionError(ValueError):
    """An approval's selection does not fit what the gate showed (6.7)."""

    def __init__(self, code: SelectionErrorCode, message: str) -> None:
        super().__init__(message)
        self.code: SelectionErrorCode = code


class GateSelectError(Exception):
    """A selection gate cannot show its items: the artifact is missing, not a JSON object, or
    has no list of items under `select.items`."""


class SelectionShown(BaseModel):
    """What a selection gate showed (`gate_waiting`'s `select`): the artifact version, where the
    items are, how many there are, the keys that can be chosen (in item order), those checked
    when it opened, and the fewest an approval selects."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact: str
    version: int
    items: str
    key: str
    count: int
    keys: list[str]
    preselected: list[str]
    min: int


def selection_items(select: GateSelect, document: JsonValue) -> list[JsonValue]:
    """The items `select` shows from `document`. Raises `GateSelectError` when there are none to
    show: `document` is not an object, or `select.items` is not a list in it."""
    if not isinstance(document, dict):
        raise GateSelectError(f"{select.artifact} is not a JSON object")
    items = document.get(select.items)
    if not isinstance(items, list):
        raise GateSelectError(f"{select.artifact} has no list {select.items!r}")
    return items[:MAX_SELECT_ITEMS]


def item_key(item: JsonValue, key: str) -> str | None:
    """The key of `item`: a non-empty string or an integer under `key`, as text."""
    value = item.get(key) if isinstance(item, dict) else None
    if isinstance(value, bool) or not isinstance(value, str | int):
        return None
    return str(value) or None


def selection_shown(select: GateSelect, ref: ArtifactRef, document: JsonValue) -> SelectionShown:
    """What a selection gate on `document` (the artifact version `ref`) shows. An item with no
    key, or with a key an earlier item has, cannot be chosen; a `preselect` that fails on an item
    leaves it unchecked. Raises `GateSelectError` as `selection_items`."""
    items = selection_items(select, document)
    condition = compile_item_condition(select.preselect) if select.preselect else None
    keys: dict[str, None] = {}
    preselected: list[str] = []
    for item in items:
        key = item_key(item, select.key)
        if key is None or key in keys:
            continue
        keys[key] = None
        try:
            if condition is not None and condition.evaluate(item):
                preselected.append(key)
        except ExpressionError:
            pass
    return SelectionShown(
        artifact=ref.name,
        version=ref.version,
        items=select.items,
        key=select.key,
        count=len(items),
        keys=list(keys),
        preselected=preselected,
        min=select.min,
    )


def check_selection(
    shown: SelectionShown | None,
    decision: Literal["approve", "reject", "changes"],
    selection: Sequence[str] | None,
) -> list[str]:
    """The selection of a decision at a gate that showed `shown` (`None` for a gate that does not
    select). Raises `SelectionError` for a selection on a gate that does not select or with a
    reject, no selection on a selection gate's approval, a key it did not show, a key twice, or
    fewer keys than its `min`."""
    if shown is None or decision != "approve":
        if selection is not None:
            why = "a gate that does not select" if shown is None else f"a {decision} decision"
            raise SelectionError("selection_not_allowed", f"{why} cannot carry a selection")
        return []
    if selection is None:
        raise SelectionError("selection_required", "approving this gate needs a selection")
    known = set(shown.keys)
    seen: set[str] = set()
    for key in selection:
        if key in seen:
            raise SelectionError("duplicate_selection", f"{key!r} is selected twice")
        seen.add(key)
        if key not in known:
            raise SelectionError("unknown_selection", f"{key!r} is not an item this gate showed")
    if len(selection) < shown.min:
        plural = "s" if shown.min != 1 else ""
        raise SelectionError("selection_too_small", f"select at least {shown.min} item{plural}")
    return list(selection)


def selected_document(
    select: GateSelect, document: JsonValue, chosen: Sequence[str]
) -> dict[str, JsonValue]:
    """`document` with only the `chosen` items under `select.items`, in their order (each key
    once). A findings report gets its `counts` and `truncated` again, so it stays a valid
    report."""
    items = selection_items(select, document)
    wanted = set(chosen)
    kept: list[JsonValue] = []
    for item in items:
        key = item_key(item, select.key)
        if key is not None and key in wanted:
            kept.append(item)
            wanted.discard(key)
    out: dict[str, JsonValue] = {**cast(dict[str, JsonValue], document), select.items: kept}
    try:
        report = FindingsReport.model_validate(out)
    except ValueError:
        return out
    severities = Counter(f.severity for f in report.findings)
    out["counts"] = {s: severities.get(s, 0) for s in SEVERITIES}
    out["truncated"] = False
    return out


async def _selection(
    select: GateSelect, artifacts: ArtifactStore | None, refs: Mapping[str, ArtifactRef]
) -> tuple[SelectionShown, JsonValue]:
    """What a selection gate shows, from the version of its artifact the run has, and that
    version's document. Raises `GateSelectError` when it cannot be shown."""
    ref = refs.get(select.artifact)
    stored = await artifacts.get(ref.name, ref.version) if ref and artifacts else None
    if ref is None or stored is None:
        raise GateSelectError(f"artifact {select.artifact!r} was not written")
    try:
        document: JsonValue = json.loads(stored.content)
    except ValueError as e:
        raise GateSelectError(f"{select.artifact} is not JSON: {e}") from e
    return selection_shown(select, ref, document), document


class DismissalError(ValueError):
    """An approval's dismissals do not fit what the gate showed (13.6)."""

    def __init__(self, code: DismissalErrorCode, message: str) -> None:
        super().__init__(message)
        self.code: DismissalErrorCode = code


def check_dismissals(
    shown: Sequence[str] | None,
    decision: Literal["approve", "reject", "changes"],
    dismissed: Sequence[str] | None,
) -> list[str]:
    """The dismissals of a decision at a gate whose review comments have the fingerprints `shown`
    (`None` for a gate with no review). Raises `DismissalError` for dismissals on a gate with no
    review or with a decision other than approve, a fingerprint the gate did not show, or one
    twice."""
    if not dismissed:
        return []
    if shown is None or decision != "approve":
        why = "a gate with no review" if shown is None else f"a {decision} decision"
        raise DismissalError("dismiss_not_allowed", f"{why} cannot dismiss comments")
    known = set(shown)
    seen: set[str] = set()
    for fingerprint in dismissed:
        if fingerprint in seen:
            raise DismissalError("duplicate_dismissal", f"{fingerprint!r} is dismissed twice")
        seen.add(fingerprint)
        if fingerprint not in known:
            raise DismissalError(
                "unknown_dismissal", f"{fingerprint!r} is not a comment this gate showed"
            )
    return list(dismissed)


def gate_request(
    node: GateNode,
    input: str,
    ttl_s: int,
    shown: SelectionShown | None = None,
    evidence: EvidenceInput | None = None,
    review: "ReviewInput | None" = None,
) -> dict[str, JsonValue]:
    """What the approver is shown: the `gate_waiting` payload, before the runner adds the
    `changes` and `expires_at`. `artifact` is the gate's input, the previous node's output (data,
    never instructions). `ttl_s` is how long the gate waits: its own time to live, else the run
    policy's `ttl_s`. A selection gate adds what it shows (`select`), and a gate that ends the
    run on a rejection says so (`on_reject`)."""
    request: dict[str, JsonValue] = {
        "title": node.title,
        "prompt": node.prompt,
        "artifact": input,
        "ttl_s": node.ttl_s if node.ttl_s is not None else ttl_s,
    }
    if shown is not None:
        request["select"] = shown.model_dump(mode="json")
    if evidence is not None:
        request["evidence"] = evidence.pack
    if review is not None:
        request["review"] = review.shown.model_dump(mode="json", by_alias=True)
    if node.on_reject == "end":
        request["on_reject"] = "end"
    if node.on_changes is not None:
        request["on_changes"] = node.on_changes
    return request


def changes_text(comments: Sequence[GateComment]) -> str:
    """A request for changes as the text the loop's next pass receives: one `## <item>` section
    per item commented on, each comment a bullet. It is the approver's words, data for the agent
    that revises (principle 5)."""
    items: dict[str, list[str]] = {}
    for comment in comments:
        items.setdefault(comment.item, []).append(comment.text)
    return "\n\n".join(
        f"## {item}\n\n" + "\n".join(f"- {text}" for text in texts) for item, texts in items.items()
    )


def decided_payload(decision: GateDecision, commits: dict[str, str]) -> dict[str, JsonValue]:
    """The `gate_decided` payload: the decision, plus its selection if it has one, and its edits
    and the commits they made if it has edits."""
    payload: dict[str, JsonValue] = decision.model_dump(
        mode="json", exclude={"edits", "selection", "comments", "dismissed"}
    )
    if decision.comments:
        payload["comments"] = [c.model_dump(mode="json") for c in decision.comments]
    if decision.selection is not None:
        payload["selection"] = list[JsonValue](decision.selection)
    if decision.dismissed:
        payload["dismissed"] = list[JsonValue](decision.dismissed)
    if decision.edits:
        payload["edits"] = [e.model_dump(mode="json") for e in decision.edits]
        payload["commits"] = dict(commits)
    return payload


async def run_gate_node(
    node: GateNode,
    input: str,
    log: RunEventLog,
    review: GateReview | None = None,
    ttl_s: int = APPROVAL_TTL_S,
    artifacts: ArtifactStore | None = None,
    refs: Mapping[str, ArtifactRef] | None = None,
    evidence: EvidenceInput | None = None,
    reviewing: "ReviewInput | None" = None,
) -> AgentNodeResult:
    """Pause until the run is continued with a `GateDecision`, then log it. Approve completes the
    node and passes `input` on unchanged, once its edits are committed through `review`; edits
    that cannot be committed fail the node. Reject cancels it, which stops the run; with
    `on_reject: end` it completes with `ends_run`, which ends the run as completed. A request
    for changes (7.8, a gate with `on_changes`) completes it with the comments as its text and
    `data` `{decision: "changes", comments}`, for the loop around it to go round again. The gate
    waits `ttl_s` (the run's `approval_ttl_s`) unless it sets its own; the worker cancels the run
    once that has passed (`agentic_store.expiry`).

    A selection gate (6.7) shows the items of its artifact (the version in `refs`, read from
    `artifacts`), and its approval's output is that artifact with only the chosen items (`data`,
    and pretty JSON as its text). One that cannot show its items, or gets a selection that does
    not fit them, fails.

    A gate with `evidence` (13.3) is given the checks' pack. When a required check failed and a
    round is left (`evidence.comments`), it does not pause: it completes at once as a request for
    changes with `source` `checks`, the failures as its comments, for the loop to hand the writer.
    Otherwise it pauses and shows the pack.

    A gate with `review` (13.6) is given the review's findings the same way: blocking ones with a
    round left complete it as a request for changes with `source` `review` (both sections, and
    `source` `checks`, when the checks failed too); otherwise it pauses and shows every finding as
    a comment, and an approval may dismiss some (`dismissed`)."""
    sent = [*(evidence.comments if evidence else []), *(reviewing.send if reviewing else [])]
    if sent:
        source = "checks" if evidence is not None and evidence.comments else "review"
        reviewed = bool(reviewing and reviewing.send)
        return await _sent_back(node, sent, log, source, reviewed=reviewed)
    if evidence is not None and evidence.proceed and reviewing is None:
        return await _passed(node, input, log)
    shown: SelectionShown | None = None
    document: JsonValue = None
    if node.select is not None:
        try:
            shown, document = await _selection(node.select, artifacts, refs or {})
        except GateSelectError as e:
            # It fails before it pauses, so the runner never announced its start.
            await log.emit(NODE_STARTED, node_id=node.id)
            return AgentNodeResult(status="failed", text=input, usage=None, error=str(e))
    request = gate_request(node, input, ttl_s, shown, evidence, reviewing)
    decision = GateDecision.model_validate(interrupt(request))
    try:
        dismissed = check_dismissals(
            [c.fingerprint for c in reviewing.shown.comments] if reviewing else None,
            decision.decision,
            decision.dismissed,
        )
    except DismissalError as e:
        error = f"the gate's dismissals do not fit what it showed: {e}"
        return AgentNodeResult(status="failed", text=input, usage=None, error=error)
    try:
        chosen = check_selection(shown, decision.decision, decision.selection)
    except SelectionError as e:
        error = f"the gate's selection does not fit what it showed: {e}"
        return AgentNodeResult(status="failed", text=input, usage=None, error=error)
    commits: dict[str, str] = {}
    if decision.decision == "approve" and decision.edits:
        try:
            if review is None:
                raise GateReviewError("the run has no repository")
            commits = await review.apply(node.id, decision.edits)
        except GateReviewError as e:
            error = f"the gate's edits could not be applied: {e}"
            return AgentNodeResult(status="failed", text=input, usage=None, error=error)
    if decision.decision == "changes" and node.on_changes is None:
        error = f"gate {node.id!r} does not take requests for changes"
        return AgentNodeResult(status="failed", text=input, usage=None, error=error)
    await log.emit(GATE_DECIDED, node_id=node.id, payload=decided_payload(decision, commits))
    if decision.decision == "changes":
        data: dict[str, JsonValue] = {
            "decision": "changes",
            "comments": [c.model_dump(mode="json") for c in decision.comments],
        }
        return AgentNodeResult(
            status="completed", text=changes_text(decision.comments), usage=None, data=data
        )
    if decision.decision == "approve":
        if node.select is None:
            # A gate that can send the work back says which way it went (`until` reads it).
            went: dict[str, JsonValue] | None = (
                {"decision": "approve"}
                if node.on_changes is not None
                or node.evidence is not None
                or node.review is not None
                else None
            )
            if went is not None and dismissed:
                went["dismissed"] = list[JsonValue](dismissed)
            if commits:
                # What the writes after the gate are checked against (13.8): the edit's commit.
                went = {
                    **(went or {"decision": "approve"}),
                    "commits": dict[str, JsonValue](commits),
                }
            return AgentNodeResult(status="completed", text=input, usage=None, data=went)
        data = selected_document(node.select, document, chosen)
        text = json.dumps(data, indent=2, ensure_ascii=False)
        return AgentNodeResult(status="completed", text=text, usage=None, data=data)
    if node.on_reject == "end":
        return AgentNodeResult(status="completed", text=input, usage=None, ends_run=True)
    reason = f"rejected at gate: {decision.comment}" if decision.comment else "rejected at gate"
    return AgentNodeResult(status="cancelled", text=input, usage=None, error=reason)


async def _sent_back(
    node: GateNode,
    comments: Sequence[GateComment],
    log: RunEventLog,
    source: Literal["checks", "review"] = "checks",
    reviewed: bool = False,
) -> AgentNodeResult:
    """The gate's checks or review sent the work back (13.3, 13.6): the same completion as a
    person's request for changes (7.8), with no one named as having decided it and no pause.
    `reviewed` says the review's findings are among the comments."""
    items: list[JsonValue] = [c.model_dump(mode="json") for c in comments]
    # The gate never paused, so the runner did not announce its start.
    await log.emit(NODE_STARTED, node_id=node.id)
    payload: dict[str, JsonValue] = {"decision": "changes", "source": source, "comments": items}
    if reviewed:
        payload["review"] = True
    await log.emit(GATE_DECIDED, node_id=node.id, payload=payload)
    data: dict[str, JsonValue] = dict(payload)
    return AgentNodeResult(status="completed", text=changes_text(comments), usage=None, data=data)


async def _passed(node: GateNode, input: str, log: RunEventLog) -> AgentNodeResult:
    """The gate's checks passed and its policy does not pause on a pass (13.4): it approves by
    itself, with no one named. `source` is not `checks`, which means a send-back."""
    # The gate never paused, so the runner did not announce its start.
    await log.emit(NODE_STARTED, node_id=node.id)
    await log.emit(
        GATE_DECIDED, node_id=node.id, payload={"decision": "approve", "source": "checks_passed"}
    )
    data: dict[str, JsonValue] = {"decision": "approve", "source": "checks_passed"}
    return AgentNodeResult(status="completed", text=input, usage=None, data=data)


async def run_wait_node(
    node: WaitForNode,
    input: str,
    log: RunEventLog,
    issue_key: str | None,
    issue_url: str,
    after_comment_id: str | None,
) -> AgentNodeResult:
    """Hold the run until the platform continues it (7.9). Like a gate it does nothing before
    `interrupt()`; the runner announces the wait (`gate_waiting`, with `wait_for`). Continued
    with an approval (`answer_arrived`) it completes with a note saying where the answers are,
    which is the next step's input; a rejection cancels it. A wait with no issue, or whose
    question comment is unknown, fails before it pauses: it could never be answered."""
    if not issue_key or not after_comment_id:
        why = (
            "the run has no Jira issue"
            if not issue_key
            else f"{node.after_from!r} posted no comment"
        )
        return AgentNodeResult(
            status="failed", text=input, usage=None, error=f"cannot wait for an answer: {why}"
        )
    request: dict[str, JsonValue] = {
        "title": node.title,
        "prompt": node.prompt,
        "artifact": input,
        "ttl_s": node.ttl_s if node.ttl_s is not None else ANSWER_TTL_S,
        "wait_for": {
            "kind": node.wait_for,
            "issue": {"key": issue_key, "url": issue_url},
            "after_comment_id": after_comment_id,
        },
    }
    decision = GateDecision.model_validate(interrupt(request))
    # The console and the run's summary read the end of a wait from this event, as a gate's.
    await log.emit(GATE_DECIDED, node_id=node.id, payload=decided_payload(decision, {}))
    if decision.decision == "approve":
        note = (
            f"The team answered the questions asked on {issue_key}: their answers are the "
            f"issue's comments after comment {after_comment_id}."
        )
        return AgentNodeResult(status="completed", text=note, usage=None, data={"answered": True})
    return AgentNodeResult(status="cancelled", text=input, usage=None, error="wait cancelled")
