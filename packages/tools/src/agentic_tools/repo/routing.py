"""`RepoTools`: one run's `repo.*` tools as a single `ToolExecutor`, routed by node.

Readers share one read-only `repo` server bound to the run's checkout. Each writer node (one
whose spec names a write tool) has a writable `repo` server bound to its own worktree on
`agent/<run>/<node>`; the worktree itself is created on the node's first call. Every call of a
writer goes to its server, so it reads its own writes and nobody else sees them. Other nodes
calling a write tool get an "unknown tool" error. Each server is bound to one directory, so a
call can never reach another node's worktree.

An orchestrator's workers (6.1) write per task: a writer working on task `t1` of orchestrator
`fix` calls as `fix.t1`, and gets the worktree and branch of that task (`agent/<run>/fix.t1`).
Those writers are only known once the hub has planned, so their servers are opened on first use.

The MCP clients of the writers known up front are opened before the first call, in the task that
will close them (anyio requires it): tool calls may come from other tasks. A task's writer is
opened by one opener task, which also closes it, for the same reason.
"""

import asyncio
import contextlib
import logging
import re
from collections.abc import AsyncGenerator, Awaitable, Callable, Collection, Sequence
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


_TASK_WRITER = re.compile(r"^([a-z][a-z0-9_-]{0,62})\.(?!lock$)[a-z][a-z0-9_-]{0,39}$")
"""A task's writer (6.1): `<orchestrator>.<task>`."""

type _Open = Callable[[Sandbox], Awaitable[McpToolExecutor]]


class _Opener:
    """Opens the writable servers of task writers as they appear, all in its own task, which
    closes them when the run's tools close: an MCP client must be closed by the task that opened
    it."""

    def __init__(self, connect: Callable[[contextlib.AsyncExitStack], _Open]) -> None:
        self._connect = connect
        self._queue: asyncio.Queue[tuple[Worktree, asyncio.Future[McpToolExecutor]] | None] = (
            asyncio.Queue()
        )

    async def open(self, worktree: Worktree) -> McpToolExecutor:
        done: asyncio.Future[McpToolExecutor] = asyncio.get_running_loop().create_future()
        await self._queue.put((worktree, done))
        return await done

    def stop(self) -> None:
        self._queue.put_nowait(None)

    async def serve(self) -> None:
        async with contextlib.AsyncExitStack() as stack:
            while (asked := await self._queue.get()) is not None:
                worktree, done = asked
                try:
                    tools = await self._connect(stack)(worktree)
                except Exception as e:  # reported to the caller
                    done.set_exception(e)
                else:
                    done.set_result(tools)


class RepoTools:
    """Implements `ToolExecutor` for one run. Open it with `open_repo_tools`."""

    def __init__(
        self,
        sandbox: Sandbox,
        run_id: UUID | None,
        base: McpToolExecutor,
        writers: dict[str, _Writer],
        write_definitions: Sequence[ToolDefinition] = (),
        task_writers: Collection[str] = (),
        opener: _Opener | None = None,
    ) -> None:
        self._sandbox = sandbox
        self._run_id = run_id
        self._base = base
        self._writers = writers
        self._task_writers = frozenset(task_writers)
        self._opener = opener
        self._opening = asyncio.Lock()
        self._definitions = list(write_definitions or base.definitions())

    def definitions(self) -> Sequence[ToolDefinition]:
        """The read tools, plus the write tools if the run has writers."""
        return self._definitions

    async def call(
        self, name: str, arguments: dict[str, JsonValue], *, node_id: str | None = None
    ) -> ToolOutput:
        writer = self._writers.get(node_id) if node_id is not None else None
        if writer is None and node_id is not None and self._is_task_writer(node_id):
            try:
                writer = await self._task_writer(node_id)
            except (SandboxError, ValueError) as e:
                return ToolOutput(text=str(e), is_error=True)
        if writer is None:
            return await self._base.call(name, arguments)
        try:
            await self._ready(writer)
        except SandboxError as e:
            return ToolOutput(text=str(e), is_error=True)
        return await writer.tools.call(name, arguments)

    def _is_task_writer(self, node_id: str) -> bool:
        """Whether `node_id` is a task's writer of an orchestrator whose workers write."""
        found = _TASK_WRITER.match(node_id)
        return found is not None and found.group(1) in self._task_writers

    async def _task_writer(self, key: str) -> _Writer:
        """The writer of the task `key`, its server opened on first use."""
        async with self._opening:
            if (writer := self._writers.get(key)) is None:
                assert self._run_id is not None and self._opener is not None
                worktree = Worktree.of(self._sandbox, self._run_id, key)
                writer = _Writer(key, worktree, await self._opener.open(worktree))
                self._writers[key] = writer
            return writer

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
    task_writers: Collection[str] = (),
    limits: RepoLimits | None = None,
) -> AsyncGenerator[RepoTools]:
    """The `repo.*` tools for one run, connected in memory: a read-only `repo` server bound to
    `sandbox`, and for each node in `writers` (which needs `run_id`) a writable one bound to its
    worktree, which is created on the node's first call. Each task of an orchestrator in
    `task_writers` (6.1) gets one too, opened on its first call as `<orchestrator>.<task>`. Every
    client closes on exit, before the caller closes the sandbox."""
    if (writers or task_writers) and run_id is None:
        raise ValueError("writers need the run id, which names their branches")

    def connector(stack: contextlib.AsyncExitStack, writable: bool) -> _Open:
        async def connect(box: Sandbox) -> McpToolExecutor:
            server = build_repo_server(box, writable=writable, limits=limits)
            client = await stack.enter_async_context(Client(server))
            return await McpToolExecutor.connect(client, SERVER_NAME)

        return connect

    async with contextlib.AsyncExitStack() as stack:
        base = await connector(stack, False)(sandbox)
        routed: dict[str, _Writer] = {}
        for node_id in sorted(writers):
            assert run_id is not None
            worktree = Worktree.of(sandbox, run_id, node_id)
            routed[node_id] = _Writer(node_id, worktree, await connector(stack, True)(worktree))
        if not task_writers:
            first = next(iter(routed.values()), None)
            definitions = first.tools.definitions() if first else ()
            yield RepoTools(sandbox, run_id, base, routed, definitions)
            return
        # The write tools' definitions, from a writable server that is never called (its
        # worktree is never created).
        assert run_id is not None
        unused = Worktree.of(sandbox, run_id, "definitions")
        definitions = (await connector(stack, True)(unused)).definitions()
        opener = _Opener(lambda opened: connector(opened, True))
        serving = asyncio.create_task(opener.serve())
        try:
            yield RepoTools(sandbox, run_id, base, routed, definitions, task_writers, opener)
        finally:
            opener.stop()
            try:
                await serving
            except asyncio.CancelledError:
                serving.cancel()
                raise
