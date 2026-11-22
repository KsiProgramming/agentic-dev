"""A runtime per provider for one run (8.3).

A run's agents may run on different providers (a node, the workflow, the workspace or the person
who started the run chose, `agentic_engine.providers`), so the worker hands the engine one runtime
that sends each request to the runtime of `request.provider`. Each provider's runtime is opened
on its first request and closed when the attempt ends: a run that never asks for Copilot never
reads a personal token, and one that never asks for Claude never decrypts the workspace's key.

A provider that cannot be opened (no key, a connection that needs attention) fails the agent that
asked, with the setup error's message, which is safe to show: it never holds a secret."""

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, AsyncExitStack

from agentic_engine.providers import ResolvedProviders, resolve_providers
from agentic_runtime import (
    AgentEvent,
    AgentRequest,
    AgentRun,
    AgentRuntime,
    Cancelled,
    Failed,
    Provider,
    ToolExecutor,
)
from agentic_store import StoredRun
from agentic_worker.errors import RunSetupError

type Opener = Callable[[], AbstractAsyncContextManager[AgentRuntime]]
"""Opens one provider's runtime, for as long as the context lasts."""


type RoutedRuntimes = Callable[
    [StoredRun, ToolExecutor | None], AbstractAsyncContextManager["ProviderRouter"]
]
"""Opens a run's `ProviderRouter` for as long as its attempt lasts."""


def run_providers(run: StoredRun) -> ResolvedProviders:
    """The provider and model of each agent of `run`, as they were resolved when it was created.
    A run from before 8.3 has none stored: it resolves from the provider it was started on, and
    one with only a personal connection (8.2) runs on Copilot."""
    if run.resolved is not None:
        return run.resolved
    asked: Provider = "copilot" if run.copilot_connection_id is not None else run.provider
    return resolve_providers(run.spec, run_override=asked)


class ProviderRouter:
    """An `AgentRuntime` over one runtime per provider, each opened on its first request."""

    def __init__(self, openers: Mapping[Provider, Opener], stack: AsyncExitStack) -> None:
        self._openers = openers
        self._stack = stack
        self._runtimes: dict[Provider, AgentRuntime] = {}
        self._locks: dict[Provider, asyncio.Lock] = {}

    @property
    def opened(self) -> list[Provider]:
        """The providers opened so far, in the order they were first asked for."""
        return list(self._runtimes)

    async def runtime(self, provider: Provider) -> AgentRuntime:
        """The runtime of `provider`, opened now if it is the first request for it. Raises
        `RunSetupError` when it cannot be opened."""
        lock = self._locks.setdefault(provider, asyncio.Lock())
        async with lock:
            if (found := self._runtimes.get(provider)) is not None:
                return found
            opened = await self._stack.enter_async_context(self._openers[provider]())
            self._runtimes[provider] = opened
            return opened

    def start(self, request: AgentRequest) -> AgentRun:
        return _Routed(self, request)


class _Routed:
    """An `AgentRun` that opens its provider's runtime when it is first iterated."""

    def __init__(self, router: ProviderRouter, request: AgentRequest) -> None:
        self._router = router
        self._request = request
        self._inner: AgentRun | None = None
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        if self._inner is not None:
            self._inner.cancel()

    def __aiter__(self) -> AsyncIterator[AgentEvent]:
        return self._events()

    async def _events(self) -> AsyncIterator[AgentEvent]:
        try:
            runtime = await self._router.runtime(self._request.provider)
        except RunSetupError as e:
            yield Cancelled() if self._cancelled else Failed(error=str(e))
            return
        if self._cancelled:
            yield Cancelled()
            return
        self._inner = runtime.start(self._request)
        async for event in self._inner:
            yield event
