"""The `artifacts` MCP server over one run's artifacts, and `open_artifact_tools`, which connects
a run's agents to it."""

import contextlib
from collections.abc import AsyncGenerator

from mcp import Client

from agentic_tools.artifacts.server import (
    MAX_READ_CHARS,
    SERVER_NAME,
    TOOLS,
    ArtifactReader,
    build_artifacts_server,
)
from agentic_tools.mcp_bridge import McpToolExecutor

ARTIFACT_TOOL_NAMES = frozenset(f"{SERVER_NAME}.{tool}" for tool in TOOLS)
"""The platform names of the artifact tools (`artifacts.list`, `artifacts.read`)."""


@contextlib.asynccontextmanager
async def open_artifact_tools(
    store: ArtifactReader, *, mirror_dir: str | None = None
) -> AsyncGenerator[McpToolExecutor]:
    """The `artifacts.*` tools for one run, connected in memory. The client closes on exit."""
    async with Client(build_artifacts_server(store, mirror_dir=mirror_dir)) as client:
        yield await McpToolExecutor.connect(client, SERVER_NAME)


__all__ = [
    "ARTIFACT_TOOL_NAMES",
    "MAX_READ_CHARS",
    "SERVER_NAME",
    "TOOLS",
    "ArtifactReader",
    "build_artifacts_server",
    "open_artifact_tools",
]
