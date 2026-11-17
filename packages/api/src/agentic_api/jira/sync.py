"""Keeping the workspace's trigger webhooks on Jira in step after a change in the API (7.3)."""

from uuid import UUID

from fastapi import Request

from agentic_api.settings import Settings
from agentic_jira import JiraPlatform, sync_jira_webhooks, webhook_url
from agentic_secrets import KeyProvider


def webhook_target(request: Request) -> str:
    """Where Jira must post deliveries for this deployment."""
    settings: Settings = request.app.state.settings
    return webhook_url(settings.jira_webhook_base_url or settings.api_base_url)


async def sync_webhooks(request: Request, workspace_id: UUID) -> None:
    """Brings the workspace's webhooks on Jira in step with its rules; failures are stored on
    the connection's `webhooks`, never raised. Nothing happens without an Atlassian app or a
    master key."""
    jira: JiraPlatform | None = request.app.state.jira
    keys: KeyProvider | None = request.app.state.keys
    if jira is None or keys is None:
        return
    await sync_jira_webhooks(
        request.app.state.sessions, keys, jira, workspace_id, webhook_target(request)
    )
