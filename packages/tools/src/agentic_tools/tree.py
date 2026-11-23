"""A writer's committed work as a directory the build and scan tools can run in (13.3).

`archived_tree` resolves a call's `node` through the run's `ReadableWriters` (the same refusals as
13.1's reads), extracts the writer's branch with `git archive` into a directory under the staging
directory, and yields a sandbox whose `workdir` is that directory: every `sh -c` script the tools
already run in the checkout runs there instead, with the same confinement. The directory is removed
afterwards. The checkout and the worktrees are never touched.
"""

import posixpath
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager, suppress
from uuid import uuid4

from mcp.server.mcpserver.exceptions import ToolError

from agentic_runtime import ReadableWriters, WorkRefused, no_commits_text
from agentic_sandbox import (
    BranchNotFoundError,
    ExecResult,
    JobNetwork,
    Sandbox,
    SandboxError,
    archive,
    branch_has_commits,
    branch_patch,
)

# Runs the script `$2` (with `$0` named `$3` and arguments `$4...`) in the directory `$1`.
_IN_TREE = 'dir=$1; script=$2; shift 2; cd -P -- "$dir" || exit 1; exec sh -c "$script" "$@"'


class TreeSandbox:
    """The `Sandbox` for tools, with `workdir` a directory of extracted files. `sh -c` commands
    run there; anything else, and every other member, is the wrapped sandbox's."""

    def __init__(self, inner: Sandbox, directory: str) -> None:
        self._inner = inner
        self._directory = directory

    @property
    def workdir(self) -> str:
        return self._directory

    @property
    def worktrees_dir(self) -> str:
        return self._inner.worktrees_dir

    @property
    def restored(self) -> tuple[str, ...]:
        return self._inner.restored

    @property
    def staging_dir(self) -> str:
        return self._inner.staging_dir

    @property
    def artifacts_dir(self) -> str:
        return self._inner.artifacts_dir

    @property
    def job_networks(self) -> frozenset[JobNetwork]:
        return self._inner.job_networks

    async def exec(
        self, argv: Sequence[str], *, timeout_s: float = 30.0, cwd: str | None = None
    ) -> ExecResult:
        if cwd is not None:
            raise ValueError("cwd is the extracted tree")
        if len(argv) >= 3 and argv[0] == "sh" and argv[1] == "-c":
            argv = ["sh", "-c", _IN_TREE, "in-tree", self._directory, argv[2], *argv[3:]]
        return await self._inner.exec(argv, timeout_s=timeout_s)

    async def put_file(self, data: bytes) -> str:
        return await self._inner.put_file(data)

    async def take_file(self, path: str) -> bytes:
        return await self._inner.take_file(path)

    async def put_artifact(self, name: str, data: bytes) -> str:
        return await self._inner.put_artifact(name, data)

    async def run_job(
        self,
        argv: Sequence[str],
        *,
        network: JobNetwork,
        cwd: str,
        timeout_s: float,
        env: Mapping[str, str] | None = None,
    ) -> ExecResult:
        return await self._inner.run_job(
            argv, network=network, cwd=cwd, timeout_s=timeout_s, env=env
        )


async def branch_of(sandbox: Sandbox, readable: ReadableWriters | None, node: str) -> str:
    """The branch of the writer `node` that completed and committed. Raises `ToolError` with a
    fixed text for any other node."""
    if readable is None:
        raise ToolError(f"'{node}' is not a writer of this run")
    try:
        branch = readable.branch(node)
    except WorkRefused as e:
        raise ToolError(str(e)) from None
    try:
        has_commits = await branch_has_commits(sandbox, branch)
    except SandboxError:
        raise ToolError("could not read the writer's work") from None
    if not has_commits:
        raise ToolError(no_commits_text(node))
    return branch


@asynccontextmanager
async def archived_tree(
    sandbox: Sandbox, readable: ReadableWriters | None, node: str
) -> AsyncGenerator[TreeSandbox]:
    """`node`'s committed tree, extracted for the length of the block."""
    branch = await branch_of(sandbox, readable, node)
    directory = posixpath.join(sandbox.staging_dir, f"tree-{uuid4().hex}")
    try:
        try:
            await archive(sandbox, branch, directory)
        except (BranchNotFoundError, SandboxError):
            raise ToolError("could not read the writer's work") from None
        yield TreeSandbox(sandbox, directory)
    finally:
        with suppress(SandboxError, ValueError):
            await sandbox.exec(["rm", "-rf", "--", directory])


@asynccontextmanager
async def overlaid_tree(
    sandbox: Sandbox,
    readable: ReadableWriters | None,
    node: str,
    pick: Callable[[str], Sequence[str]],
) -> AsyncGenerator[TreeSandbox]:
    """The run's base tree (the commit the run started from) with some of `node`'s files laid
    over it, for the length of the block (13.4). `pick` gets the unified diff of the writer's
    work against the base and returns the repo-relative paths to take from the writer's branch:
    its tests, so a test the change added runs against the code it was written to check."""
    branch = await branch_of(sandbox, readable, node)
    directory = posixpath.join(sandbox.staging_dir, f"base-{uuid4().hex}")
    try:
        try:
            await archive(sandbox, branch, directory, base=True)
            chosen = list(pick(await branch_patch(sandbox, branch)))
            if chosen:
                await archive(sandbox, branch, directory, paths=chosen)
        except (BranchNotFoundError, SandboxError):
            raise ToolError("could not read the writer's work") from None
        yield TreeSandbox(sandbox, directory)
    finally:
        with suppress(SandboxError, ValueError):
            await sandbox.exec(["rm", "-rf", "--", directory])
