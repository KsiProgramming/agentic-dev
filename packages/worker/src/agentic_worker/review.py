"""The `GateReview` of a run with a repo: its writers' branches in its sandbox, as a gate shows
them, and the approver's edits committed onto them."""

from collections.abc import Collection, Sequence
from uuid import UUID

from agentic_engine.gate import (
    MAX_REVIEW_FILE_BYTES,
    MAX_REVIEW_FILES,
    MAX_REVIEW_TOTAL_BYTES,
    FileChange,
    FileEdit,
    GateReviewError,
    NotEditable,
)
from agentic_engine.spec import task_writer_orchestrator
from agentic_sandbox import Sandbox, SandboxError, Worktree, branch_name
from agentic_sandbox.review import (
    BranchNotFoundError,
    ChangedFile,
    branch_changes,
    commit_files,
    read_blobs,
)

EDITED_BY = "Edited-by: reviewer"
"""The trailer of a gate's edit commit. Who edited is not known until users exist."""


class SandboxGateReview:
    """Implements `GateReview` over `sandbox` for the writer nodes `writers` of run `run_id`, and
    the tasks' writers (`<orchestrator>.<task>`, 6.1) of the orchestrators in `task_writers`."""

    def __init__(
        self,
        sandbox: Sandbox,
        run_id: UUID,
        writers: Collection[str],
        task_writers: Collection[str] = (),
    ) -> None:
        self._sandbox = sandbox
        self._run_id = run_id
        self._writers = writers
        self._task_writers = frozenset(task_writers)

    def _is_writer(self, node_id: str) -> bool:
        """Whether `node_id` names a writer of the run: a writer node, or a task's writer."""
        if node_id in self._writers:
            return True
        orchestrator = task_writer_orchestrator(node_id)
        return orchestrator is not None and orchestrator in self._task_writers

    async def changes(self, ran: Sequence[str]) -> list[FileChange]:
        """The files changed on the branch of each writer among `ran`, in run order. The first
        files that fit `MAX_REVIEW_FILES` and `MAX_REVIEW_TOTAL_BYTES` and are UTF-8 text of at
        most `MAX_REVIEW_FILE_BYTES` come with their contents and are editable; the others are
        listed with the reason they are not."""
        shown: list[FileChange] = []
        files, total = 0, 0
        for node_id in (n for n in ran if self._is_writer(n)):
            try:
                branch = await branch_changes(self._sandbox, branch_name(self._run_id, node_id))
            except BranchNotFoundError:
                continue  # it never wrote
            except SandboxError as e:
                raise GateReviewError(f"cannot read the branch of {node_id}: {e}") from e
            reasons: list[NotEditable | None] = []
            for f in branch.files:
                size = (f.before_size or 0) + (f.after_size or 0)
                reason: NotEditable | None = None
                if f.status == "deleted" or f.status == "renamed":
                    reason = f.status
                elif max(f.before_size or 0, f.after_size or 0) > MAX_REVIEW_FILE_BYTES:
                    reason = "too_large"
                elif files >= MAX_REVIEW_FILES or total + size > MAX_REVIEW_TOTAL_BYTES:
                    reason = "over_limit"
                else:
                    files, total = files + 1, total + size
                reasons.append(reason)
            readable = [f for f, r in zip(branch.files, reasons, strict=True) if r is None]
            contents = await self._read(node_id, branch.base_sha, branch.branch, readable)
            for f, reason in zip(branch.files, reasons, strict=True):
                before, after = contents.get(f.path, (None, None))
                text = after is not None and (f.status == "added" or before is not None)
                if reason is None and not text:
                    reason = "binary"
                shown.append(
                    FileChange(
                        node_id=node_id,
                        path=f.path,
                        old_path=f.old_path,
                        status=f.status,
                        editable=reason is None,
                        reason=reason,
                        before=before if reason is None else None,
                        after=after if reason is None else None,
                    )
                )
        return shown

    async def _read(
        self, node_id: str, base: str, branch: str, files: list[ChangedFile]
    ) -> dict[str, tuple[str | None, str | None]]:
        """The text of each file in `files` at `base` (modified files only) and at the tip of
        `branch`; `None` for a side that is not UTF-8 text."""
        specs = [f"refs/heads/{branch}:{f.path}" for f in files]
        modified = [f for f in files if f.status == "modified"]
        specs += [f"{base}:{f.path}" for f in modified]
        try:
            blobs = [_text(b) for b in await read_blobs(self._sandbox, specs)]
        except (SandboxError, ValueError) as e:
            raise GateReviewError(f"cannot read the files of {node_id}: {e}") from e
        after = {f.path: blobs[i] for i, f in enumerate(files)}
        before = {f.path: blobs[len(files) + i] for i, f in enumerate(modified)}
        return {f.path: (before.get(f.path), after[f.path]) for f in files}

    async def apply(self, gate_id: str, edits: Sequence[FileEdit]) -> dict[str, str]:
        """Commit `edits` in their writers' worktrees: one commit `Edit at gate <gate_id>` per
        writer, or none for a writer whose files already hold them."""
        by_writer: dict[str, list[tuple[str, bytes]]] = {}
        for edit in edits:
            if not self._is_writer(edit.node_id):
                raise GateReviewError(f"node {edit.node_id!r} is not a writer of this run")
            by_writer.setdefault(edit.node_id, []).append((edit.path, edit.content.encode()))
        message = f"Edit at gate {gate_id}\n\n{EDITED_BY}"
        commits: dict[str, str] = {}
        for node_id, files in by_writer.items():
            tree = Worktree.of(self._sandbox, self._run_id, node_id)
            try:
                commits[node_id] = await commit_files(tree, files, message)
            except SandboxError as e:
                raise GateReviewError(str(e)) from e
        return commits


def _text(data: bytes | None) -> str | None:
    """`data` as text, or `None` if it is missing or not UTF-8 text (it holds a NUL byte, as git
    checks, or is not valid UTF-8)."""
    if data is None or b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None
