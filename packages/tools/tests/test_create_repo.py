"""`github.createRepo`: the run's repo created through a fake GitHub, before there is a sandbox."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import JsonValue

from agentic_github import (
    GithubApiError,
    InstallationNotFoundError,
    RepoCreationNotAllowedError,
    RepoInfo,
)
from agentic_runtime import ToolOutput
from agentic_tools.github import GithubTarget, open_github_tools
from agentic_tools.mcp_bridge import McpToolExecutor
from agentic_tools.strict import INTENT_HELP
from agentic_tools.testing import FakeGithub

RUN_CREATED = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
TARGET = GithubTarget(installation_id=42, full_name="acme/docs-new", run_created_at=RUN_CREATED)


@asynccontextmanager
async def no_sandbox(github: FakeGithub) -> AsyncGenerator[McpToolExecutor]:
    async with open_github_tools(github, TARGET, None, run_id=uuid4(), writers=()) as tools:
        yield tools


async def create(tools: McpToolExecutor, **args: JsonValue) -> ToolOutput:
    arguments: dict[str, JsonValue] = {"name": "docs-new", **args}
    return await tools.call("github.createRepo", arguments, node_id="create_repo")


def existing(created_at: datetime) -> RepoInfo:
    return RepoInfo(
        id=7,
        full_name="acme/docs-new",
        name="docs-new",
        owner="acme",
        private=True,
        default_branch="main",
        html_url="https://github.com/acme/docs-new",
        created_at=created_at,
    )


async def test_it_creates_the_runs_repo_with_the_scaffold_asked_for() -> None:
    github = FakeGithub()
    async with no_sandbox(github) as tools:
        output = await create(
            tools, private=False, description="Docs", gitignore="Python", license="mit"
        )

    assert not output.is_error, output.text
    assert output.data == {
        "full_name": "acme/docs-new",
        "url": "https://github.com/acme/docs-new",
        "default_branch": "main",
        "private": False,
        "created": True,
    }
    assert github.created == [
        {
            "repo": "acme/docs-new",
            "private": False,
            "description": "Docs",
            "gitignore": "Python",
            "license": "mit",
        }
    ]


async def test_a_repo_is_private_by_default() -> None:
    github = FakeGithub()
    async with no_sandbox(github) as tools:
        await create(tools)

    assert github.created[0]["private"] is True


async def test_it_creates_only_the_runs_repo() -> None:
    github = FakeGithub()
    async with no_sandbox(github) as tools:
        output = await create(tools, name="other")

    assert output.is_error
    assert "this run creates acme/docs-new" in output.text
    assert github.created == []


async def test_a_retry_takes_over_the_repo_an_earlier_attempt_created() -> None:
    github = FakeGithub()
    github.repos["acme/docs-new"] = existing(RUN_CREATED + timedelta(seconds=5))
    async with no_sandbox(github) as tools:
        output = await create(tools)

    assert not output.is_error, output.text
    assert output.data is not None and output.data["created"] is False


async def test_an_older_repo_of_that_name_is_never_taken_over() -> None:
    github = FakeGithub()
    github.repos["acme/docs-new"] = existing(RUN_CREATED - timedelta(days=1))
    async with no_sandbox(github) as tools:
        output = await create(tools)

    assert output.is_error
    assert "acme/docs-new already exists" in output.text


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (RepoCreationNotAllowedError("GitHub does not let the App create repos in acme"), "acme"),
        (GithubApiError("GitHub returned 502"), "GitHub returned 502"),
        (InstallationNotFoundError(42), "installation is gone"),
    ],
)
async def test_github_errors_are_tool_errors(error: Exception, message: str) -> None:
    github = FakeGithub()
    github.refuse = error
    async with no_sandbox(github) as tools:
        output = await create(tools)

    assert output.is_error
    assert message in output.text


@pytest.mark.parametrize(
    "args",
    [{"gitignore": "Cobol"}, {"license": "gpl-3.0"}, {"name": "bad/name"}, {"owner": "evil"}],
)
async def test_arguments_are_strict(args: dict[str, JsonValue]) -> None:
    github = FakeGithub()
    async with no_sandbox(github) as tools:
        output = await create(tools, **args)

    assert output.is_error
    assert github.created == []


async def test_without_a_sandbox_only_create_repo_is_offered() -> None:
    async with no_sandbox(FakeGithub()) as tools:
        (definition,) = tools.definitions()

    assert definition.name == "github.createRepo"
    assert definition.input_schema["examples"] == [
        {"name": "docs-demo", "private": True, "gitignore": "Python", "license": "mit"}
    ]
    assert definition.input_schema["additionalProperties"] is False
    # Its own `description` is the repo's, so it takes no intent.
    assert INTENT_HELP not in str(definition.input_schema)
