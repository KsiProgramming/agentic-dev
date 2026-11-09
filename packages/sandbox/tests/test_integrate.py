"""Writers' branches merged into one integration branch (6.3), on both backends."""

from uuid import UUID

import pytest

from agentic_sandbox import Sandbox, SandboxError, add_worktree
from agentic_sandbox.integrate import MergeSource, integrate_branches

RUN_ID = UUID("00000000-0000-4000-8000-000000000001")
# The clone is root's in the Docker sandbox: git needs it marked safe.
_SAFE = 'git -c safe.directory="$(pwd -P)"'
_COMMIT = "git add -A && git -c user.name=t -c user.email=t@e.invalid -c commit.gpgsign=false"


async def sh(box: Sandbox, script: str, cwd: str | None = None) -> str:
    result = await box.exec(["sh", "-c", script], cwd=cwd)
    assert result.exit_code == 0, result.stderr
    return result.stdout.strip()


async def task(sandbox: Sandbox, key: str, script: str) -> None:
    """A task writer `key` that ran `script` in its worktree and committed it."""
    tree = await add_worktree(sandbox, RUN_ID, key)
    await sh(tree, f"{script} && {_COMMIT} commit -q -m {key}")


def sources(*keys: str) -> list[MergeSource]:
    return [MergeSource(key=k, message=f"Merge task '{k.split('.')[1]}': {k}") for k in keys]


async def test_clean_branches_merge_in_order(sandbox: Sandbox) -> None:
    await task(sandbox, "fix.a", "printf 'a\\n' > a.txt")
    await task(sandbox, "fix.b", "printf 'b\\n' > b.txt")

    outcome = await integrate_branches(sandbox, RUN_ID, "fix", sources("fix.a", "fix.b"))

    tree = f"{sandbox.worktrees_dir}/fix"
    assert outcome.branch == f"agent/{RUN_ID}/fix"
    assert outcome.merged == ["fix.a", "fix.b"]
    assert outcome.empty == [] and outcome.conflicts == {}
    assert outcome.head == await sh(sandbox, "git rev-parse HEAD", cwd=tree)
    log = await sh(sandbox, "git log --merges --format=%s%x09%an", cwd=tree)
    assert log.splitlines() == [
        "Merge task 'b': fix.b\tagentic-dev agent",
        "Merge task 'a': fix.a\tagentic-dev agent",
    ]
    assert await sh(sandbox, "cat a.txt b.txt", cwd=tree) == "a\nb"


async def test_a_conflict_is_reported_and_the_others_still_merge(sandbox: Sandbox) -> None:
    await task(sandbox, "fix.a", "printf 'from a\\n' > README.md")
    await task(sandbox, "fix.b", "printf 'from b\\n' > README.md && printf 'x' > x.txt")
    await task(sandbox, "fix.c", "printf 'c\\n' > c.txt")

    outcome = await integrate_branches(sandbox, RUN_ID, "fix", sources("fix.a", "fix.b", "fix.c"))

    tree = f"{sandbox.worktrees_dir}/fix"
    assert outcome.merged == ["fix.a", "fix.c"]
    assert outcome.conflicts == {"fix.b": ["README.md"]}
    # No merge left in progress, and nothing of b's in the branch.
    assert await sh(sandbox, "git status --porcelain", cwd=tree) == ""
    assert await sh(sandbox, "cat README.md", cwd=tree) == "from a"
    assert "x.txt" not in (await sh(sandbox, "ls", cwd=tree)).split()
    # b's own branch is left as it was.
    assert await sh(sandbox, f"{_SAFE} show agent/{RUN_ID}/fix.b:README.md") == "from b"


async def test_a_branch_with_no_commits_or_none_at_all_is_empty(sandbox: Sandbox) -> None:
    await add_worktree(sandbox, RUN_ID, "fix.a")

    outcome = await integrate_branches(sandbox, RUN_ID, "fix", sources("fix.a", "fix.none"))

    assert outcome.merged == [] and outcome.empty == ["fix.a", "fix.none"]
    assert outcome.head == await sh(sandbox, f"{_SAFE} rev-parse HEAD")


async def test_integrating_again_merges_nothing_twice(sandbox: Sandbox) -> None:
    await task(sandbox, "fix.a", "printf 'a\\n' > a.txt")
    first = await integrate_branches(sandbox, RUN_ID, "fix", sources("fix.a"))
    await task(sandbox, "fix.b", "printf 'b\\n' > b.txt")

    again = await integrate_branches(sandbox, RUN_ID, "fix", sources("fix.a", "fix.b"))

    tree = f"{sandbox.worktrees_dir}/fix"
    assert first.merged == ["fix.a"]
    assert again.merged == ["fix.a", "fix.b"]
    assert await sh(sandbox, "git rev-list --merges --count HEAD", cwd=tree) == "2"


async def test_a_message_with_a_nul_is_refused(sandbox: Sandbox) -> None:
    with pytest.raises(ValueError):
        await integrate_branches(sandbox, RUN_ID, "fix", [MergeSource("fix.a", "a\0b")])


async def test_a_worktree_on_another_branch_is_refused(sandbox: Sandbox) -> None:
    await sh(sandbox, f"mkdir -p '{sandbox.worktrees_dir}/fix'")

    with pytest.raises(SandboxError):
        await integrate_branches(sandbox, RUN_ID, "fix", sources("fix.a"))
