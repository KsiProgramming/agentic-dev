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
from agentic_sandbox import Sandbox, SandboxError, branch_patch
from agentic_tools.build.changed import is_test_path, parse_patch, source_changes
from agentic_tools.build.report import BuildReport, Ecosystem
from agentic_tools.build.runner import BuildLimits, restore_modules, test_modules
from agentic_tools.build.tests import (
    TestEcosystem,
    TestOptions,
    TestReport,
    is_criterion_id,
)
from agentic_tools.repo.paths import CONFINE, NOT_FOUND, OUTSIDE, repo_relative
from agentic_tools.strict import strict_tool
from agentic_tools.tree import archived_tree, branch_of, overlaid_tree

MAX_SELECT = 100

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
            list[TestEcosystem] | Literal["auto"],
            Field(
                description="`auto` (default): the Node and Python modules and the C# projects "
                "under `path`. Or a list naming which to test: `node`, `python`, `dotnet`."
            ),
        ] = "auto",
        node: NodeArg = None,
        select: Annotated[
            list[str] | None,
            Field(
                max_length=MAX_SELECT,
                description="Criterion ids such as `AC-001`: also report each test whose name "
                "holds one of them (`cases`: name, file, status and ids).",
            ),
        ] = None,
        coverage: Annotated[
            bool,
            Field(
                description="Also measure the coverage of the lines the writer's work changed "
                "against the run's base (needs `node`; Python and C# only)."
            ),
        ] = False,
        on: Annotated[
            Literal["change", "base"],
            Field(
                description="`change` (default): the writer's tree. `base`: the run's base tree "
                "with the writer's test files laid over it, running only the tests `select` "
                "names (needs `node` and `select`)."
            ),
        ] = "change",
    ) -> TestReport:
        """Build and test the repository's Node and Python modules and C# projects: restore their
        packages (the only step with a network), build, then run the tests with no network. The
        runner comes from the repo: the `test` script of `package.json`, pytest for Python,
        `dotnet test` for C#. The report
        says, per module, whether it built and how many tests passed and failed, with the
        failing tests named. With `node`, tests what that writer committed. `select`, `coverage`
        and `on` add the per-criterion results and the coverage of changed lines."""
        ids = tuple(dict.fromkeys(select or ()))
        if any(not is_criterion_id(i) for i in ids):
            raise ToolError("select takes criterion ids such as AC-001")
        if (coverage or on == "base") and node is None:
            raise ToolError("coverage and on: base need a node: the writer whose work is checked")
        if on == "base" and (coverage or not ids):
            raise ToolError("on: base runs the tests that select names, and measures no coverage")
        if node is None:
            return await self._run_tests(path, ecosystems, TestOptions(select=ids))
        if on == "base":
            async with overlaid_tree(
                self._sandbox,
                self._readable,
                node,
                lambda patch: [f for f in parse_patch(patch) if is_test_path(f)],
            ) as tree:
                options = TestOptions(select=ids, base=True)
                return await _BuildTools(tree, self._limits)._run_tests(path, ecosystems, options)
        changes: dict[str, set[int]] = {}
        if coverage:
            branch = await branch_of(self._sandbox, self._readable, node)
            try:
                patch = await branch_patch(self._sandbox, branch)
            except SandboxError:
                raise ToolError("could not read the writer's work") from None
            changes = source_changes(patch, repo_relative(path) or ".")
        options = TestOptions(select=ids, coverage=coverage, changes=changes)
        async with archived_tree(self._sandbox, self._readable, node) as tree:
            return await _BuildTools(tree, self._limits)._run_tests(path, ecosystems, options)

    async def _run_tests(
        self,
        path: str,
        ecosystems: list[TestEcosystem] | Literal["auto"],
        options: TestOptions,
    ) -> TestReport:
        target = await self._checked_path(path)
        chosen: tuple[TestEcosystem, ...] = (
            ("node", "python", "dotnet") if ecosystems == "auto" else tuple(ecosystems)
        )
        try:
            return await test_modules(self._sandbox, target, chosen, self._limits, options)
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
