"""What the API (and, from 7.2, the worker's Jira tools) needs from Atlassian: `AtlassianApp`,
or `FakeAtlassian` in local dev and end-to-end tests."""

from collections.abc import Sequence
from typing import Protocol

from pydantic import SecretStr

from agentic_jira.models import Account, Grant, Project, ProjectPage, Site


class JiraPlatform(Protocol):
    def authorize_url(self, state: str) -> str: ...

    async def exchange(self, code: str) -> Grant: ...

    async def refresh(self, refresh_token: SecretStr) -> Grant: ...

    async def account(self, token: SecretStr) -> Account: ...

    async def sites(self, token: SecretStr) -> list[Site]: ...

    async def search_projects(
        self, token: SecretStr, cloud_id: str, *, query: str = "", start_at: int = 0
    ) -> ProjectPage: ...

    async def get_projects(
        self, token: SecretStr, cloud_id: str, ids: Sequence[str]
    ) -> list[Project]: ...

    async def aclose(self) -> None: ...
