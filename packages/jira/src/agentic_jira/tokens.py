"""A valid access token for a workspace's Jira connection, for whoever needs one: the API now,
the worker's Jira tools from 7.2.

Atlassian's refresh tokens rotate (each use returns a new one), so two refreshes must not race.
The token is refreshed while the connection's row is locked (`refresh_jira_secret`), and the
rotated pair is stored before the lock is released. A refresh Atlassian refuses marks the
connection as needing attention: only the person who consented can fix it, by connecting again."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_jira.errors import JiraAuthError, JiraUnauthorizedError
from agentic_jira.models import Grant
from agentic_jira.platform import JiraPlatform
from agentic_secrets import KeyProvider
from agentic_store import (
    JiraNeedsAttentionError,
    mark_jira_needs_attention,
    refresh_jira_secret,
)

# A token this close to its expiry is refreshed, so a call made with it does not outlive it.
REFRESH_MARGIN = timedelta(seconds=60)
INVALID_GRANT = "invalid_grant"
UNAUTHORIZED = "unauthorized"


async def access_token(
    sessions: async_sessionmaker[AsyncSession],
    keys: KeyProvider,
    platform: JiraPlatform,
    workspace_id: UUID,
    *,
    force: bool = False,
) -> SecretStr:
    """The connection's access token, refreshed first if it is about to expire (or `force`).

    Raises `JiraNotConnectedError`, `JiraNeedsAttentionError` (also when this refresh was
    refused), `JiraApiError` when Atlassian could not be reached, or `SecretDecryptError`."""

    async def refresh(secret: SecretStr) -> SecretStr | None:
        grant = Grant.from_secret(secret)
        if not force and grant.expires_at - datetime.now(UTC) > REFRESH_MARGIN:
            return None
        fresh = await platform.refresh(grant.refresh_token)
        # Atlassian may leave the scopes out of a refresh; they are the grant's.
        scopes = fresh.scopes or grant.scopes
        return Grant(fresh.access_token, fresh.refresh_token, fresh.expires_at, scopes).to_secret()

    try:
        secret = await refresh_jira_secret(sessions, keys, workspace_id, refresh)
    except JiraAuthError:
        await mark_jira_needs_attention(sessions, workspace_id, INVALID_GRANT)
        raise JiraNeedsAttentionError(INVALID_GRANT) from None
    return Grant.from_secret(secret).access_token


async def call[T](
    sessions: async_sessionmaker[AsyncSession],
    keys: KeyProvider,
    platform: JiraPlatform,
    workspace_id: UUID,
    request: Callable[[SecretStr], Awaitable[T]],
) -> T:
    """`request` with the workspace's access token. A token Atlassian does not accept is
    refreshed once; if the new one is refused too (the app's access was removed), the
    connection is marked as needing attention and `JiraNeedsAttentionError` is raised."""
    token = await access_token(sessions, keys, platform, workspace_id)
    try:
        return await request(token)
    except JiraUnauthorizedError:
        pass
    token = await access_token(sessions, keys, platform, workspace_id, force=True)
    try:
        return await request(token)
    except JiraUnauthorizedError:
        await mark_jira_needs_attention(sessions, workspace_id, UNAUTHORIZED)
        raise JiraNeedsAttentionError(UNAUTHORIZED) from None
