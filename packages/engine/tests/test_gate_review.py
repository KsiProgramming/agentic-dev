"""A gate shows the files its writers changed and commits an approval's edits (phase 3.6)."""

from collections.abc import Sequence

import pytest

from agentic_engine.gate import (
    MAX_REVIEW_FILE_BYTES,
    MAX_REVIEW_TOTAL_BYTES,
    EditError,
    FileChange,
    FileEdit,
    GateDecision,
    GateReviewError,
    check_edits,
)
from agentic_engine.graph import WorkflowRunResult, resume_workflow, run_workflow

from .test_gate import Run, gated, lifecycle

PAGE = FileChange(
    node_id="writer",
    path="docs/a.md",
    status="added",
    editable=True,
    after="# A\n",
)
LOGO = FileChange(
    node_id="writer", path="logo.png", status="added", editable=False, reason="binary"
)
EDIT = FileEdit(node_id="writer", path="docs/a.md", content="# A, edited\n")


class FakeReview:
    """A writer branch kept as a dict: `apply` commits only what changes a file."""

    def __init__(self, changes: Sequence[FileChange] = (PAGE, LOGO)) -> None:
        self.shown = list(changes)
        self.files = {c.path: c.after for c in changes}
        self.ran: list[list[str]] = []
        self.applied: list[tuple[str, list[FileEdit]]] = []
        self.commits = 0
        self.fail: Exception | None = None
        self.crash_after_apply = False

    async def changes(self, ran: Sequence[str]) -> list[FileChange]:
        self.ran.append(list(ran))
        if self.fail is not None:
            raise self.fail
        return self.shown

    async def apply(self, gate_id: str, edits: Sequence[FileEdit]) -> dict[str, str]:
        self.applied.append((gate_id, list(edits)))
        if self.fail is not None:
            raise self.fail
        changed = [e for e in edits if self.files.get(e.path) != e.content]
        for edit in changed:
            self.files[edit.path] = edit.content
        if changed:
            self.commits += 1
        if self.crash_after_apply:
            self.crash_after_apply = False
            raise RuntimeError("worker died")
        return {"writer": f"sha{self.commits}"}


class ReviewedRun(Run):
    def __init__(self, review: FakeReview) -> None:
        super().__init__(gated("gate"))
        self.review = review

    async def start(self) -> WorkflowRunResult:
        return await run_workflow(
            self.spec,
            self.runtime,
            "go",
            run_id=self.run_id,
            sink=self.sink,
            checkpointer=self.checkpointer,
            review=self.review,
        )

    async def resume(self, decision: GateDecision | None) -> WorkflowRunResult:
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
            decision=decision,
            review=self.review,
        )


def approve(*edits: FileEdit) -> GateDecision:
    return GateDecision(decision="approve", edits=list(edits))


async def test_the_pause_shows_what_the_writers_changed() -> None:
    review = FakeReview()
    run = ReviewedRun(review)

    await run.start()

    assert review.ran == [["writer"]]
    waiting = run.sink.events[-1]
    assert waiting.type == "gate_waiting"
    assert waiting.payload is not None
    assert waiting.payload["changes"] == [
        PAGE.model_dump(mode="json"),
        LOGO.model_dump(mode="json"),
    ]
    assert "changes_error" not in waiting.payload


async def test_changes_that_cannot_be_read_still_pause_the_run() -> None:
    review = FakeReview()
    review.fail = GateReviewError("git failed")
    run = ReviewedRun(review)

    assert (await run.start()).waiting_at == "gate"

    payload = run.sink.events[-1].payload
    assert payload is not None
    assert (payload["changes"], payload["changes_error"]) == ([], "git failed")


async def test_approve_with_edits_commits_them_before_the_run_goes_on() -> None:
    """Done when (3.6), engine side: the approval's edits land on the writer's branch."""
    review = FakeReview()
    run = ReviewedRun(review)
    await run.start()

    result = await run.resume(approve(EDIT))

    assert result.status == "completed"
    assert review.applied == [("gate", [EDIT])]
    assert review.files["docs/a.md"] == "# A, edited\n"
    decided = next(e for e in run.sink.events if e.type == "gate_decided")
    assert decided.payload == {
        "decision": "approve",
        "comment": None,
        "decided_by": None,
        "edits": [EDIT.model_dump(mode="json")],
        "commits": {"writer": "sha1"},
    }
    after = run.runtime.requests[-1]
    assert (after.node_id, after.input) == ("after-gate", "draft notes")


async def test_approve_without_edits_applies_nothing() -> None:
    review = FakeReview()
    run = ReviewedRun(review)
    await run.start()

    assert (await run.resume(approve())).status == "completed"

    assert review.applied == []
    decided = next(e for e in run.sink.events if e.type == "gate_decided")
    assert decided.payload == {"decision": "approve", "comment": None, "decided_by": None}


async def test_reject_applies_nothing() -> None:
    review = FakeReview()
    run = ReviewedRun(review)
    await run.start()

    assert (await run.resume(GateDecision(decision="reject"))).status == "cancelled"

    assert review.applied == []


async def test_edits_that_cannot_be_applied_fail_the_run() -> None:
    review = FakeReview()
    run = ReviewedRun(review)
    await run.start()
    paused_at = len(run.sink.events)
    review.fail = GateReviewError("the worktree is gone")

    result = await run.resume(approve(EDIT))

    assert (result.status, result.stopped_at) == ("failed", "gate")
    assert result.results["gate"].error == (
        "the gate's edits could not be applied: the worktree is gone"
    )
    assert lifecycle(run.sink.events[paused_at:]) == [
        ("run_resumed", None),
        ("node_failed", "gate"),
        ("run_failed", None),
    ]


async def test_edits_without_a_review_fail_the_run() -> None:
    run = Run(gated("gate"))
    await run.start()

    result = await run.resume(approve(EDIT))

    assert result.status == "failed"
    assert result.results["gate"].error == (
        "the gate's edits could not be applied: the run has no repository"
    )


async def test_a_crash_after_the_commit_applies_again_without_a_second_commit() -> None:
    """A worker that dies after committing the edits, before the gate's checkpoint, leaves the
    gate to run again: it applies the same edits, which commits nothing new."""
    review = FakeReview()
    run = ReviewedRun(review)
    await run.start()
    review.crash_after_apply = True

    with pytest.raises(RuntimeError, match="worker died"):
        await run.resume(approve(EDIT))
    result = await run.resume(approve(EDIT))

    assert result.status == "completed"
    assert len(review.applied) == 2
    assert review.commits == 1
    decided = [e for e in run.sink.events if e.type == "gate_decided"]
    assert len(decided) == 1


class TestCheckEdits:
    def test_keeps_edits_of_editable_files(self) -> None:
        assert check_edits([PAGE, LOGO], "approve", [EDIT]) == [EDIT]

    def test_drops_an_edit_that_leaves_the_file_as_it_was(self) -> None:
        same = FileEdit(node_id="writer", path="docs/a.md", content="# A\n")
        assert check_edits([PAGE], "approve", [same]) == []

    def test_refuses_edits_with_a_reject(self) -> None:
        with pytest.raises(EditError) as e:
            check_edits([PAGE], "reject", [EDIT])
        assert e.value.code == "edits_with_reject"

    @pytest.mark.parametrize(
        "edit",
        [
            FileEdit(node_id="writer", path="logo.png", content="x"),
            FileEdit(node_id="writer", path="docs/b.md", content="x"),
            FileEdit(node_id="other", path="docs/a.md", content="x"),
        ],
        ids=["not-editable", "not-shown", "other-writer"],
    )
    def test_refuses_a_file_that_was_not_shown_as_editable(self, edit: FileEdit) -> None:
        with pytest.raises(EditError) as e:
            check_edits([PAGE, LOGO], "approve", [edit])
        assert (e.value.code, e.value.path) == ("edit_not_allowed", edit.path)

    def test_refuses_the_same_file_twice(self) -> None:
        with pytest.raises(EditError) as e:
            check_edits([PAGE], "approve", [EDIT, EDIT])
        assert e.value.code == "duplicate_edit"

    def test_refuses_a_file_over_the_cap(self) -> None:
        big = EDIT.model_copy(update={"content": "x" * (MAX_REVIEW_FILE_BYTES + 1)})
        with pytest.raises(EditError) as e:
            check_edits([PAGE], "approve", [big])
        assert (e.value.code, e.value.path) == ("edit_too_large", "docs/a.md")

    def test_refuses_edits_over_the_total_cap(self) -> None:
        pages = [PAGE.model_copy(update={"path": f"docs/{i}.md"}) for i in range(3)]
        size = MAX_REVIEW_TOTAL_BYTES // 3 + 1
        edits = [FileEdit(node_id="writer", path=p.path, content="x" * size) for p in pages]
        with pytest.raises(EditError) as e:
            check_edits(pages, "approve", edits)
        assert (e.value.code, e.value.path) == ("edit_too_large", None)
