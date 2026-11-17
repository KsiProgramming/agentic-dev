"""The `jira` MCP server over one workspace's Jira (7.2), `open_jira_tools`, which connects a
run to it, and `read_issue`, the same issue read for the worker's issue brief (7.4)."""

import contextlib
from collections.abc import AsyncGenerator
from uuid import UUID

from mcp import Client

from agentic_tools.jira.server import (
    MAX_COMMENT_CHARS,
    MAX_DESCRIPTION_CHARS,
    MAX_POST_CHARS,
    MAX_SEARCH_RESULTS,
    READ_TOOLS,
    SERVER_NAME,
    WRITE_TOOLS,
    IssueOut,
    IssueReadError,
    JiraAccess,
    MappedOut,
    balanced,
    build_jira_server,
    read_issue,
    tool_names,
)
from agentic_tools.mcp_bridge import McpToolExecutor

JIRA_READ_TOOL_NAMES = tool_names(sorted(READ_TOOLS))
"""`jira.getIssue`, `jira.search`, `jira.listTransitions`: any agent may be granted them."""

JIRA_WRITE_TOOL_NAMES = tool_names(sorted(WRITE_TOOLS))
"""`jira.comment`, `jira.transition`: only a tool node after a gate calls them."""


@contextlib.asynccontextmanager
async def open_jira_tools(
    access: JiraAccess, *, run_id: UUID, run_url: str | None = None
) -> AsyncGenerator[McpToolExecutor]:
    """The `jira.*` tools for one run, connected in memory. The client closes on exit."""
    async with Client(build_jira_server(access, run_id=run_id, run_url=run_url)) as client:
        yield await McpToolExecutor.connect(client, SERVER_NAME)


__all__ = [
    "JIRA_READ_TOOL_NAMES",
    "JIRA_WRITE_TOOL_NAMES",
    "MAX_COMMENT_CHARS",
    "MAX_DESCRIPTION_CHARS",
    "MAX_POST_CHARS",
    "MAX_SEARCH_RESULTS",
    "READ_TOOLS",
    "SERVER_NAME",
    "WRITE_TOOLS",
    "IssueOut",
    "IssueReadError",
    "JiraAccess",
    "MappedOut",
    "balanced",
    "build_jira_server",
    "open_jira_tools",
    "read_issue",
]
