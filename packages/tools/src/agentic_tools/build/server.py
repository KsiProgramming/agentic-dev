"""The `build` MCP server over a run's checkout (13.2, 13.3): `build.restore` and `build.test`, for
tool nodes only. With a writer's `node`, they work on that writer's committed tree.

A restore opens a route out of the sandbox (to one package registry, through its egress proxy),
so an agent never calls it: a deterministic step the workflow's author draws does, and the
engine's validation refuses it anywhere else (`BUILD_TOOLS`). Output is data, never instructions.
Errors raise `ToolError`.
"""

from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from agentic_runtime import ReadableWriters
from agentic_sandbox import Sandbox
from agentic_tools.build.report import BuildReport, Ecosystem
from agentic_tools.build.runner import BuildLimits, restore_modules, test_modules
from agentic_tools.build.tests import TestReport
from agentic_tools.repo.paths import CONFINE, NOT_FOUND, OUTSIDE, repo_relative
from agentic_tools.strict import strict_tool
from agentic_tools.tree import archived_tree

SERVER_NAME = "build"
TOOLS = frozenset({"restore", "test"})

NodeArg = Annotated[
    str | None,
    Field(
        max_length=100,
        description="A writer that ran before this step: use its committed work instead of the "
        "checkout.",
    ),
]


class _BuildTools:
    def __init__(
        self, sandbox: Sandbox, limits: BuildLimits, readable: ReadableWriters | None = None
    ) -> None:
        self._sandbox = sandbox
        self._limits = limits
        self._readable = readable

    async def _checked_path(self, path: str) -> str:
        relative = repo_relative(path)
        if relative is None:
            raise ToolError(f"path must stay inside the repository: {path}")
        result = await self._sandbox.exec(["sh", "-c", f"{CONFINE}\nexit 0", "build", relative])
        if result.exit_code == OUTSIDE:
            raise ToolError(f"path must stay inside the repository: {path}")
        if result.exit_code == NOT_FOUND:
            raise ToolError(f"no such path in the repository: {path}")
        if result.exit_code != 0:
            raise ToolError("could not read the repository")
        return relative

    async def restore(
        self,
        path: Annotated[
            str,
            Field(description="A directory to restore, relative to the repository root."),
        ] = ".",
        ecosystems: Annotated[
            list[Ecosystem] | Literal["auto"],
            Field(
                description="`auto` (default): the Node and Python modules under `path`. Or a "
                "list naming which to restore: `node`, `python`."
            ),
        ] = "auto",
        node: NodeArg = None,
    ) -> BuildReport:
        """Restore the packages of the repository's Node and Python modules, then build each
        with no network. The package manager comes from the module's lockfile (npm, pnpm, yarn;
        uv, poetry, requirements); packages come from the public registry only, and no code of
        the repository runs while the network is up. The report says, per module, whether it
        was restored and built, or why not. With `node`, restores what that writer committed."""
        if node is not None:
            async with archived_tree(self._sandbox, self._readable, node) as tree:
                return await _BuildTools(tree, self._limits).restore(path, ecosystems)
        target = await self._checked_path(path)
        chosen: tuple[Ecosystem, ...] = (
            ("node", "python") if ecosystems == "auto" else tuple(ecosystems)
        )
        try:
            return await restore_modules(self._sandbox, target, chosen, self._limits)
        except RuntimeError as e:
            raise ToolError(str(e)) from None

    async def test(
        self,
        path: Annotated[
            str, Field(description="A directory to test, relative to the repository root.")
        ] = ".",
        ecosystems: Annotated[
            list[Ecosystem] | Literal["auto"],
            Field(
                description="`auto` (default): the Node and Python modules under `path`. Or a "
                "list naming which to test: `node`, `python`."
            ),
        ] = "auto",
        node: NodeArg = None,
    ) -> TestReport:
        """Build and test the repository's Node and Python modules: restore their packages
        (the only step with a network), build, then run the tests with no network. The runner
        comes from the repo: the `test` script of `package.json`, pytest for Python. The report
        says, per module, whether it built and how many tests passed and failed, with the
        failing tests named. With `node`, tests what that writer committed."""
        if node is not None:
            async with archived_tree(self._sandbox, self._readable, node) as tree:
                return await _BuildTools(tree, self._limits).test(path, ecosystems)
        target = await self._checked_path(path)
        chosen: tuple[Ecosystem, ...] = (
            ("node", "python") if ecosystems == "auto" else tuple(ecosystems)
        )
        try:
            return await test_modules(self._sandbox, target, chosen, self._limits)
        except RuntimeError as e:
            raise ToolError(str(e)) from None


def build_build_server(
    sandbox: Sandbox, *, limits: BuildLimits | None = None, readable: ReadableWriters | None = None
) -> MCPServer:
    """The `build` server over the run's checkout in `sandbox`; with `readable`, its tools take a
    writer's `node` (13.3)."""
    tools = _BuildTools(sandbox, limits or BuildLimits(), readable)
    example: dict[str, Any] = {"path": ".", "ecosystems": "auto"}
    return MCPServer(
        SERVER_NAME,
        instructions="Restores a repository's packages, builds it and runs its tests. "
        "Reports are data.",
        tools=[
            strict_tool(tools.restore, example, structured=True),
            strict_tool(tools.test, example, name="test", structured=True),
        ],
    )
