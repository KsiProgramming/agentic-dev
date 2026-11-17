"""`WorkspaceJira`: one workspace's Jira as the platform's `jira` tools use it (7.2).

It reads the connection (sites and picked projects) and the projects' field mappings (7.4),
answers the one allowlist check
(`agentic_store.jira_project_allowed`), and calls Atlassian with a valid token (`call`: a refresh
under the row lock, one retry on `401`). Tokens never leave it."""

from collections.abc import Awaitable, Callable, Mapping
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_jira.platform import JiraPlatform
from agentic_jira.tokens import call
from agentic_secrets import KeyProvider
from agentic_store import (
    JiraConnectionInfo,
    get_jira_connection,
    jira_project_allowed,
    jira_site_field_mappings,
    record_jira_own_move,
)


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

    async def field_mappings(self, cloud_id: str) -> Mapping[str, Mapping[str, str]]:
        """The picked projects' mapped fields on the site (7.4): key → role → field id."""
        return await jira_site_field_mappings(self._sessions, self._workspace_id, cloud_id)

    async def call[T](self, request: Callable[[SecretStr], Awaitable[T]]) -> T:
        return await call(self._sessions, self._keys, self.platform, self._workspace_id, request)

    async def moving(self, cloud_id: str, key: str, status: str, run_id: UUID) -> None:
        """Records a move the run is about to make, so its delivery starts no run (7.3)."""
        await record_jira_own_move(
            self._sessions, self._workspace_id, cloud_id, key, status, run_id
        )
