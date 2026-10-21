"""`list_files` on the `repo` MCP server, on both sandbox backends (see conftest)."""

import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from agentic_sandbox import RepoSource, SandboxManager
from agentic_sandbox.testing import make_repo
from agentic_tools.repo import RepoLimits, repo_relative
from agentic_tools.testing import CallRepo, call_tool


async def test_lists_the_repo_relative_to_its_root(call: CallRepo) -> None:
    is_error, text = await call("list_files")

    assert not is_error
    assert text.splitlines() == [
        "README.md",
        "docs/",
        "docs/guide.md",
        "src/",
        "src/app.py",
        "src/pkg/",
        "src/pkg/__init__.py",
        "src/pkg/deep/",
    ]


async def test_lists_a_subdirectory_to_a_given_depth(call: CallRepo) -> None:
    _, text = await call("list_files", path="./src/pkg/", max_depth=1)

    assert text.splitlines() == ["src/pkg/__init__.py", "src/pkg/deep/"]


async def test_skips_git_metadata(call: CallRepo) -> None:
    _, text = await call("list_files", max_depth=10)

    assert ".git" not in text
    assert "src/pkg/deep/mod.py" in text.splitlines()


@pytest.mark.parametrize("path", ["/etc", "../..", "src/../../x", "C:/Windows", "\\\\host\\share"])
async def test_paths_outside_the_repo_are_refused(call: CallRepo, path: str) -> None:
    is_error, text = await call("list_files", path=path)

    assert is_error
    assert "inside the repository" in text


@pytest.mark.parametrize("path", ["missing", "README.md"])
async def test_a_path_that_is_not_a_directory_is_an_error(call: CallRepo, path: str) -> None:
    is_error, text = await call("list_files", path=path)

    assert is_error
    assert text.endswith(f"not a directory in the repository: {path}")


async def test_an_option_like_path_is_just_a_missing_directory(call: CallRepo) -> None:
    is_error, text = await call("list_files", path="-delete")

    assert is_error
    assert "not a directory" in text


async def test_long_listings_are_truncated(call: CallRepo) -> None:
    _, text = await call("list_files", RepoLimits(max_entries=2))

    assert text.splitlines() == ["README.md", "docs/", "(truncated: showing 2 of 8 entries)"]


@pytest.mark.parametrize(
    "arguments", [{"max_depth": 0}, {"max_depth": 11}, {"path": 3}, {"recursive": True}]
)
async def test_bad_arguments_are_reported(call: CallRepo, arguments: dict[str, Any]) -> None:
    is_error, text = await call("list_files", **arguments)

    assert is_error
    assert "validation error" in text


async def test_unknown_tools_are_reported(call: CallRepo) -> None:
    assert await call("delete_everything") == (True, "Unknown tool: delete_everything")


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
async def test_a_symlink_out_of_the_repo_is_refused(manager: SandboxManager, repos: Path) -> None:
    repo = make_repo(repos / "linked", {"README.md": "x"}, links={"escape": "/etc"})

    async with manager.open(uuid4(), RepoSource(url=str(repo))) as box:
        is_error, text = await call_tool(box, "list_files", {"path": "escape"})

    assert is_error
    assert "not a directory in the repository" in text


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (".", "."),
        ("", "."),
        ("./src//pkg/", "src/pkg"),
        ("src\\pkg", "src/pkg"),
        ("/etc", None),
        ("D:\\x", None),
        ("a/../b", None),
    ],
)
def test_repo_relative(path: str, expected: str | None) -> None:
    assert repo_relative(path) == expected
