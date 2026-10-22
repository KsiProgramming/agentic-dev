"""The `github` MCP server over a run's sandbox and its repo on GitHub, and `open_github_tools`,
which connects a run to it."""

import contextlib
from collections.abc import AsyncGenerator, Collection
from uuid import UUID

from mcp import Client

from agentic_github import push_bundle
from agentic_sandbox import Sandbox
from agentic_tools.github.server import (
    PUBLISH_TOOLS,
    SERVER_NAME,
    GithubPublisher,
    GithubTarget,
    PullRequestOut,
    PushBranch,
    build_github_server,
)
from agentic_tools.mcp_bridge import McpToolExecutor

PUBLISH_TOOL_NAMES = frozenset(f"{SERVER_NAME}.{tool}" for tool in PUBLISH_TOOLS)
"""The platform names of the publishing tools (`github.openPR`)."""


@contextlib.asynccontextmanager
async def open_github_tools(
    github: GithubPublisher,
    target: GithubTarget,
    sandbox: Sandbox,
    *,
    run_id: UUID,
    writers: Collection[str],
    push: PushBranch = push_bundle,
) -> AsyncGenerator[McpToolExecutor]:
    """The `github.*` tools for one run, connected in memory. The client closes on exit, before
    the caller closes the sandbox."""
    server = build_github_server(github, target, sandbox, run_id=run_id, writers=writers, push=push)
    async with Client(server) as client:
        yield await McpToolExecutor.connect(client, SERVER_NAME)


__all__ = [
    "PUBLISH_TOOLS",
    "PUBLISH_TOOL_NAMES",
    "SERVER_NAME",
    "GithubPublisher",
    "GithubTarget",
    "PullRequestOut",
    "PushBranch",
    "build_github_server",
    "open_github_tools",
]
