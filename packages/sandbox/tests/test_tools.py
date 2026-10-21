"""`repo.list_files` on both backends: the fake one needs `sh` and GNU/busybox `find` on the
host, the Docker one a daemon. Each is skipped where it cannot run."""

import shutil
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import docker
import pytest
from docker.errors import DockerException
from pydantic import JsonValue

from agentic_runtime import AgentRequest, ClaudeRuntime, ToolCall, ToolResult
from agentic_runtime.testing import MockClaude, collect_and_check, text_reply, tool_use_reply
from agentic_sandbox import FakeSandboxManager, RepoSource, Sandbox, SandboxManager
from agentic_sandbox.docker_backend import DockerSandboxManager
from agentic_sandbox.testing import make_repo
from agentic_sandbox.tools import SandboxTools, repo_relative


def _posix_tools_on_host() -> bool:
    if not (shutil.which("sh") and (find := shutil.which("find"))):
        return False
    probe = subprocess.run([find, ".", "-maxdepth", "0"], capture_output=True, check=False)
    return probe.returncode == 0


def _docker_manager(local_root: Path) -> SandboxManager:
    try:
        client = docker.from_env()
        client.ping()
    except DockerException:
        pytest.skip("no Docker daemon")
    return DockerSandboxManager(client, local_root=local_root)


@pytest.fixture(
    params=[
        pytest.param("fake"),
        pytest.param("docker", marks=pytest.mark.integration),
    ]
)
def manager(request: pytest.FixtureRequest, repos: Path) -> SandboxManager:
    if request.param == "fake":
        if not _posix_tools_on_host():
            pytest.skip("needs sh and a POSIX find on the host")
        return FakeSandboxManager(local_root=repos)
    return _docker_manager(repos)


@pytest.fixture
async def sandbox(manager: SandboxManager, repos: Path) -> AsyncIterator[Sandbox]:
    async with manager.open(uuid4(), RepoSource(url=str(repos / "hello"))) as box:
        yield box


async def test_lists_the_repo_relative_to_its_root(sandbox: Sandbox) -> None:
    output = await SandboxTools(sandbox).call("repo.list_files", {})

    assert not output.is_error
    assert output.text.splitlines() == [
        "README.md",
        "docs/",
        "docs/guide.md",
        "src/",
        "src/app.py",
        "src/pkg/",
        "src/pkg/__init__.py",
        "src/pkg/deep/",
    ]


async def test_lists_a_subdirectory_to_a_given_depth(sandbox: Sandbox) -> None:
    output = await SandboxTools(sandbox).call(
        "repo.list_files", {"path": "./src/pkg/", "max_depth": 1}
    )

    assert output.text.splitlines() == ["src/pkg/__init__.py", "src/pkg/deep/"]


async def test_skips_git_metadata(sandbox: Sandbox) -> None:
    output = await SandboxTools(sandbox).call("repo.list_files", {"max_depth": 10})

    assert ".git" not in output.text
    assert "src/pkg/deep/mod.py" in output.text.splitlines()


@pytest.mark.parametrize("path", ["/etc", "../..", "src/../../x", "C:/Windows", "\\\\host\\share"])
async def test_paths_outside_the_repo_are_refused(sandbox: Sandbox, path: str) -> None:
    output = await SandboxTools(sandbox).call("repo.list_files", {"path": path})

    assert output.is_error
    assert "inside the repository" in output.text


@pytest.mark.parametrize("path", ["missing", "README.md"])
async def test_a_path_that_is_not_a_directory_is_an_error(sandbox: Sandbox, path: str) -> None:
    output = await SandboxTools(sandbox).call("repo.list_files", {"path": path})

    assert output.is_error
    assert output.text == f"not a directory in the repository: {path}"


async def test_an_option_like_path_is_just_a_missing_directory(sandbox: Sandbox) -> None:
    output = await SandboxTools(sandbox).call("repo.list_files", {"path": "-delete"})

    assert output.is_error
    assert "not a directory" in output.text


async def test_long_listings_are_truncated(sandbox: Sandbox) -> None:
    output = await SandboxTools(sandbox, max_entries=2).call("repo.list_files", {})

    assert output.text.splitlines() == [
        "README.md",
        "docs/",
        "(truncated: showing 2 of 8 entries)",
    ]


@pytest.mark.parametrize(
    "arguments", [{"max_depth": 0}, {"max_depth": 11}, {"path": 3}, {"recursive": True}]
)
async def test_bad_arguments_are_reported(
    sandbox: Sandbox, arguments: dict[str, JsonValue]
) -> None:
    output = await SandboxTools(sandbox).call("repo.list_files", arguments)

    assert output.is_error
    assert output.text.startswith("invalid arguments:")


async def test_unknown_tools_are_reported(sandbox: Sandbox) -> None:
    output = await SandboxTools(sandbox).call("repo.delete_everything", {})

    assert (output.is_error, output.text) == (True, "unknown tool: repo.delete_everything")


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
async def test_a_symlink_out_of_the_repo_is_refused(manager: SandboxManager, repos: Path) -> None:
    repo = make_repo(repos / "linked", {"README.md": "x"}, links={"escape": "/etc"})

    async with manager.open(uuid4(), RepoSource(url=str(repo))) as box:
        output = await SandboxTools(box).call("repo.list_files", {"path": "escape"})

    assert output.is_error
    assert "not a directory in the repository" in output.text


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


async def test_claude_lists_files_through_the_sandbox(sandbox: Sandbox) -> None:
    """Done when (1.1), with a scripted Claude: the agent's tool call lists the cloned repo."""
    mock = MockClaude(
        [
            tool_use_reply(("toolu_1", "repo__list_files", {"max_depth": 1})),
            text_reply("The repo has a README, docs and src."),
        ]
    )
    runtime = ClaudeRuntime(mock.client, tools=SandboxTools(sandbox))
    request = AgentRequest(
        node_id="lister",
        role="Explorer",
        instructions="What is in this repo?",
        tools=["repo.list_files"],
    )

    events = await collect_and_check(runtime, request)

    call = next(e for e in events if isinstance(e, ToolCall))
    result = next(e for e in events if isinstance(e, ToolResult))
    assert call.name == "repo.list_files"
    assert result.output.splitlines() == ["README.md", "docs/", "src/"]
    sent_back = mock.requests[1]["messages"][-1]["content"][0]
    assert sent_back["content"] == result.output
    assert mock.requests[0]["tools"][0]["name"] == "repo__list_files"
