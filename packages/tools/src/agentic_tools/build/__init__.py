"""The `build` tools (13.2): restore a repo's Node and Python packages through a registry's egress
proxy, then build with no network. `build.restore` is for tool nodes only."""

import contextlib
from collections.abc import AsyncGenerator

from mcp import Client

from agentic_runtime import ReadableWriters
from agentic_sandbox import Sandbox
from agentic_tools.build.report import BuildCheck, BuildReport, build_report
from agentic_tools.build.runner import BuildLimits, restore_modules, test_modules
from agentic_tools.build.server import SERVER_NAME, TOOLS, build_build_server
from agentic_tools.build.tests import TestCheck, TestFailure, TestReport
from agentic_tools.mcp_bridge import McpToolExecutor

BUILD_TOOL_NAMES = frozenset(f"{SERVER_NAME}.{tool}" for tool in TOOLS)
"""The platform names of the build tools (`build.restore`, `build.test`)."""


@contextlib.asynccontextmanager
async def open_build_tools(
    sandbox: Sandbox, *, limits: BuildLimits | None = None, readable: ReadableWriters | None = None
) -> AsyncGenerator[McpToolExecutor]:
    """The `build.*` tools over the run's checkout in `sandbox`, connected in memory. The client
    closes on exit."""
    async with Client(build_build_server(sandbox, limits=limits, readable=readable)) as client:
        yield await McpToolExecutor.connect(client, SERVER_NAME)


__all__ = [
    "BUILD_TOOL_NAMES",
    "SERVER_NAME",
    "TOOLS",
    "BuildCheck",
    "BuildLimits",
    "BuildReport",
    "TestCheck",
    "TestFailure",
    "TestReport",
    "build_build_server",
    "build_report",
    "open_build_tools",
    "restore_modules",
    "test_modules",
]
