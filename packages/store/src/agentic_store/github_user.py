"""A person's own GitHub account, connected so a run they start can use their Copilot
subscription (8.2).

The workspace has one connection per person (`GithubUserConnection`), each holding that person's
grant as one encrypted secret under the workspace's data key (the `agentic_github` package says
what is in it; here it is opaque). Only `refresh_github_user_secret` decrypts it, and nothing
lists it. A run uses only the connection it was started with, and never the company App's token.

A grant whose token kind expires (a GitHub App's user token lasts hours) is refreshed while its
row is locked, and the rotated pair is stored before the lock is released, as for Jira."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_secrets import KeyProvider, SecretDecryptError, WrappedKey, decrypt, encrypt
from agentic_store.audit import audit
from agentic_store.connections import WorkspaceNotFoundError, dek_context, workspace_dek
from agentic_store.models import GithubUserConnection, Workspace

GITHUB_USER = "github_user"


class GithubUserNotConnectedError(LookupError):
    """The workspace has no such personal GitHub connection."""


class GithubUserNeedsAttentionError(RuntimeError):
    """The connection cannot be used until its person connects again; `reason` says why
    (`invalid_grant`, `unauthorized`)."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"the GitHub connection needs attention: {reason}")
        self.reason = reason


@dataclass(frozen=True)
class GithubUserInfo:
    """A personal connection as listed: who it is, never its secret."""

    id: UUID
    workspace_id: UUID
    github_user_id: int
    login: str
    scopes: list[str] | None
    needs_attention: str | None
    created_at: datetime
    updated_at: datetime


def user_secret_aad(connection: GithubUserConnection) -> bytes:
    return f"agentic-secret:{connection.workspace_id}:{connection.id}:{GITHUB_USER}".encode()


async def put_github_user_connection(
    sessions: async_sessionmaker[AsyncSession],
    keys: KeyProvider,
    workspace_id: UUID,
    *,
    github_user_id: int,
    login: str,
    scopes: list[str] | None,
    secret: SecretStr,
) -> GithubUserInfo:
    """Store `secret` as that GitHub user's connection in the workspace, replacing their earlier
    one (the same person connecting again clears "needs attention")."""
    now = datetime.now(UTC)
    async with sessions.begin() as session:
        workspace = await session.get(Workspace, workspace_id, with_for_update=True)
        if workspace is None:
            raise WorkspaceNotFoundError(workspace_id)
        dek = await workspace_dek(session, keys, workspace, now)
        connection = await session.scalar(
            select(GithubUserConnection).where(
                GithubUserConnection.workspace_id == workspace_id,
                GithubUserConnection.github_user_id == github_user_id,
            )
        )
        replaced = connection is not None
        if connection is None:
            connection = GithubUserConnection(
                id=uuid4(),
                workspace_id=workspace_id,
                github_user_id=github_user_id,
                created_at=now,
            )
            session.add(connection)
        connection.login = login
        connection.scopes = scopes
        connection.needs_attention = None
        connection.updated_at = now
        connection.secret_nonce, connection.secret_ciphertext = encrypt(
            dek, secret, user_secret_aad(connection)
        )
        audit(
            session,
            workspace_id,
            "connection.added",
            details={"provider": GITHUB_USER, "account_login": login, "replaced": replaced},
        )
        return _info(connection)


async def list_github_user_connections(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID
) -> list[GithubUserInfo]:
    async with sessions() as session:
        if await session.get(Workspace, workspace_id) is None:
            raise WorkspaceNotFoundError(workspace_id)
        rows = await session.scalars(
            select(GithubUserConnection)
            .where(GithubUserConnection.workspace_id == workspace_id)
            .order_by(GithubUserConnection.login, GithubUserConnection.created_at)
        )
        return [_info(c) for c in rows]


async def get_github_user_connection(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID, connection_id: UUID
) -> GithubUserInfo | None:
    """The workspace's connection `connection_id`, or `None` (also for another workspace's)."""
    async with sessions() as session:
        connection = await session.get(GithubUserConnection, connection_id)
    if connection is None or connection.workspace_id != workspace_id:
        return None
    return _info(connection)


async def delete_github_user_connection(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID, connection_id: UUID
) -> bool:
    """Remove the connection and its grant. Runs started with it keep the login they recorded.
    `False` if the workspace has no such connection."""
    async with sessions.begin() as session:
        connection = await session.get(GithubUserConnection, connection_id, with_for_update=True)
        if connection is None or connection.workspace_id != workspace_id:
            return False
        login = connection.login
        await session.execute(
            delete(GithubUserConnection).where(GithubUserConnection.id == connection_id)
        )
        audit(
            session,
            workspace_id,
            "connection.removed",
            details={"provider": GITHUB_USER, "account_login": login},
        )
        return True


async def mark_github_user_needs_attention(
    sessions: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    connection_id: UUID,
    reason: str,
) -> bool:
    """Record that the connection cannot be used until its person connects again. `False` if
    there is no such connection or it was already marked (the audit entry is written once)."""
    async with sessions.begin() as session:
        connection = await session.get(GithubUserConnection, connection_id, with_for_update=True)
        if (
            connection is None
            or connection.workspace_id != workspace_id
            or connection.needs_attention is not None
        ):
            return False
        connection.needs_attention = reason
        connection.updated_at = datetime.now(UTC)
        audit(
            session,
            workspace_id,
            "connection.needs_attention",
            actor_type="system",
            details={"provider": GITHUB_USER, "account_login": connection.login, "reason": reason},
        )
        return True


async def refresh_github_user_secret(
    sessions: async_sessionmaker[AsyncSession],
    keys: KeyProvider,
    workspace_id: UUID,
    connection_id: UUID,
    refresh: Callable[[SecretStr], Awaitable[SecretStr | None]],
) -> SecretStr:
    """The connection's grant, after `refresh` had its chance to replace it.

    `refresh` gets the stored grant while the connection's row is locked, and returns a new one
    to store or `None` to keep it. If it raises, nothing is stored and the lock is released.
    Raises `GithubUserNotConnectedError`, `GithubUserNeedsAttentionError` or
    `SecretDecryptError`."""
    async with sessions.begin() as session:
        connection = await session.get(GithubUserConnection, connection_id, with_for_update=True)
        if connection is None or connection.workspace_id != workspace_id:
            raise GithubUserNotConnectedError(connection_id)
        if connection.needs_attention is not None:
            raise GithubUserNeedsAttentionError(connection.needs_attention)
        workspace = await session.get_one(Workspace, workspace_id)
        if workspace.wrapped_dek is None or workspace.key_id is None:
            raise SecretDecryptError("the workspace has no data key")
        dek = keys.unwrap(
            WrappedKey(workspace.key_id, workspace.wrapped_dek), dek_context(workspace)
        )
        aad = user_secret_aad(connection)
        current = decrypt(dek, connection.secret_nonce, connection.secret_ciphertext, aad)
        replacement = await refresh(current)
        if replacement is None:
            return current
        connection.secret_nonce, connection.secret_ciphertext = encrypt(dek, replacement, aad)
        connection.updated_at = datetime.now(UTC)
        return replacement


def _info(connection: GithubUserConnection) -> GithubUserInfo:
    return GithubUserInfo(
        id=connection.id,
        workspace_id=connection.workspace_id,
        github_user_id=connection.github_user_id,
        login=connection.login,
        scopes=connection.scopes,
        needs_attention=connection.needs_attention,
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )
