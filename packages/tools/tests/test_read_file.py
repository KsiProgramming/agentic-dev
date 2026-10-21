"""`read_file` on the `repo` MCP server, on both sandbox backends (see conftest)."""

import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from agentic_sandbox import RepoSource, Sandbox, SandboxManager
from agentic_sandbox.testing import make_repo
from agentic_tools.repo import RepoLimits
from agentic_tools.testing import CallRepo, call_tool

FILES = {
    "README.md": "# Hello repo\n",
    "notes.txt": "".join(f"line {n}\n" for n in range(1, 11)),
    "src/app.py": "print('hello')\n",
    "assets/logo.png": "\x89PNG\x00\x00binary",
    "-dash.txt": "option-like\n",
    "no-newline.txt": "a\nb",
}


@pytest.fixture
async def repo(manager: SandboxManager, repos: Path) -> AsyncIterator[Sandbox]:
    make_repo(repos / "reader", FILES)
    async with manager.open(uuid4(), RepoSource(url=str(repos / "reader"))) as box:
        yield box


@pytest.fixture
def read(repo: Sandbox) -> CallRepo:
    async def _read(limits: RepoLimits | None = None, **arguments: Any) -> tuple[bool, str]:
        return await call_tool(repo, "read_file", arguments, limits)

    return _read


async def test_reads_numbered_lines(read: CallRepo) -> None:
    assert await read(path="src/app.py") == (False, "1\tprint('hello')")


async def test_reads_a_line_range(read: CallRepo) -> None:
    _, text = await read(path="notes.txt", start_line=3, end_line=5)

    assert text == "3\tline 3\n4\tline 4\n5\tline 5"


async def test_an_end_past_the_file_is_fine(read: CallRepo) -> None:
    _, text = await read(path="notes.txt", start_line=9, end_line=500)

    assert text == "9\tline 9\n10\tline 10"


async def test_a_start_past_the_file_says_how_long_it_is(read: CallRepo) -> None:
    assert await read(path="notes.txt", start_line=20) == (
        False,
        "(no lines from line 20: the file has 10 lines)",
    )


async def test_a_last_line_without_newline_is_read(read: CallRepo) -> None:
    assert await read(path="no-newline.txt") == (False, "1\ta\n2\tb")


async def test_an_option_like_name_is_just_a_file(read: CallRepo) -> None:
    assert await read(path="-dash.txt") == (False, "1\toption-like")


async def test_long_files_are_cut_at_the_line_cap(read: CallRepo) -> None:
    _, text = await read(RepoLimits(max_lines=3), path="notes.txt", start_line=2)

    assert text.splitlines() == [
        "2\tline 2",
        "3\tline 3",
        "4\tline 4",
        "(truncated: showing lines 2-4 of 10; call again with start_line=5 for more)",
    ]


async def test_long_files_are_cut_at_the_byte_cap(read: CallRepo) -> None:
    _, text = await read(RepoLimits(max_bytes=20), path="notes.txt")

    assert text.splitlines() == [
        "1\tline 1",
        "2\tline 2",
        "(truncated: showing lines 1-2 of 10; call again with start_line=3 for more)",
    ]


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("src", "not a file: src"),
        ("missing.txt", "no such path in the repository: missing.txt"),
        ("assets/logo.png", "binary file, not shown: assets/logo.png"),
        ("/etc/passwd", "path must stay inside the repository: /etc/passwd"),
        ("../reader/README.md", "path must stay inside the repository"),
        ("C:/Windows/win.ini", "path must stay inside the repository"),
    ],
)
async def test_refusals(read: CallRepo, path: str, message: str) -> None:
    is_error, text = await read(path=path)

    assert is_error
    assert message in text
    assert str(Path.cwd()) not in text


@pytest.mark.parametrize(
    "arguments",
    [{}, {"path": "README.md", "start_line": 0}, {"path": "README.md", "lines": 3}],
)
async def test_bad_arguments_are_reported(read: CallRepo, arguments: dict[str, Any]) -> None:
    is_error, text = await read(**arguments)

    assert is_error
    assert "validation error" in text


async def test_an_end_before_the_start_is_reported(read: CallRepo) -> None:
    assert await read(path="notes.txt", start_line=5, end_line=4) == (
        True,
        "Error executing tool read_file: end_line must not be before start_line",
    )


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
async def test_symlinks_out_of_the_repo_are_refused(manager: SandboxManager, repos: Path) -> None:
    repo = make_repo(
        repos / "linked",
        {"README.md": "x\n", "docs/real.md": "real\n"},
        links={"passwd": "/etc/passwd", "etc": "/etc", "inside.md": "docs/real.md"},
    )

    async with manager.open(uuid4(), RepoSource(url=str(repo))) as box:
        to_file = await call_tool(box, "read_file", {"path": "passwd"})
        via_dir = await call_tool(box, "read_file", {"path": "etc/passwd"})
        inside = await call_tool(box, "read_file", {"path": "inside.md"})

    assert to_file[0] and "inside the repository" in to_file[1]
    assert via_dir[0] and "inside the repository" in via_dir[1]
    assert inside == (False, "1\treal")
