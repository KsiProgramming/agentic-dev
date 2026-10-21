"""`search` on the `repo` MCP server, on both sandbox backends (see conftest)."""

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
    "README.md": "# Hello repo\nSay Hello to the app.\n",
    "src/app.py": "def main():\n    print('hello')\n",
    "src/pkg/util.py": "def helper():\n    return 'HELLO'\n",
    "assets/blob.bin": "hello\x00binary",
    "long.txt": "hello " + "x" * 400 + "\n",
    "tricky.txt": "'; rm -rf / #\n$(touch pwned)\n",
}


@pytest.fixture
async def repo(manager: SandboxManager, repos: Path) -> AsyncIterator[Sandbox]:
    make_repo(repos / "searcher", FILES)
    async with manager.open(uuid4(), RepoSource(url=str(repos / "searcher"))) as box:
        yield box


@pytest.fixture
def search(repo: Sandbox) -> CallRepo:
    async def _search(limits: RepoLimits | None = None, **arguments: Any) -> tuple[bool, str]:
        return await call_tool(repo, "search", arguments, limits)

    return _search


async def test_finds_a_fixed_string_with_paths_and_line_numbers(search: CallRepo) -> None:
    is_error, text = await search(pattern="def ")

    assert not is_error
    assert sorted(text.splitlines()) == [
        "src/app.py:1: def main():",
        "src/pkg/util.py:1: def helper():",
    ]


async def test_fixed_strings_are_not_regexes(search: CallRepo) -> None:
    assert await search(pattern="def .*\\(") == (False, "no matches for 'def .*\\\\('")


async def test_regex_search(search: CallRepo) -> None:
    _, text = await search(pattern="^def [a-z]+\\(", regex=True)

    assert len(text.splitlines()) == 2


async def test_case_insensitive_search(search: CallRepo) -> None:
    _, sensitive = await search(pattern="hello", path="src")
    _, insensitive = await search(pattern="hello", path="src", case_sensitive=False)

    assert sensitive.splitlines() == ["src/app.py:2:     print('hello')"]
    assert sorted(insensitive.splitlines()) == [
        "src/app.py:2:     print('hello')",
        "src/pkg/util.py:2:     return 'HELLO'",
    ]


async def test_searches_one_file(search: CallRepo) -> None:
    assert await search(pattern="def", path="src/pkg/util.py") == (
        False,
        "src/pkg/util.py:1: def helper():",
    )


async def test_skips_git_metadata_and_binary_files(search: CallRepo) -> None:
    _, text = await search(pattern="hello", case_sensitive=False, max_results=500)

    files = {line.split(":")[0] for line in text.splitlines()}
    assert files == {"README.md", "src/app.py", "src/pkg/util.py", "long.txt"}


async def test_long_lines_are_clipped(search: CallRepo) -> None:
    _, text = await search(pattern="xxx", path="long.txt", limits=None)

    assert text == "long.txt:1: hello " + "x" * 294 + "…"


async def test_results_are_capped(search: CallRepo) -> None:
    _, text = await search(pattern="def", max_results=1)

    lines = text.splitlines()
    assert len(lines) == 2
    assert lines[1] == "(truncated: showing the first 1 matches)"


@pytest.mark.parametrize("pattern", ["'; rm -rf / #", "$(touch pwned)"])
async def test_shell_syntax_in_patterns_is_matched_literally(
    search: CallRepo, repo: Sandbox, pattern: str
) -> None:
    _, text = await search(pattern=pattern)

    assert text.startswith("tricky.txt:")
    probe = await repo.exec(["sh", "-c", "ls pwned /pwned 2>/dev/null; ls README.md"])
    assert probe.stdout.split() == ["README.md"]


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("/etc", "path must stay inside the repository: /etc"),
        ("../..", "path must stay inside the repository"),
        ("missing", "no such path in the repository: missing"),
    ],
)
async def test_refusals(search: CallRepo, path: str, message: str) -> None:
    is_error, text = await search(pattern="root", path=path)

    assert is_error
    assert message in text


@pytest.mark.parametrize(
    "arguments",
    [{}, {"pattern": ""}, {"pattern": "x", "max_results": 501}, {"pattern": "x", "glob": "*"}],
)
async def test_bad_arguments_are_reported(search: CallRepo, arguments: dict[str, Any]) -> None:
    is_error, text = await search(**arguments)

    assert is_error
    assert "validation error" in text


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
async def test_symlinks_out_of_the_repo_are_not_followed(
    manager: SandboxManager, repos: Path
) -> None:
    repo = make_repo(repos / "linked", {"README.md": "root\n"}, links={"etc": "/etc"})

    async with manager.open(uuid4(), RepoSource(url=str(repo))) as box:
        through = await call_tool(box, "search", {"pattern": "root", "path": "etc"})
        everywhere = await call_tool(box, "search", {"pattern": "root"})

    assert through[0] and "inside the repository" in through[1]
    assert everywhere == (False, "README.md:1: root")
