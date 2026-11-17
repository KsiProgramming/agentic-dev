"""What the API (and, from 7.2, the worker's Jira tools) needs from Atlassian: `AtlassianApp`,
or `FakeAtlassian` in local dev and end-to-end tests."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from pydantic import SecretStr

from agentic_jira.models import (
    Account,
    DeliveryClaims,
    Grant,
    Issue,
    Project,
    ProjectPage,
    SearchPage,
    Site,
    Transition,
    Webhook,
)


class JiraPlatform(Protocol):
    """Each call that takes a token raises `JiraUnauthorizedError` when Atlassian refuses it
    (`agentic_jira.call` refreshes and retries), `JiraNotFoundError` for a missing issue,
    `JiraBadRequestError` for a request Jira refuses, `JiraRateLimitedError`, or `JiraApiError`;
    `register_webhook` raises `JiraWebhookError` when Jira refuses the webhook."""

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

    def verify_delivery(self, authorization: str | None) -> DeliveryClaims:
        """A webhook delivery's claims, or `JiraDeliveryError` (7.3)."""
        ...

    async def register_webhook(
        self, token: SecretStr, cloud_id: str, url: str, project_keys: Sequence[str]
    ) -> int: ...

    async def list_webhooks(self, token: SecretStr, cloud_id: str) -> list[Webhook]: ...

    async def refresh_webhooks(
        self, token: SecretStr, cloud_id: str, ids: Sequence[int]
    ) -> datetime | None: ...

    async def delete_webhooks(
        self, token: SecretStr, cloud_id: str, ids: Sequence[int]
    ) -> None: ...

    async def project_statuses(self, token: SecretStr, cloud_id: str, key: str) -> list[str]: ...

    async def aclose(self) -> None: ...
