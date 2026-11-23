"""Protected paths in the repo tools (13.5): a writer cannot change them, whatever route its write
takes, and each refusal is one fixed text and one callback."""

import re
from uuid import UUID

import pytest

from agentic_runtime import ProtectedPaths, ProtectRule
from agentic_sandbox import Sandbox, add_worktree
from agentic_tools.repo import open_repo_tools

DEFAULT = ProtectRule(".github/workflows/**", "default")
CONFIG = ProtectRule("**/.editorconfig", "default")
WORKFLOW = ProtectRule("tests/**", "workflow")
FROZEN = ProtectRule("tests/test_cart.py", "frozen", writer="test_writer", gate="approve_tests")


def said(text: str) -> str:
    return re.sub(r"^Error executing tool \w+: ", "", text)


class Refusals:
    def __init__(self) -> None:
        self.seen: list[tuple[str, str, str, str]] = []

    def __call__(self, node: str, tool: str, path: str, rule: ProtectRule) -> None:
        self.seen.append((node, tool, path, rule.kind))


def protection(
    *,
    rules: list[ProtectRule] | None = None,
    allow: dict[str, list[str]] | None = None,
    frozen: dict[str, list[ProtectRule]] | None = None,
) -> tuple[ProtectedPaths, Refusals]:
    refusals = Refusals()
    protected = ProtectedPaths(refusals)
    protected.set(rules if rules is not None else [DEFAULT, CONFIG, WORKFLOW], allow, frozen)
    return protected, refusals


async def sh(box: Sandbox, script: str) -> str:
    result = await box.exec(["sh", "-c", script])
    assert result.exit_code == 0, result.stderr
    return result.stdout.strip()


async def test_write_file_refuses_each_kind_of_rule_with_its_fixed_text(
    sandbox: Sandbox, run_id: UUID
) -> None:
    protected, refusals = protection(frozen={"impl": [FROZEN]})
    async with open_repo_tools(
        sandbox, run_id=run_id, writers=["impl"], protected=protected
    ) as tools:
        ci = await tools.call(
            "repo.write_file", {"path": ".github/workflows/ci.yml", "content": "x"}, node_id="impl"
        )
        config = await tools.call(
            "repo.write_file", {"path": "src/.editorconfig", "content": "x"}, node_id="impl"
        )
        flow = await tools.call(
            "repo.write_file", {"path": "tests/a.py", "content": "x"}, node_id="impl"
        )
        frozen = await tools.call(
            "repo.write_file", {"path": "./Tests/Test_Cart.py", "content": "x"}, node_id="impl"
        )
        ok = await tools.call(
            "repo.write_file", {"path": "src/a.py", "content": "x"}, node_id="impl"
        )

    assert (ci.is_error, said(ci.text)) == (
        True,
        "'.github/workflows/ci.yml' is protected by the platform (CI and analyzer config): "
        "you can read it but not change it",
    )
    assert "by the platform" in config.text
    assert said(flow.text) == (
        "'tests/a.py' is protected by this workflow (tests/**): you can read it but not change it"
    )
    assert "approved at 'approve_tests' from 'test_writer'" in frozen.text
    assert not ok.is_error
    assert refusals.seen == [
        ("impl", "repo.write_file", ".github/workflows/ci.yml", "default"),
        ("impl", "repo.write_file", "src/.editorconfig", "default"),
        ("impl", "repo.write_file", "tests/a.py", "workflow"),
        ("impl", "repo.write_file", "Tests/Test_Cart.py", "frozen"),
    ]
    tree = await add_worktree(sandbox, run_id, "impl")
    assert await sh(tree, "ls -A .github 2>/dev/null | wc -l") == "0"
    assert await sh(tree, "test -e tests/a.py && echo yes || echo no") == "no"


async def test_a_refused_write_writes_nothing_and_commits_nothing(
    sandbox: Sandbox, run_id: UUID
) -> None:
    protected, _ = protection()
    async with open_repo_tools(
        sandbox, run_id=run_id, writers=["impl"], protected=protected
    ) as tools:
        await tools.call(
            "repo.write_file", {"path": ".github/workflows/ci.yml", "content": "x"}, node_id="impl"
        )
        commit = await tools.call("repo.commit", {"message": "m"}, node_id="impl")

    assert said(commit.text) == "nothing to commit: write a file first"


async def test_commit_refuses_a_protected_path_written_through_a_symlinked_directory(
    sandbox: Sandbox, run_id: UUID
) -> None:
    protected, refusals = protection()
    async with open_repo_tools(
        sandbox, run_id=run_id, writers=["impl"], protected=protected
    ) as tools:
        tree = await add_worktree(sandbox, run_id, "impl")
        await sh(tree, "mkdir -p .github/workflows && ln -s .github/workflows ci")
        if await sh(tree, "test -L ci && echo link || echo copy") != "link":
            pytest.skip("this host cannot make symlinks")
        # `write_file` never follows the link; anything else that writes into the worktree may.
        await sh(tree, "echo x > ci/build.yml")
        await tools.call("repo.write_file", {"path": "ok.txt", "content": "y"}, node_id="impl")
        commit = await tools.call("repo.commit", {"message": "m"}, node_id="impl")
        log = await sh(tree, "git log --oneline | wc -l")
        staged = await sh(tree, "git diff --cached --name-only")

    assert commit.is_error
    assert "'.github/workflows/build.yml' is protected by the platform" in commit.text
    assert ("impl", "repo.commit", ".github/workflows/build.yml", "default") in refusals.seen
    assert log == "1"  # the run's base commit only
    assert staged == ""  # the index is as it was


async def test_commit_refuses_a_rename_out_of_a_protected_path(
    sandbox: Sandbox, run_id: UUID
) -> None:
    protected, refusals = protection(rules=[CONFIG])
    tree = await add_worktree(sandbox, run_id, "impl")
    await sh(
        tree,
        "echo r > .editorconfig && git add -A && git -c user.name=t -c user.email=t@e.invalid "
        "commit -q -m base-config",
    )
    async with open_repo_tools(
        sandbox, run_id=run_id, writers=["impl"], protected=protected
    ) as tools:
        await sh(tree, "mv .editorconfig moved.txt")
        commit = await tools.call("repo.commit", {"message": "m"}, node_id="impl")

    assert commit.is_error
    assert "'.editorconfig' is protected" in commit.text
    assert [(p, k) for _, _, p, k in refusals.seen] == [(".editorconfig", "default")]


async def test_an_allowed_node_writes_its_paths_and_only_those(
    sandbox: Sandbox, run_id: UUID
) -> None:
    protected, refusals = protection(allow={"test_writer": ["tests/**"]})
    async with open_repo_tools(
        sandbox, run_id=run_id, writers=["test_writer", "impl"], protected=protected
    ) as tools:
        allowed = await tools.call(
            "repo.write_file", {"path": "tests/a.py", "content": "x"}, node_id="test_writer"
        )
        still_ci = await tools.call(
            "repo.write_file",
            {"path": ".github/workflows/ci.yml", "content": "x"},
            node_id="test_writer",
        )
        other = await tools.call(
            "repo.write_file", {"path": "tests/b.py", "content": "x"}, node_id="impl"
        )
        commit = await tools.call("repo.commit", {"message": "tests"}, node_id="test_writer")

    assert not allowed.is_error
    assert still_ci.is_error
    assert other.is_error
    assert not commit.is_error
    assert [p for _, _, p, _ in refusals.seen] == [".github/workflows/ci.yml", "tests/b.py"]


async def test_an_orchestrators_task_takes_its_orchestrators_rules(
    sandbox: Sandbox, run_id: UUID
) -> None:
    protected, refusals = protection(frozen={"fix": [FROZEN]}, allow={"fixer": ["tests/**"]})
    async with open_repo_tools(
        sandbox, run_id=run_id, task_writers=["fix"], protected=protected
    ) as tools:
        frozen = await tools.call(
            "repo.write_file", {"path": "tests/test_cart.py", "content": "x"}, node_id="fix.t1"
        )
        ci = await tools.call(
            "repo.write_file", {"path": ".github/workflows/x.yml", "content": "x"}, node_id="fix.t2"
        )
        ok = await tools.call(
            "repo.write_file", {"path": "src/a.py", "content": "x"}, node_id="fix.t1"
        )

    assert frozen.is_error and ci.is_error and not ok.is_error
    assert [(n, k) for n, _, _, k in refusals.seen] == [("fix.t1", "frozen"), ("fix.t2", "default")]


async def test_readers_and_unprotected_runs_are_unchanged(sandbox: Sandbox, run_id: UUID) -> None:
    protected, refusals = protection()
    async with open_repo_tools(
        sandbox, run_id=run_id, writers=["impl"], protected=protected
    ) as tools:
        read = await tools.call("repo.list_files", {}, node_id="reviewer")
    async with open_repo_tools(sandbox, run_id=run_id, writers=["impl"]) as tools:
        free = await tools.call(
            "repo.write_file", {"path": ".github/workflows/ci.yml", "content": "x"}, node_id="impl"
        )

    assert not read.is_error
    assert not free.is_error
    assert refusals.seen == []
