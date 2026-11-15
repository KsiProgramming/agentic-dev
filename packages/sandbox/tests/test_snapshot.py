"""A writer's uncommitted work, recorded on `wip/<run>/<key>` when its run fails (12.3)."""

import os
import shutil
import stat
import tempfile
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from uuid import uuid4

import pytest

from agentic_sandbox import (
    FakeSandboxManager,
    RepoSource,
    Sandbox,
    add_worktree,
    branch_name,
    export_branch,
    snapshot_worktrees,
    wip_branch,
)
from agentic_sandbox.review import branch_changes, commit_files
from agentic_sandbox.testing import make_repo


@pytest.fixture
def base() -> Iterator[Path]:
    """A short path: git on Windows cannot name a range from deep in `tmp_path`."""
    path = Path(tempfile.mkdtemp(prefix="ag-"))
    yield path
    shutil.rmtree(path, onexc=_writable_then_retry)


def _writable_then_retry(func: Callable[[str], object], path: str, _: BaseException) -> None:
    os.chmod(path, stat.S_IWRITE)
    func(path)


@pytest.fixture
async def box(base: Path) -> AsyncIterator[Sandbox]:
    make_repo(base / "repos" / "hello")
    (base / "boxes").mkdir()
    manager = FakeSandboxManager(local_root=base / "repos", base_dir=base / "boxes")
    async with manager.open(uuid4(), RepoSource(url=str(base / "repos" / "hello"))) as sandbox:
        yield sandbox


async def git(box: Sandbox, cwd: str, *argv: str) -> str:
    result = await box.exec(["git", "-c", f"safe.directory={box.workdir}", *argv], cwd=cwd)
    assert result.exit_code == 0, result.stderr
    return result.stdout


async def test_uncommitted_work_is_recorded_without_touching_the_worktree(box: Sandbox) -> None:
    run_id = uuid4()
    tree = await add_worktree(box, run_id, "writer")
    await commit_files(tree, [("NOTES.md", b"notes\n")], "Add notes")
    (Path(tree.path) / "NOTES.md").write_text("notes, edited\n", encoding="utf-8")
    (Path(tree.path) / "DRAFT.md").write_text("draft\n", encoding="utf-8")
    tip = await git(box, tree.path, "rev-parse", "HEAD")
    status = await git(box, tree.path, "status", "--porcelain", "--untracked-files=all")

    [snapshot] = await snapshot_worktrees(box, run_id)

    assert (snapshot.key, snapshot.branch) == ("writer", wip_branch(run_id, "writer"))
    # The worktree, its index and its branch are as they were.
    assert await git(box, tree.path, "rev-parse", "HEAD") == tip
    assert await git(box, tree.path, "status", "--porcelain", "--untracked-files=all") == status
    # The snapshot sits on the branch's tip and holds both files.
    parent = await git(box, box.workdir, "rev-parse", f"{snapshot.commit}^")
    assert parent == tip
    changes = await branch_changes(box, snapshot.branch)
    assert sorted((f.path, f.status) for f in changes.files) == [
        ("DRAFT.md", "added"),
        ("NOTES.md", "added"),
    ]
    bundle = await export_branch(box, snapshot.branch)
    assert (bundle.head_sha, bundle.commits) == (snapshot.commit, 2)


async def test_a_clean_worktree_and_other_runs_are_left_out(box: Sandbox) -> None:
    run_id, other = uuid4(), uuid4()
    clean = await add_worktree(box, run_id, "clean")
    await commit_files(clean, [("A.md", b"a\n")], "Add a")
    elsewhere = await add_worktree(box, other, "writer")
    (Path(elsewhere.path) / "B.md").write_text("b\n", encoding="utf-8")

    assert await snapshot_worktrees(box, run_id) == []
    branches = await git(box, box.workdir, "branch", "--list", "wip/*")
    assert branches == ""
    assert branch_name(run_id, "clean") in await git(box, box.workdir, "branch", "--list")
