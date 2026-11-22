"""A run on a person's Copilot (8.2): which token it uses and how its runtime is built.

A run started with a personal GitHub connection (`runs.copilot_connection_id`) runs every agent
on that person's Copilot subscription. The token is read for that one connection, never the
company App's and never another person's, held for the run's attempt (redacted from logs while
it is) and handed only to the SDK's client. The token is refreshed first when it is about to
expire; a grant GitHub no longer accepts fails the run with a fixed code before any agent runs.

`AGENTIC_RUNTIME=fake` (the dev and e2e stack) still reads the token, so a missing or broken
connection fails there as it would for real, then runs the stack's fake agents."""

from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_github import GithubApiError, GithubUserAuth, user_access_token
from agentic_runtime import (
    AgentEvent,
    AgentRequest,
    AgentRun,
    AgentRuntime,
    CopilotRuntime,
    Failed,
    ToolExecutor,
)
from agentic_secrets import KeyProvider, SecretDecryptError, registered
from agentic_store import (
    GithubUserNeedsAttentionError,
    GithubUserNotConnectedError,
    ProviderSettings,
    StoredRun,
)
from agentic_worker.errors import RunSetupError

TokenLoader = Callable[[StoredRun], Awaitable[SecretStr]]
"""The access token of the run's personal GitHub connection."""

type RunRuntimes = Callable[
    [StoredRun, ToolExecutor | None], AbstractAsyncContextManager[AgentRuntime]
]


class CopilotSettings(Protocol):
    """What the worker's settings say about Copilot."""

    @property
    def copilot_model(self) -> str: ...

    @property
    def runtime(self) -> str: ...


def token_loader(
    sessions: async_sessionmaker[AsyncSession], keys: KeyProvider, auth: GithubUserAuth | None
) -> TokenLoader:
    """Reads the run's connection's token (refreshed if it is about to expire), its failures as
    `RunSetupError`s with a fixed code that is safe to show."""

    async def load(run: StoredRun) -> SecretStr:
        connection_id = run.copilot_connection_id
        assert connection_id is not None
        who = run.copilot_login or "the person"
        if auth is None:
            raise RunSetupError(
                "copilot_not_configured: this worker has no GitHub OAuth app for personal "
                "connections (set GITHUB_USER_CLIENT_ID and GITHUB_USER_CLIENT_SECRET_FILE)"
            )
        try:
            return await user_access_token(sessions, keys, auth, run.workspace_id, connection_id)
        except GithubUserNotConnectedError:
            raise RunSetupError(
                f"copilot_not_connected: {who}'s GitHub connection was removed; connect it "
                "again in Settings > Integrations and rerun"
            ) from None
        except GithubUserNeedsAttentionError as e:
            raise RunSetupError(
                f"copilot_needs_attention: {who}'s GitHub connection needs attention "
                f"({e.reason}); connect it again in Settings > Integrations and rerun"
            ) from None
        except SecretDecryptError:
            raise RunSetupError(
                f"copilot_not_connected: {who}'s GitHub token cannot be decrypted; connect it again"
            ) from None
        except GithubApiError:
            raise RunSetupError(
                "copilot_unavailable: GitHub could not be reached to renew the token"
            ) from None

    return load


type Refused = Callable[[StoredRun], Awaitable[None]]
"""Called when GitHub refused the run's token mid-run."""

REFUSED_CODE = "copilot_needs_attention"


class _Watched:
    """An `AgentRun` that tells `on_refused` once if the run fails because GitHub refused the
    token, then passes every event on unchanged."""

    def __init__(self, inner: AgentRun, run: StoredRun, on_refused: Refused) -> None:
        self._inner = inner
        self._run = run
        self._on_refused = on_refused

    def cancel(self) -> None:
        self._inner.cancel()

    def __aiter__(self) -> AsyncIterator[AgentEvent]:
        return self._events()

    async def _events(self) -> AsyncIterator[AgentEvent]:
        async for event in self._inner:
            if isinstance(event, Failed) and event.error.startswith(f"{REFUSED_CODE}:"):
                await self._on_refused(self._run)
            yield event


class _Watching:
    """An `AgentRuntime` whose runs mark their person's connection as needing attention when
    GitHub refuses the token (a revoked grant, a token that expired inside a long run)."""

    def __init__(self, inner: AgentRuntime, run: StoredRun, on_refused: Refused) -> None:
        self._inner = inner
        self._run = run
        self._on_refused = on_refused

    def start(self, request: AgentRequest) -> AgentRun:
        return _Watched(self._inner.start(request), self._run, self._on_refused)


type WorkspaceSettings = Callable[[StoredRun], Awaitable[ProviderSettings]]
"""The provider settings of the run's workspace (8.3)."""


async def no_workspace_settings(run: StoredRun) -> ProviderSettings:
    return ProviderSettings()


def copilot_runtimes(
    settings: CopilotSettings,
    load_token: TokenLoader,
    fake: RunRuntimes,
    on_refused: Refused | None = None,
    workspace: WorkspaceSettings = no_workspace_settings,
) -> RunRuntimes:
    """Opens the Copilot runtime of a run that has a personal GitHub connection (8.2) for the
    agents that run on it (8.3). On the fake stack (`settings.runtime != "claude"`) that is
    `fake`, after the token was read. An agent with no model of its own runs on the workspace's
    `copilot_model`, else the worker's; a call's cost is its AI credits at the workspace's price
    per credit."""

    @asynccontextmanager
    async def open_copilot(
        run: StoredRun, tools: ToolExecutor | None
    ) -> AsyncGenerator[AgentRuntime]:
        token = await load_token(run)
        with registered(token):
            if settings.runtime != "claude":
                async with fake(run, tools) as runtime:
                    yield runtime
                return
            # Imported here: the SDK is only needed once a run really uses it.
            from agentic_runtime.copilot_sdk import SdkConnector

            chosen = await workspace(run)
            runtime = CopilotRuntime(
                SdkConnector(token.get_secret_value()),
                model=chosen.copilot_model or settings.copilot_model,
                tools=tools,
                secrets=[token.get_secret_value()],
                credit_usd=chosen.credit_usd,
            )
            yield _Watching(runtime, run, on_refused) if on_refused is not None else runtime

    return open_copilot
