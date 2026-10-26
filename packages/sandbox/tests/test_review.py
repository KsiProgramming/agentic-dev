"""A writer's branch as a gate shows it, and edits committed onto it, on both backends."""

from uuid import UUID

import pytest

from agentic_sandbox import Sandbox, SandboxError, Worktree, add_worktree
from agentic_sandbox.review import (
    BranchNotFoundError,
    ChangedFile,
    branch_changes,
    commit_files,
    read_blobs,
)

RUN_ID = UUID("00000000-0000-4000-8000-000000000001")
_COMMIT = "git add -A && git -c user.name=t -c user.email=t@e.invalid -c commit.gpgsign=false"


async def sh(box: Sandbox, script: str) -> str:
    result = await box.exec(["sh", "-c", script])
    assert result.exit_code == 0, result.stderr
    return result.stdout.strip()


async def writer(sandbox: Sandbox) -> Worktree:
    """A writer that added, modified, deleted, renamed and wrote a binary file."""
    tree = await add_worktree(sandbox, RUN_ID, "writer")
    await sh(
        tree,
        "mkdir -p out && printf '# New\\n' > out/new.md && printf '# Hello, edited\\n' > README.md"
        " && rm docs/guide.md && git mv src/app.py src/main.py"
        " && printf 'a\\0b' > out/blob.bin"
        f" && {_COMMIT} commit -q -m work",
    )
    return tree


async def test_branch_changes_lists_every_kind_of_change(sandbox: Sandbox) -> None:
    tree = await writer(sandbox)

    changes = await branch_changes(sandbox, tree.branch)

    assert changes.branch == tree.branch
    # The clone is root's in the Docker sandbox: git needs it marked safe.
    head = 'git -c safe.directory="$(pwd -P)" rev-parse HEAD'
    assert changes.base_sha == await sh(sandbox, head)
    assert sorted(changes.files, key=lambda f: f.path) == [
        ChangedFile(path="README.md", status="modified", before_size=13, after_size=16),
        ChangedFile(path="docs/guide.md", status="deleted", before_size=9),
        ChangedFile(path="out/blob.bin", status="added", after_size=3),
        ChangedFile(path="out/new.md", status="added", after_size=6),
        ChangedFile(
            path="src/main.py",
            status="renamed",
            old_path="src/app.py",
            before_size=15,
            after_size=15,
        ),
    ]


async def test_a_branch_without_commits_has_no_changes(sandbox: Sandbox) -> None:
    tree = await add_worktree(sandbox, RUN_ID, "writer")

    assert (await branch_changes(sandbox, tree.branch)).files == []


async def test_a_missing_branch_is_refused(sandbox: Sandbox) -> None:
    with pytest.raises(BranchNotFoundError):
        await branch_changes(sandbox, "agent/x/nobody")


async def test_read_blobs_reads_both_sides_as_bytes(sandbox: Sandbox) -> None:
    tree = await writer(sandbox)
    changes = await branch_changes(sandbox, tree.branch)
    head = f"refs/heads/{tree.branch}"

    blobs = await read_blobs(
        sandbox,
        [
            f"{changes.base_sha}:README.md",
            f"{head}:README.md",
            f"{head}:out/blob.bin",
            f"{head}:docs/guide.md",
            f"{head}:out",
        ],
    )

    assert blobs == [b"# Hello repo\n", b"# Hello, edited\n", b"a\0b", None, None]


async def test_commit_files_commits_only_the_edited_files(sandbox: Sandbox) -> None:
    tree = await writer(sandbox)
    # Left over by the agent, uncommitted: not part of the edit.
    await sh(tree, "printf 'scratch' > scratch.txt")

    tip = await commit_files(
        tree, [("out/new.md", b"# New, by a reviewer\n")], "Edit at gate approve"
    )

    assert tip == await sh(tree, "git rev-parse HEAD")
    assert await sh(tree, "git log -1 --format=%s%n%an") == (
        "Edit at gate approve\nagentic-dev agent"
    )
    assert await sh(tree, "git show --name-only --format= HEAD") == "out/new.md"
    assert await sh(tree, "git show HEAD:out/new.md") == "# New, by a reviewer"
    assert await sh(tree, "git status --porcelain") == "?? scratch.txt"


async def test_committing_the_same_files_again_makes_no_commit(sandbox: Sandbox) -> None:
    tree = await writer(sandbox)
    edit = [("out/new.md", b"# New, by a reviewer\n")]
    first = await commit_files(tree, edit, "Edit at gate approve")

    again = await commit_files(tree, edit, "Edit at gate approve")

    assert again == first
    assert await sh(tree, "git rev-list --count HEAD") == "3"


@pytest.mark.parametrize("path", ["../escape.md", ".git/config/x"])
async def test_a_path_out_of_the_worktree_is_refused(sandbox: Sandbox, path: str) -> None:
    tree = await writer(sandbox)

    with pytest.raises(SandboxError):
        await commit_files(tree, [(path, b"x")], "Edit at gate approve")
