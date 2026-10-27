"""`github.openPR`: a writer's branch bundled out of the sandbox (fake and Docker, see conftest),
pushed to a bare repo standing in for GitHub, and a pull request opened on a fake GitHub."""

import os
import subprocess
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import JsonValue

from agentic_github import GithubApiError, InstallationNotFoundError, PullRequestError
from agentic_runtime import ToolOutput
from agentic_sandbox import Sandbox
from agentic_tools.github import GithubTarget, open_github_tools
from agentic_tools.repo import open_repo_tools
from agentic_tools.routing import RunTools
from agentic_tools.testing import FakeGithub, bare_remote

TOKEN = "ghs_servertoken0004"


def git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def remote(repos: Path, tmp_path: Path) -> Path:
    bare_remote(repos / "hello", tmp_path / "remote.git")
    return tmp_path / "remote.git"


@pytest.fixture
def remote_url(remote: Path) -> str:
    return remote.resolve().as_uri()


@pytest.fixture
def github() -> FakeGithub:
    return FakeGithub(TOKEN)


@pytest.fixture
def open_tools(
    sandbox: Sandbox, run_id: UUID, remote_url: str, github: FakeGithub
) -> Callable[[], AbstractAsyncContextManager[RunTools]]:
    """Opens the run's `repo.*` and `github.*` tools; used inside each test, since the MCP
    clients must close in the task that opened them."""

    @asynccontextmanager
    async def open_() -> AsyncGenerator[RunTools]:
        target = GithubTarget(installation_id=42, full_name="acme/hello", remote_url=remote_url)
        async with (
            open_repo_tools(sandbox, run_id=run_id, writers={"writer"}) as repo,
            open_github_tools(github, target, sandbox, run_id=run_id, writers={"writer"}) as gh,
        ):
            yield RunTools([repo, gh])

    return open_


type OpenTools = Callable[[], AbstractAsyncContextManager[RunTools]]


async def write_and_commit(tools: RunTools) -> None:
    calls: list[tuple[str, dict[str, JsonValue]]] = [
        ("repo.write_file", {"path": "NOTES.md", "content": "notes\n"}),
        ("repo.commit", {"message": "Add notes"}),
    ]
    for name, args in calls:
        output = await tools.call(name, args, node_id="writer")
        assert not output.is_error, output.text


async def open_pr(tools: RunTools, **args: JsonValue) -> ToolOutput:
    arguments: dict[str, JsonValue] = {"from_node": "writer", "title": "Add notes", **args}
    return await tools.call("github.openPR", arguments, node_id="publish")


async def test_open_pr_pushes_the_branch_and_opens_a_pull_request(
    open_tools: OpenTools, run_id: UUID, remote: Path, github: FakeGithub
) -> None:
    async with open_tools() as tools:
        await write_and_commit(tools)

        output = await open_pr(tools, body="Please review.")

        branch = f"agent/{run_id}/writer"
        assert not output.is_error, output.text
        assert output.data is not None
        assert output.data["url"] == "https://github.com/acme/hello/pull/1"
        assert output.data["number"] == 1
        assert output.data["head"] == branch
        assert output.data["base"] == "main"  # the branch the run cloned
        assert output.data["commit"] == git(remote, "rev-parse", f"refs/heads/{branch}")
        assert git(remote, "show", f"{branch}:NOTES.md") == "notes"
        assert github.pulls == [
            {
                "repo": "acme/hello",
                "head": branch,
                "base": "main",
                "title": "Add notes",
                "body": "Please review.",
            }
        ]
        assert TOKEN not in output.text


async def test_the_base_can_be_chosen(open_tools: OpenTools, github: FakeGithub) -> None:
    async with open_tools() as tools:
        await write_and_commit(tools)

        output = await open_pr(tools, base="develop")

        assert not output.is_error, output.text
        assert github.pulls[0]["base"] == "develop"


async def test_opening_it_again_pushes_nothing_new(open_tools: OpenTools) -> None:
    async with open_tools() as tools:
        await write_and_commit(tools)
        first = await open_pr(tools)

        again = await open_pr(tools)

        assert not again.is_error, again.text
        assert again.data is not None and first.data is not None
        assert again.data["commit"] == first.data["commit"]


async def test_a_writer_without_commits_has_nothing_to_publish(
    open_tools: OpenTools, github: FakeGithub
) -> None:
    async with open_tools() as tools:
        output = await open_pr(tools)

        assert output.is_error
        assert "nothing to publish" in output.text
        assert github.tokens_issued == 0
        assert github.pulls == []


async def test_only_writers_of_the_run_can_be_published(open_tools: OpenTools) -> None:
    async with open_tools() as tools:
        output = await open_pr(tools, from_node="reader")

        assert output.is_error
        assert "node 'reader' is not a writer of this run" in output.text


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (PullRequestError("GitHub refused the pull request: No commits"), "No commits"),
        (GithubApiError("GitHub returned 502"), "GitHub returned 502"),
        (InstallationNotFoundError(42), "installation is gone"),
    ],
)
async def test_github_errors_are_tool_errors(
    open_tools: OpenTools, github: FakeGithub, error: Exception, message: str
) -> None:
    async with open_tools() as tools:
        await write_and_commit(tools)
        github.refuse = error

        output = await open_pr(tools)

        assert output.is_error
        assert message in output.text


async def test_a_branch_taken_on_the_remote_is_not_overwritten(
    open_tools: OpenTools, run_id: UUID, remote: Path, repos: Path
) -> None:
    branch = f"agent/{run_id}/writer"
    git(remote, "branch", branch, "main")  # another branch of the same name
    async with open_tools() as tools:
        await write_and_commit(tools)

        output = await open_pr(tools)

        assert output.is_error
        assert "already exists" in output.text
        assert git(remote, "rev-parse", branch) == git(repos / "hello", "rev-parse", "HEAD")


async def test_the_tool_offers_an_example_and_strict_arguments(
    sandbox: Sandbox, run_id: UUID, github: FakeGithub
) -> None:
    target = GithubTarget(installation_id=1, full_name="acme/hello")
    async with open_github_tools(github, target, sandbox, run_id=run_id, writers=()) as gh:
        definitions = {d.name: d for d in gh.definitions()}

    assert sorted(definitions) == ["github.createRepo", "github.openPR"]
    definition = definitions["github.openPR"]
    assert definition.input_schema["examples"] == [
        {"from_node": "writer", "title": "Add NOTES.md", "body": "Written by an agent."}
    ]
    assert definition.input_schema["additionalProperties"] is False


async def test_run_tools_route_by_tool_and_refuse_unknown_ones(open_tools: OpenTools) -> None:
    async with open_tools() as tools:
        names = {d.name for d in tools.definitions()}
        unknown = await tools.call("github.mergePR", {}, node_id="publish")

        assert {"github.openPR", "repo.read_file", "repo.commit"} <= names
        assert (unknown.is_error, unknown.text) == (True, "unknown tool: github.mergePR")
