"""A writer's branch bundled out of the sandbox, and `take_file`, on both backends."""

import os
import subprocess
from pathlib import Path
from uuid import UUID

import pytest

from agentic_sandbox import (
    BranchBundle,
    EmptyBranchError,
    RepoSource,
    Sandbox,
    SandboxError,
    SandboxManager,
    add_worktree,
    branch_heads,
    export_branch,
)

RUN_ID = UUID("00000000-0000-4000-8000-000000000001")
_ENV = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, env=_ENV, check=True, capture_output=True, text=True
    ).stdout.strip()


async def commit(box: Sandbox, files: dict[str, str]) -> None:
    script = " && ".join(f"printf '%s' '{text}' > {name}" for name, text in files.items())
    result = await box.exec(
        ["sh", "-c", f"{script} && git add -A && git -c user.name=t -c user.email=t@e.invalid "
         "-c commit.gpgsign=false commit -q -m work"]
    )  # fmt: skip
    assert result.exit_code == 0, result.stderr


async def test_a_branch_bundles_onto_the_clone_head(
    sandbox: Sandbox, repos: Path, tmp_path: Path
) -> None:
    tree = await add_worktree(sandbox, RUN_ID, "writer")
    await commit(tree, {"NOTES.md": "notes"})

    bundle = await export_branch(sandbox, tree.branch)

    origin = repos / "hello"
    assert bundle.base_sha == git(origin, "rev-parse", "HEAD")
    # The bundle applies on top of the base, fetched from the origin, as a push does.
    target = tmp_path / "target"
    git(tmp_path, "init", "-q", str(target))
    git(target, "fetch", "-q", "--depth", "1", origin.resolve().as_uri(), bundle.base_sha)
    (tmp_path / "b.bundle").write_bytes(bundle.data)
    ref = f"refs/heads/{tree.branch}"
    git(target, "fetch", "-q", str(tmp_path / "b.bundle"), f"{ref}:{ref}")
    assert git(target, "show", f"{ref}:NOTES.md") == "notes"
    assert git(target, "rev-list", "--count", f"{bundle.base_sha}..{ref}") == "1"


async def test_the_bundle_leaves_nothing_behind(sandbox: Sandbox) -> None:
    tree = await add_worktree(sandbox, RUN_ID, "writer")
    await commit(tree, {"NOTES.md": "notes"})

    await export_branch(sandbox, tree.branch)

    listing = await sandbox.exec(["ls", "-A", sandbox.staging_dir])
    assert listing.stdout.strip() == ""


async def test_a_branch_without_commits_is_refused(sandbox: Sandbox) -> None:
    tree = await add_worktree(sandbox, RUN_ID, "writer")

    with pytest.raises(SandboxError, match="no commits"):
        await export_branch(sandbox, tree.branch)
    with pytest.raises(SandboxError, match="no commits"):
        await export_branch(sandbox, f"agent/{RUN_ID}/missing")


@pytest.mark.parametrize("branch", ["-x", "a/../b", "a b", ""])
async def test_only_branch_names_are_bundled(sandbox: Sandbox, branch: str) -> None:
    with pytest.raises(ValueError, match="not a branch"):
        await export_branch(sandbox, branch)


async def test_take_file_hands_out_a_staged_file_once(sandbox: Sandbox) -> None:
    path = await sandbox.put_file(b"payload")

    assert await sandbox.take_file(path) == b"payload"
    with pytest.raises(SandboxError, match="no such file"):
        await sandbox.take_file(path)


async def test_take_file_only_takes_from_the_staging_dir(sandbox: Sandbox) -> None:
    for path in (
        f"{sandbox.workdir}/README.md",
        f"{sandbox.staging_dir}/../repo/README.md",
        sandbox.staging_dir,
    ):
        with pytest.raises(ValueError, match="staging"):
            await sandbox.take_file(path)


async def test_take_file_refuses_more_than_the_limit(
    backend: tuple[str, SandboxManager], sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = "agentic_sandbox.fake" if backend[0] == "fake" else "agentic_sandbox.docker_backend"
    monkeypatch.setattr(f"{module}.MAX_TAKE_FILE_BYTES", 4)
    path = await sandbox.put_file(b"12345")

    with pytest.raises(SandboxError, match="too large"):
        await sandbox.take_file(path)


async def test_a_bundle_records_its_branch_s_tip_and_commit_count(sandbox: Sandbox) -> None:
    tree = await add_worktree(sandbox, RUN_ID, "writer")
    await commit(tree, {"A.md": "a"})
    await commit(tree, {"B.md": "b"})

    bundle = await export_branch(sandbox, tree.branch)
    heads = await branch_heads(sandbox, f"agent/{RUN_ID}/")

    assert bundle.commits == 2
    assert heads.base == bundle.base_sha
    assert heads.branches == {tree.branch: bundle.head_sha}


async def test_a_branch_without_commits_is_an_empty_branch(sandbox: Sandbox) -> None:
    tree = await add_worktree(sandbox, RUN_ID, "writer")

    with pytest.raises(EmptyBranchError):
        await export_branch(sandbox, tree.branch)


async def test_a_fresh_sandbox_gets_the_saved_branches_back(
    backend: tuple[str, SandboxManager], repos: Path
) -> None:
    """12.2: a branch saved from one sandbox is restored into the next one the run opens, at
    the run's base, and a writer's worktree reopens on it."""
    manager = backend[1]
    repo = RepoSource(url=str(repos / "hello"))
    async with manager.open(RUN_ID, repo) as first:
        assert first.restored == ()
        tree = await add_worktree(first, RUN_ID, "writer")
        await commit(tree, {"NOTES.md": "notes"})
        saved = await export_branch(first, tree.branch)

    async with manager.open(RUN_ID, repo, at=saved.base_sha, restore=[saved]) as second:
        assert second.restored == (tree.branch,)
        heads = await branch_heads(second, f"agent/{RUN_ID}/")
        assert heads.branches == {tree.branch: saved.head_sha}
        again = await add_worktree(second, RUN_ID, "writer")
        shown = await again.exec(["cat", "NOTES.md"])
        assert shown.stdout == "notes"


async def test_a_reopened_sandbox_is_not_restored_over(
    backend: tuple[str, SandboxManager], repos: Path
) -> None:
    manager = backend[1]
    repo = RepoSource(url=str(repos / "hello"))
    async with manager.open(RUN_ID, repo) as first:
        tree = await add_worktree(first, RUN_ID, "writer")
        await commit(tree, {"NOTES.md": "notes"})
        saved = await export_branch(first, tree.branch)
        await commit(tree, {"MORE.md": "more"})  # after the save
        manager.keep(RUN_ID)

    try:
        async with manager.open(RUN_ID, repo, reuse=True, restore=[saved]) as kept:
            assert kept.restored == ()
            heads = await branch_heads(kept, f"agent/{RUN_ID}/")
            assert heads.branches[tree.branch] != saved.head_sha
    finally:
        await manager.discard(RUN_ID)


async def test_a_bundle_that_does_not_apply_fails_the_open(
    backend: tuple[str, SandboxManager], repos: Path
) -> None:
    bad = BranchBundle(branch=f"agent/{RUN_ID}/writer", base_sha="0" * 40, data=b"not a bundle")
    with pytest.raises(SandboxError, match=f"could not restore branch agent/{RUN_ID}/writer"):
        async with backend[1].open(RUN_ID, RepoSource(url=str(repos / "hello")), restore=[bad]):
            pass
