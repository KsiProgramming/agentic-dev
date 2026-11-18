"""A valid access token for one person's GitHub connection (8.2), for the worker that builds a
Copilot run and the API that checks a connection.

A GitHub App's user token expires (8 hours) and its refresh token rotates, so two refreshes must
not race: the token is refreshed while the connection's row is locked
(`refresh_github_user_secret`) and the rotated grant is stored before the lock is released. An
OAuth app's `gho_` token has no expiry and no refresh token, and is used as it is. A refresh GitHub
refuses marks the connection as needing attention: only that person can fix it, by connecting
again."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_github.user_auth import GithubUserAuth, GithubUserAuthError, UserGrant
from agentic_secrets import KeyProvider
from agentic_store import (
    GithubUserNeedsAttentionError,
    mark_github_user_needs_attention,
    refresh_github_user_secret,
)

# A token this close to its expiry is refreshed, so a session started with it does not outlive it.
REFRESH_MARGIN = timedelta(minutes=10)
INVALID_GRANT = "invalid_grant"
UNAUTHORIZED = "unauthorized"


async def user_access_token(
    sessions: async_sessionmaker[AsyncSession],
    keys: KeyProvider,
    auth: GithubUserAuth,
    workspace_id: UUID,
    connection_id: UUID,
    *,
    force: bool = False,
) -> SecretStr:
    """The connection's access token, refreshed first if it is about to expire (or `force`).

    Raises `GithubUserNotConnectedError`, `GithubUserNeedsAttentionError` (also when this refresh
    was refused), `GithubApiError` when GitHub could not be reached, or `SecretDecryptError`."""

    async def refresh(secret: SecretStr) -> SecretStr | None:
        grant = UserGrant.from_secret(secret)
        if grant.refresh_token is None:
            return None  # a token that never expires: nothing to refresh
        if not force and (
            grant.expires_at is None or grant.expires_at - datetime.now(UTC) > REFRESH_MARGIN
        ):
            return None
        fresh = await auth.refresh(grant.refresh_token)
        # GitHub may leave the scopes out of a refresh; they are the grant's.
        scopes = fresh.scopes or grant.scopes
        return UserGrant(
            fresh.access_token, fresh.refresh_token or grant.refresh_token, fresh.expires_at, scopes
        ).to_secret()

    try:
        secret = await refresh_github_user_secret(
            sessions, keys, workspace_id, connection_id, refresh
        )
    except GithubUserAuthError:
        await mark_github_user_needs_attention(sessions, workspace_id, connection_id, INVALID_GRANT)
        raise GithubUserNeedsAttentionError(INVALID_GRANT) from None
    return UserGrant.from_secret(secret).access_token
