"""`write_file` on a writer's `repo` server, on both sandbox backends (see conftest)."""

import posixpath
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from agentic_sandbox import (
    FakeSandboxManager,
    RepoSource,
    Sandbox,
    SandboxManager,
    Worktree,
    add_worktree,
)
from agentic_tools.repo import RepoLimits
from agentic_tools.testing import CallRepo, call_tool


async def sh(box: Sandbox, script: str) -> tuple[int, str]:
    result = await box.exec(["sh", "-c", script])
    return result.exit_code, (result.stdout + result.stderr).strip()


async def staged_files(box: Sandbox) -> str:
    incoming = posixpath.join(posixpath.dirname(box.worktrees_dir.replace("\\", "/")), ".incoming")
    return (await sh(box, f"ls -A '{incoming}'"))[1]


async def test_writes_a_new_file_the_writer_can_read_back(call_writer: CallRepo) -> None:
    text = "# Notes\n\nline two\n"

    assert await call_writer("write_file", path="NOTES.md", content=text) == (
        False,
        f"wrote NOTES.md ({len(text.encode())} bytes)",
    )
    assert await call_writer("read_file", path="NOTES.md") == (
        False,
        "1\t# Notes\n2\t\n3\tline two",
    )


async def test_overwrites_a_file(call_writer: CallRepo, worktree: Worktree) -> None:
    await call_writer("write_file", path="README.md", content="new\n")

    assert await sh(worktree, "cat README.md") == (0, "new")


async def test_creates_missing_parent_directories(call_writer: CallRepo) -> None:
    assert await call_writer("write_file", path="docs/a/b/deep.md", content="é\n") == (
        False,
        "wrote docs/a/b/deep.md (3 bytes)",
    )
    assert await call_writer("list_files", path="docs/a") == (False, "docs/a/b/\ndocs/a/b/deep.md")


async def test_the_bytes_are_written_exactly(call_writer: CallRepo, worktree: Worktree) -> None:
    await call_writer("write_file", path="crlf.txt", content="a\r\nb")

    assert await sh(worktree, "od -An -c crlf.txt | tr -s ' '") == (0, "a \\r \\n b")


async def test_the_shared_checkout_and_other_writers_do_not_see_the_write(
    call_writer: CallRepo, sandbox: Sandbox, run_id: UUID
) -> None:
    other = await add_worktree(sandbox, run_id, "other")

    await call_writer("write_file", path="NOTES.md", content="x\n")

    assert (await sh(sandbox, "test -e NOTES.md"))[0] == 1
    assert (await sh(other, "test -e NOTES.md"))[0] == 1


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("/etc/passwd", "path must stay inside the repository: /etc/passwd"),
        ("../escape.txt", "path must stay inside the repository"),
        ("src/../../escape.txt", "path must stay inside the repository"),
        ("C:/Windows/x.txt", "path must stay inside the repository"),
        (".", "path must name a file"),
        (".git/config", "cannot write inside .git"),
        ("src/.GIT/hooks/pre-commit", "cannot write inside .git"),
        (".git", "cannot write inside .git"),
        ("src", "a directory or file is in the way of: src"),
        ("README.md/inner.txt", "a directory or file is in the way of: README.md/inner.txt"),
    ],
)
async def test_refusals(call_writer: CallRepo, worktree: Worktree, path: str, message: str) -> None:
    is_error, text = await call_writer("write_file", path=path, content="x\n")

    assert is_error
    assert message in text
    assert str(Path.cwd()) not in text
    assert worktree.workdir not in text
    assert await staged_files(worktree) == ""


async def test_content_over_the_limit_is_refused(call_writer: CallRepo) -> None:
    assert await call_writer(
        "write_file", RepoLimits(max_write_bytes=4), path="big.txt", content="12345"
    ) == (True, "Error executing tool write_file: content too large: 5 bytes (at most 4)")


async def test_a_read_only_server_has_no_write_tools(call: CallRepo) -> None:
    for tool, arguments in (("write_file", {"path": "x", "content": "x"}), ("commit", {})):
        is_error, text = await call(tool, **arguments)
        assert is_error
        assert "Unknown tool" in text


async def test_symlinks_out_of_the_worktree_are_refused(
    manager: SandboxManager, repos: Path
) -> None:
    if isinstance(manager, FakeSandboxManager) and sys.platform == "win32":
        pytest.skip("symlinks need privileges on Windows")
    run_id = uuid4()

    async with manager.open(run_id, RepoSource(url=str(repos / "hello"))) as box:
        tree = await add_worktree(box, run_id, "writer")
        # Links a repo could hold, made in the worktree (the host may not be able to).
        links = "ln -s /etc etc; ln -s /etc/hosts hosts; ln -s docs inside; ln -s /nowhere dangling"
        assert (await sh(tree, links))[0] == 0

        async def write(path: str) -> tuple[bool, str]:
            arguments = {"path": path, "content": "x\n"}
            return await call_tool(tree, "write_file", arguments, writable=True)

        via_dir = await write("etc/x.conf")
        deep = await write("etc/new/x.conf")
        onto_link = await write("hosts")
        dangling = await write("dangling/x")
        inside = await write("inside/new.md")
        landed = await sh(tree, "cat docs/new.md")
        outside = await sh(tree, "ls /etc/x.conf /etc/new 2>&1; true")

    assert via_dir[0] and "inside the repository" in via_dir[1]
    assert deep[0] and "inside the repository" in deep[1]
    assert onto_link[0] and "inside the repository" in onto_link[1]
    assert dangling[0] and "in the way" in dangling[1]
    assert inside == (False, "wrote inside/new.md (2 bytes)")
    assert landed == (0, "x")
    assert "No such file" in outside[1]
