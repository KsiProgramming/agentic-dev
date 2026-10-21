"""Writer worktrees and staged files, on both sandbox backends: the fake one needs `sh` and `git`
on the host, the Docker one a daemon. Each is skipped where it cannot run."""

import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import docker
import pytest
from docker.errors import DockerException

from agentic_sandbox import (
    MAX_PUT_FILE_BYTES,
    FakeSandboxManager,
    RepoSource,
    Sandbox,
    SandboxError,
    SandboxManager,
    add_worktree,
    branch_name,
)
from agentic_sandbox.docker_backend import DockerSandboxManager
from agentic_sandbox.testing import ensure_sandbox_image

RUN_ID = UUID("00000000-0000-4000-8000-000000000001")
COMMIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q"]


@pytest.fixture(params=["fake", pytest.param("docker", marks=pytest.mark.integration)])
def backend(request: pytest.FixtureRequest, repos: Path) -> tuple[str, SandboxManager]:
    if request.param == "fake":
        if not (shutil.which("sh") and shutil.which("git")):
            pytest.skip("needs sh and git on the host")
        return "fake", FakeSandboxManager(local_root=repos)
    try:
        client = docker.from_env()
        client.ping()
    except DockerException:
        pytest.skip("no Docker daemon")
    ensure_sandbox_image(client)
    return "docker", DockerSandboxManager(client, local_root=repos)


@pytest.fixture
async def sandbox(backend: tuple[str, SandboxManager], repos: Path) -> AsyncIterator[Sandbox]:
    async with backend[1].open(RUN_ID, RepoSource(url=str(repos / "hello"))) as box:
        yield box


async def sh(box: Sandbox, script: str, cwd: str | None = None) -> tuple[int, str]:
    result = await box.exec(["sh", "-c", script], cwd=cwd)
    return result.exit_code, (result.stdout + result.stderr).strip()


async def test_a_writer_gets_a_worktree_on_its_own_branch_from_head(sandbox: Sandbox) -> None:
    tree = await add_worktree(sandbox, RUN_ID, "writer")

    assert tree.branch == branch_name(RUN_ID, "writer") == f"agent/{RUN_ID}/writer"
    assert tree.workdir == f"{sandbox.worktrees_dir}/writer"
    assert await sh(tree, "git rev-parse --abbrev-ref HEAD") == (0, tree.branch)
    assert await sh(tree, "git log --format=%s") == (0, "init")
    assert await sh(tree, "cat README.md") == (0, "# Hello repo")


async def test_adding_the_same_worktree_again_reuses_it(sandbox: Sandbox) -> None:
    first = await add_worktree(sandbox, RUN_ID, "writer")
    await sh(first, "echo kept > kept.txt")

    again = await add_worktree(sandbox, RUN_ID, "writer")

    assert again.workdir == first.workdir
    assert await sh(again, "cat kept.txt") == (0, "kept")


async def test_a_commit_in_the_shallow_clone_lands_on_the_writer_branch(sandbox: Sandbox) -> None:
    tree = await add_worktree(sandbox, RUN_ID, "writer")

    code, out = await sh(tree, f"echo hi > NOTES.md && git add -A && {' '.join(COMMIT)} -m note")
    assert (code, out) == (0, "")

    assert await sh(tree, "git log --format=%s") == (0, "note\ninit")
    assert await sh(sandbox, "git -c safe.directory=* branch --list 'agent/*'") == (
        0,
        f"+ {tree.branch}",
    )
    assert await sh(sandbox, "test -e NOTES.md") == (1, "")


async def test_each_writer_has_its_own_worktree(sandbox: Sandbox) -> None:
    one = await add_worktree(sandbox, RUN_ID, "one")
    two = await add_worktree(sandbox, RUN_ID, "two")

    await sh(one, "echo one > only-one.txt")

    assert one.workdir != two.workdir
    assert (await sh(two, "test -e only-one.txt"))[0] == 1
    assert await sh(two, "git rev-parse --abbrev-ref HEAD") == (0, two.branch)


@pytest.mark.parametrize("node_id", ["Writer", "../x", "a/b", "", "-x"])
async def test_only_node_ids_name_worktrees(sandbox: Sandbox, node_id: str) -> None:
    with pytest.raises(ValueError, match="not a node id"):
        await add_worktree(sandbox, RUN_ID, node_id)


async def test_commands_only_run_in_the_checkout_or_a_worktree(sandbox: Sandbox) -> None:
    for cwd in (sandbox.worktrees_dir, f"{sandbox.workdir}/..", "/etc"):
        with pytest.raises(ValueError, match="cwd"):
            await sandbox.exec(["true"], cwd=cwd)


async def test_put_file_stages_the_bytes_outside_the_checkout(sandbox: Sandbox) -> None:
    path = await sandbox.put_file(b"line 1\nline 2\n")

    assert "/.incoming/" in path
    assert await sh(sandbox, f"cat '{path}'") == (0, "line 1\nline 2")
    assert (await sh(sandbox, "git -c safe.directory=* status --porcelain")) == (0, "")


async def test_put_file_refuses_more_than_the_limit(sandbox: Sandbox) -> None:
    with pytest.raises(SandboxError, match="too large"):
        await sandbox.put_file(b"x" * (MAX_PUT_FILE_BYTES + 1))


@pytest.mark.integration
async def test_in_docker_the_checkout_stays_read_only_and_staged_files_are_the_users(
    backend: tuple[str, SandboxManager], sandbox: Sandbox
) -> None:
    if backend[0] != "docker":
        pytest.skip("the fake sandbox does not isolate permissions")
    tree = await add_worktree(sandbox, RUN_ID, "writer")
    staged = await sandbox.put_file(b"x")

    assert (await sh(sandbox, "touch README.md"))[0] != 0
    assert (await sh(sandbox, "touch new.txt"))[0] != 0
    assert (await sh(tree, "touch new.txt"))[0] == 0
    assert await sh(sandbox, f"stat -c %u '{staged}'") == (0, "1000")


def test_a_fresh_run_id_names_a_fresh_branch() -> None:
    assert branch_name(uuid4(), "a") != branch_name(uuid4(), "a")
