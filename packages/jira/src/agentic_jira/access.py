"""`WorkspaceJira`: one workspace's Jira as the platform's `jira` tools use it (7.2).

It reads the connection (sites and picked projects), answers the one allowlist check
(`agentic_store.jira_project_allowed`), and calls Atlassian with a valid token (`call`: a refresh
under the row lock, one retry on `401`). Tokens never leave it."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_jira.platform import JiraPlatform
from agentic_jira.tokens import call
from agentic_secrets import KeyProvider
from agentic_store import JiraConnectionInfo, get_jira_connection, jira_project_allowed


class WorkspaceJira:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        keys: KeyProvider,
        platform: JiraPlatform,
        workspace_id: UUID,
    ) -> None:
        self._sessions = sessions
        self._keys = keys
        self.platform = platform
        self._workspace_id = workspace_id

    async def connection(self) -> JiraConnectionInfo | None:
        return await get_jira_connection(self._sessions, self._workspace_id)

    async def allowed(self, cloud_id: str, project_key: str) -> bool:
        return await jira_project_allowed(self._sessions, self._workspace_id, cloud_id, project_key)

    async def call[T](self, request: Callable[[SecretStr], Awaitable[T]]) -> T:
        return await call(self._sessions, self._keys, self.platform, self._workspace_id, request)
