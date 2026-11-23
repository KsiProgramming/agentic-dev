"""Declared paths in the repo tools (13.7): a step that declared `paths` cannot write or commit
anything outside them, whatever route the change takes, with one fixed text."""

import re
from uuid import UUID

import pytest

from agentic_runtime import ProtectedPaths
from agentic_sandbox import Sandbox, add_worktree
from agentic_tools.repo import open_repo_tools


def said(text: str) -> str:
    return re.sub(r"^Error executing tool \w+: ", "", text)


def declaring(*globs: str, node: str = "impl") -> ProtectedPaths:
    protected = ProtectedPaths()
    protected.declared.set(node, list(globs))
    return protected


async def sh(box: Sandbox, script: str) -> str:
    result = await box.exec(["sh", "-c", script])
    assert result.exit_code == 0, result.stderr
    return result.stdout.strip()


async def test_write_file_refuses_a_path_outside_the_declared_ones_with_a_fixed_text(
    sandbox: Sandbox, run_id: UUID
) -> None:
    async with open_repo_tools(
        sandbox, run_id=run_id, writers=["impl", "other"], protected=declaring("docs/**")
    ) as tools:
        outside = await tools.call(
            "repo.write_file", {"path": "CHANGES.md", "content": "x"}, node_id="impl"
        )
        inside = await tools.call(
            "repo.write_file", {"path": "./docs/Guide.md", "content": "x"}, node_id="impl"
        )
        free = await tools.call(
            "repo.write_file", {"path": "CHANGES.md", "content": "x"}, node_id="other"
        )

    assert outside.is_error
    assert said(outside.text) == (
        "'CHANGES.md' is outside the paths this step may write (`docs/**`): it was not written"
    )
    assert not inside.is_error and not free.is_error  # a node with no `paths` writes anywhere
    tree = await add_worktree(sandbox, run_id, "impl")
    assert await sh(tree, "test -e CHANGES.md && echo yes || echo no") == "no"


async def test_a_refused_write_commits_nothing(sandbox: Sandbox, run_id: UUID) -> None:
    async with open_repo_tools(
        sandbox, run_id=run_id, writers=["impl"], protected=declaring("docs/**")
    ) as tools:
        await tools.call("repo.write_file", {"path": "a.txt", "content": "x"}, node_id="impl")
        commit = await tools.call("repo.commit", {"message": "m"}, node_id="impl")

    assert said(commit.text) == "nothing to commit: write a file first"


async def test_commit_refuses_a_file_written_outside_the_declared_paths_by_other_means(
    sandbox: Sandbox, run_id: UUID
) -> None:
    async with open_repo_tools(
        sandbox, run_id=run_id, writers=["impl"], protected=declaring("docs/**")
    ) as tools:
        tree = await add_worktree(sandbox, run_id, "impl")
        await sh(tree, "echo x > stray.txt")
        await tools.call("repo.write_file", {"path": "docs/a.md", "content": "y"}, node_id="impl")
        commit = await tools.call("repo.commit", {"message": "m"}, node_id="impl")
        log = await sh(tree, "git log --oneline | wc -l")
        staged = await sh(tree, "git diff --cached --name-only")

    assert commit.is_error
    assert "'stray.txt' is outside the paths this step may write" in commit.text
    assert log == "1" and staged == ""  # the base commit only, and the index as it was


async def test_commit_refuses_a_symlinked_directory_that_leads_out(
    sandbox: Sandbox, run_id: UUID
) -> None:
    async with open_repo_tools(
        sandbox, run_id=run_id, writers=["impl"], protected=declaring("docs/**")
    ) as tools:
        tree = await add_worktree(sandbox, run_id, "impl")
        await sh(tree, "mkdir -p docs && ln -s ../src docs/out")
        if await sh(tree, "test -L docs/out && echo link || echo copy") != "link":
            pytest.skip("this host cannot make symlinks")
        await sh(tree, "mkdir -p src && echo x > src/leak.txt")
        commit = await tools.call("repo.commit", {"message": "m"}, node_id="impl")

    assert commit.is_error
    assert "'src/leak.txt' is outside the paths this step may write" in commit.text


async def test_commit_refuses_a_rename_from_outside_into_the_declared_paths(
    sandbox: Sandbox, run_id: UUID
) -> None:
    tree = await add_worktree(sandbox, run_id, "impl")
    await sh(
        tree,
        "mkdir -p src docs && echo r > src/a.py && git add -A && git -c user.name=t "
        "-c user.email=t@e.invalid commit -q -m base-file",
    )
    async with open_repo_tools(
        sandbox, run_id=run_id, writers=["impl"], protected=declaring("docs/**")
    ) as tools:
        await sh(tree, "mv src/a.py docs/a.py")
        commit = await tools.call("repo.commit", {"message": "m"}, node_id="impl")

    assert commit.is_error
    assert "'src/a.py' is outside the paths this step may write" in commit.text


async def test_a_task_of_an_orchestrator_is_held_to_its_own_key(
    sandbox: Sandbox, run_id: UUID
) -> None:
    protected = declaring("docs/**", node="fix.t1")
    async with open_repo_tools(
        sandbox, run_id=run_id, task_writers=["fix"], protected=protected
    ) as tools:
        held = await tools.call(
            "repo.write_file", {"path": "src/a.py", "content": "x"}, node_id="fix.t1"
        )
        free = await tools.call(
            "repo.write_file", {"path": "src/a.py", "content": "x"}, node_id="fix.t2"
        )

    assert held.is_error and not free.is_error
