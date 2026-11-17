"""What the API (and, from 7.2, the worker's Jira tools) needs from Atlassian: `AtlassianApp`,
or `FakeAtlassian` in local dev and end-to-end tests."""

from collections.abc import Sequence
from typing import Protocol

from pydantic import SecretStr

from agentic_jira.models import (
    Account,
    Grant,
    Issue,
    Project,
    ProjectPage,
    SearchPage,
    Site,
    Transition,
)


class JiraPlatform(Protocol):
    """Each call that takes a token raises `JiraUnauthorizedError` when Atlassian refuses it
    (`agentic_jira.call` refreshes and retries), `JiraNotFoundError` for a missing issue,
    `JiraBadRequestError` for a request Jira refuses, `JiraRateLimitedError`, or `JiraApiError`."""

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

    async def get_issue(self, token: SecretStr, cloud_id: str, key: str) -> Issue: ...

    async def search(
        self,
        token: SecretStr,
        cloud_id: str,
        jql: str,
        *,
        limit: int,
        page_token: str | None = None,
    ) -> SearchPage: ...

    async def transitions(self, token: SecretStr, cloud_id: str, key: str) -> list[Transition]: ...

    async def add_comment(self, token: SecretStr, cloud_id: str, key: str, body: str) -> str: ...

    async def transition(
        self, token: SecretStr, cloud_id: str, key: str, transition_id: str
    ) -> None: ...

    async def aclose(self) -> None: ...
