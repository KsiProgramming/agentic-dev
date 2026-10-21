"""The read-only `repo` MCP server over a run's sandbox, and `open_repo_tools`, which connects a
run's agents to it."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from mcp import Client

from agentic_sandbox import Sandbox
from agentic_tools.mcp_bridge import McpToolExecutor
from agentic_tools.repo.paths import repo_relative
from agentic_tools.repo.server import SERVER_NAME, RepoLimits, build_repo_server


@asynccontextmanager
async def open_repo_tools(
    sandbox: Sandbox, *, limits: RepoLimits | None = None
) -> AsyncGenerator[McpToolExecutor]:
    """The `repo.*` tools for one run: a `repo` server bound to `sandbox`, connected in memory.
    The client closes on exit, before the caller closes the sandbox."""
    server = build_repo_server(sandbox, limits=limits)
    async with Client(server) as client:
        yield await McpToolExecutor.connect(client, SERVER_NAME)


__all__ = [
    "SERVER_NAME",
    "RepoLimits",
    "build_repo_server",
    "open_repo_tools",
    "repo_relative",
]
