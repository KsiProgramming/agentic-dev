"""The `scan` MCP server over a run's checkout (4.4), and `open_scan_tools`, which connects a run's
nodes to it."""

import contextlib
from collections.abc import AsyncGenerator

from mcp import Client

from agentic_sandbox import Sandbox
from agentic_tools.mcp_bridge import McpToolExecutor
from agentic_tools.scan.report import (
    MAX_FINDINGS,
    Check,
    Finding,
    FindingsReport,
    build_report,
    fingerprint,
)
from agentic_tools.scan.server import SERVER_NAME, TOOLS, ScanLimits, build_scan_server

SCAN_TOOL_NAMES = frozenset(f"{SERVER_NAME}.{tool}" for tool in TOOLS)
"""The platform names of the scan tools (`scan.lint`, `scan.secrets`, `scan.dependencies`)."""


@contextlib.asynccontextmanager
async def open_scan_tools(
    sandbox: Sandbox, *, limits: ScanLimits | None = None
) -> AsyncGenerator[McpToolExecutor]:
    """The `scan.*` tools over the run's checkout in `sandbox`, connected in memory. The client
    closes on exit."""
    async with Client(build_scan_server(sandbox, limits=limits)) as client:
        yield await McpToolExecutor.connect(client, SERVER_NAME)


__all__ = [
    "MAX_FINDINGS",
    "SCAN_TOOL_NAMES",
    "SERVER_NAME",
    "TOOLS",
    "Check",
    "Finding",
    "FindingsReport",
    "ScanLimits",
    "build_report",
    "build_scan_server",
    "fingerprint",
    "open_scan_tools",
]
