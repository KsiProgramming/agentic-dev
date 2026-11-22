"""A writer's branch read from git refs (13.1), on both backends."""

from uuid import UUID

import pytest

from agentic_sandbox import Sandbox, Worktree, add_worktree
from agentic_sandbox.refs import (
    DiffFile,
    RefPathError,
    branch_diff,
    branch_has_commits,
    grep_tree,
    list_tree,
    show_file,
)
from agentic_sandbox.review import BranchNotFoundError

RUN_ID = UUID("00000000-0000-4000-8000-000000000001")
_COMMIT = "git add -A && git -c user.name=t -c user.email=t@e.invalid -c commit.gpgsign=false"


async def sh(box: Sandbox, script: str) -> str:
    result = await box.exec(["sh", "-c", script])
    assert result.exit_code == 0, result.stderr
    return result.stdout.strip()


async def writer(sandbox: Sandbox) -> Worktree:
    tree = await add_worktree(sandbox, RUN_ID, "writer")
    await sh(
        tree,
        "mkdir -p out && printf '# New\\n' > out/new.md && printf '# Hello\\nmore\\n' > README.md"
        " && rm docs/guide.md && git mv src/app.py src/main.py"
        " && printf 'a\\0b' > out/blob.bin"
        f" && {_COMMIT} commit -q -m work",
    )
    return tree


async def test_branch_diff_lists_files_and_the_unified_diff(sandbox: Sandbox) -> None:
    tree = await writer(sandbox)

    result = await branch_diff(sandbox, tree.branch)

    assert sorted(result.files, key=lambda f: f.path) == [
        DiffFile(path="README.md", status="modified", added=2, removed=1),
        DiffFile(path="docs/guide.md", status="deleted", added=0, removed=1),
        DiffFile(path="out/blob.bin", status="added"),
        DiffFile(path="out/new.md", status="added", added=1, removed=0),
        DiffFile(path="src/main.py", status="renamed", old_path="src/app.py", added=0, removed=0),
    ]
    assert next(f for f in result.files if f.path == "out/blob.bin").binary
    assert "+# Hello" in result.diff
    assert "+more" in result.diff
    assert "rename from src/app.py" in result.diff
    assert "Binary files" in result.diff
    assert not result.truncated


async def test_branch_diff_limits_to_one_path(sandbox: Sandbox) -> None:
    tree = await writer(sandbox)

    result = await branch_diff(sandbox, tree.branch, path="README.md")

    assert [f.path for f in result.files] == ["README.md"]
    assert "out/new.md" not in result.diff


async def test_branch_diff_cuts_a_long_diff_at_a_line(sandbox: Sandbox) -> None:
    tree = await add_worktree(sandbox, RUN_ID, "writer")
    await sh(
        tree,
        'i=0; while [ $i -lt 400 ]; do echo "line $i"; i=$((i+1)); done > big.txt'
        f" && {_COMMIT} commit -q -m big",
    )

    result = await branch_diff(sandbox, tree.branch, max_bytes=1000)

    assert result.truncated
    assert len(result.diff.encode()) <= 1000
    assert result.diff.endswith("\n")
    assert [f.path for f in result.files] == ["big.txt"]


async def test_a_missing_branch_is_refused(sandbox: Sandbox) -> None:
    with pytest.raises(BranchNotFoundError):
        await branch_diff(sandbox, "agent/x/nobody")
    with pytest.raises(BranchNotFoundError):
        await show_file(sandbox, "agent/x/nobody", "README.md", first=1, last=2, max_bytes=100)
    assert not await branch_has_commits(sandbox, "agent/x/nobody")


async def test_a_branch_has_commits_only_after_its_writer_committed(sandbox: Sandbox) -> None:
    tree = await add_worktree(sandbox, RUN_ID, "writer")
    assert not await branch_has_commits(sandbox, tree.branch)

    await sh(tree, f"echo x > x.txt && {_COMMIT} commit -q -m x")

    assert await branch_has_commits(sandbox, tree.branch)


async def test_uncommitted_work_is_not_read(sandbox: Sandbox) -> None:
    tree = await add_worktree(sandbox, RUN_ID, "writer")
    await sh(tree, "echo draft > draft.txt")

    assert (await branch_diff(sandbox, tree.branch)).files == []
    with pytest.raises(RefPathError):
        await show_file(sandbox, tree.branch, "draft.txt", first=1, last=5, max_bytes=100)


async def test_show_file_reads_a_range_and_counts_lines(sandbox: Sandbox) -> None:
    tree = await writer(sandbox)

    whole = await show_file(sandbox, tree.branch, "README.md", first=1, last=10, max_bytes=1000)
    second = await show_file(sandbox, tree.branch, "README.md", first=2, last=2, max_bytes=1000)
    cut = await show_file(sandbox, tree.branch, "README.md", first=1, last=10, max_bytes=3)

    assert (whole.total, whole.text) == (2, "# Hello\nmore\n")
    assert (second.total, second.text) == (2, "more\n")
    assert cut.text == "# H"


@pytest.mark.parametrize(
    ("path", "kind"),
    [("nope.txt", "missing"), ("out", "not_a_file"), ("out/blob.bin", "binary")],
)
async def test_show_file_refuses_what_is_not_a_text_file(
    sandbox: Sandbox, path: str, kind: str
) -> None:
    tree = await writer(sandbox)

    with pytest.raises(RefPathError) as raised:
        await show_file(sandbox, tree.branch, path, first=1, last=5, max_bytes=100)

    assert raised.value.kind == kind


async def test_a_path_outside_the_repo_is_not_found(sandbox: Sandbox) -> None:
    tree = await writer(sandbox)

    with pytest.raises(RefPathError):
        await show_file(sandbox, tree.branch, "../../etc/passwd", first=1, last=5, max_bytes=100)


async def test_list_tree_respects_the_depth(sandbox: Sandbox) -> None:
    tree = await writer(sandbox)

    shallow = await list_tree(sandbox, tree.branch, ".", depth=1)
    deep = await list_tree(sandbox, tree.branch, "src", depth=2)

    assert shallow == ["README.md", "out/", "src/"]
    assert deep == ["src/main.py", "src/pkg/", "src/pkg/__init__.py", "src/pkg/deep/"]
    with pytest.raises(RefPathError):
        await list_tree(sandbox, tree.branch, "README.md", depth=1)


async def test_grep_tree_returns_hits_by_path_and_line(sandbox: Sandbox) -> None:
    tree = await writer(sandbox)

    hits = await grep_tree(sandbox, tree.branch, "hello|more", ignore_case=True, max_lines=50)
    nothing = await grep_tree(sandbox, tree.branch, "zzz", max_lines=50)

    assert hits == [
        ("README.md", 1, "# Hello"),
        ("README.md", 2, "more"),
        ("src/main.py", 1, "print('hello')"),
    ]
    assert nothing == []


async def test_grep_tree_skips_binary_files(sandbox: Sandbox) -> None:
    tree = await writer(sandbox)

    assert await grep_tree(sandbox, tree.branch, "b", path="out", max_lines=50) == []
