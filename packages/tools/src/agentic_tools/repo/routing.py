"""`RepoTools`: one run's `repo.*` tools as a single `ToolExecutor`, routed by node.

Readers share one read-only `repo` server bound to the run's checkout. Each writer node (one
whose spec names a write tool) has a writable `repo` server bound to its own worktree on
`agent/<run>/<node>`; the worktree itself is created on the node's first call. Every call of a
writer goes to its server, so it reads its own writes and nobody else sees them. Other nodes
calling a write tool get an "unknown tool" error. Each server is bound to one directory, so a
call can never reach another node's worktree.

The MCP clients are all opened up front, in the task that will close them (anyio requires it):
tool calls may come from other tasks.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator, Collection, Sequence
from contextlib import asynccontextmanager
from uuid import UUID

from mcp import Client
from pydantic import JsonValue

from agentic_runtime.tools import ToolDefinition, ToolOutput
from agentic_sandbox import Sandbox, SandboxError, Worktree, add_worktree
from agentic_tools.mcp_bridge import McpToolExecutor
from agentic_tools.repo.server import SERVER_NAME, RepoLimits, build_repo_server

log = logging.getLogger("agentic_tools.repo")


class _Writer:
    def __init__(self, node_id: str, worktree: Worktree, tools: McpToolExecutor) -> None:
        self.node_id = node_id
        self.worktree = worktree
        self.tools = tools
        self.ready = False
        self.lock = asyncio.Lock()


class RepoTools:
    """Implements `ToolExecutor` for one run. Open it with `open_repo_tools`."""

    def __init__(
        self,
        sandbox: Sandbox,
        run_id: UUID | None,
        base: McpToolExecutor,
        writers: dict[str, _Writer],
    ) -> None:
        self._sandbox = sandbox
        self._run_id = run_id
        self._base = base
        self._writers = writers
        first = next(iter(writers.values()), None)
        self._definitions = list((first.tools if first else base).definitions())

    def definitions(self) -> Sequence[ToolDefinition]:
        """The read tools, plus the write tools if the run has writers."""
        return self._definitions

    async def call(
        self, name: str, arguments: dict[str, JsonValue], *, node_id: str | None = None
    ) -> ToolOutput:
        writer = self._writers.get(node_id) if node_id is not None else None
        if writer is None:
            return await self._base.call(name, arguments)
        try:
            await self._ready(writer)
        except SandboxError as e:
            return ToolOutput(text=str(e), is_error=True)
        return await writer.tools.call(name, arguments)

    async def _ready(self, writer: _Writer) -> None:
        """Create the writer's worktree, once."""
        async with writer.lock:
            if not writer.ready:
                assert self._run_id is not None  # `open_repo_tools` requires it with writers
                await add_worktree(self._sandbox, self._run_id, writer.node_id)
                writer.ready = True
                log.info("node %s writes on %s", writer.node_id, writer.worktree.branch)


@asynccontextmanager
async def open_repo_tools(
    sandbox: Sandbox,
    *,
    run_id: UUID | None = None,
    writers: Collection[str] = (),
    limits: RepoLimits | None = None,
) -> AsyncGenerator[RepoTools]:
    """The `repo.*` tools for one run, connected in memory: a read-only `repo` server bound to
    `sandbox`, and for each node in `writers` (which needs `run_id`) a writable one bound to its
    worktree, which is created on the node's first call. Every client closes on exit, before the
    caller closes the sandbox."""
    if writers and run_id is None:
        raise ValueError("writers need the run id, which names their branches")
    async with contextlib.AsyncExitStack() as stack:

        async def connect(box: Sandbox, writable: bool) -> McpToolExecutor:
            server = build_repo_server(box, writable=writable, limits=limits)
            client = await stack.enter_async_context(Client(server))
            return await McpToolExecutor.connect(client, SERVER_NAME)

        base = await connect(sandbox, False)
        routed: dict[str, _Writer] = {}
        for node_id in sorted(writers):
            assert run_id is not None
            worktree = Worktree.of(sandbox, run_id, node_id)
            routed[node_id] = _Writer(node_id, worktree, await connect(worktree, True))
        yield RepoTools(sandbox, run_id, base, routed)
