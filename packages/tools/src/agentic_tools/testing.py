"""Test helpers shared by the tools and worker test suites."""

from collections.abc import Awaitable, Callable
from typing import Any

from mcp import Client

from agentic_sandbox import Sandbox
from agentic_tools.repo import RepoLimits, build_repo_server

CallRepo = Callable[..., Awaitable[tuple[bool, str]]]
"""`await call(tool, limits=None, **arguments)` -> (is_error, text)."""


async def call_tool(
    sandbox: Sandbox,
    tool: str,
    arguments: dict[str, Any],
    limits: RepoLimits | None = None,
    *,
    writable: bool = False,
) -> tuple[bool, str]:
    """Call one `repo` tool through a fresh in-memory MCP client; returns (is_error, text). With
    `writable`, `sandbox` must be a worktree."""
    server = build_repo_server(sandbox, writable=writable, limits=limits)
    async with Client(server) as client:
        result = await client.call_tool(tool, arguments)
    text = "\n".join(c.text for c in result.content if c.type == "text")
    return result.is_error, text
