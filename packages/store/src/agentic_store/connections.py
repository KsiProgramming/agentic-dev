"""Workspaces and their connections, whose secrets are stored encrypted.

Each workspace has a data key (DEK) wrapped by the master key (`KeyProvider`). A connection's
secret is encrypted under that DEK, bound to its workspace, connection and provider. Only
`load_secret` ever decrypts; the listings carry the hint, never the secret."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_secrets import (
    KeyProvider,
    SecretDecryptError,
    WrappedKey,
    decrypt,
    encrypt,
    hint,
    new_dek,
)
from agentic_store.models import Connection, Workspace

log = logging.getLogger(__name__)


class WorkspaceNotFoundError(LookupError):
    """No workspace has the given id."""


@dataclass(frozen=True)
class WorkspaceInfo:
    id: UUID
    name: str
    created_at: datetime


@dataclass(frozen=True)
class ConnectionInfo:
    id: UUID
    workspace_id: UUID
    provider: str
    key_hint: str
    created_at: datetime
    updated_at: datetime


async def list_workspaces(sessions: async_sessionmaker[AsyncSession]) -> list[WorkspaceInfo]:
    async with sessions() as session:
        rows = await session.scalars(select(Workspace).order_by(Workspace.created_at))
        return [_workspace_info(w) for w in rows]


async def get_workspace(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID
) -> WorkspaceInfo | None:
    async with sessions() as session:
        workspace = await session.get(Workspace, workspace_id)
        return None if workspace is None else _workspace_info(workspace)


async def list_connections(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID
) -> list[ConnectionInfo]:
    """The workspace's connections, without their secrets."""
    async with sessions() as session:
        if await session.get(Workspace, workspace_id) is None:
            raise WorkspaceNotFoundError(workspace_id)
        rows = await session.scalars(
            select(Connection)
            .where(Connection.workspace_id == workspace_id)
            .order_by(Connection.provider)
        )
        return [_connection_info(c) for c in rows]


async def put_connection(
    sessions: async_sessionmaker[AsyncSession],
    keys: KeyProvider,
    workspace_id: UUID,
    provider: str,
    secret: SecretStr,
) -> ConnectionInfo:
    """Store `secret` as the workspace's `provider` connection, replacing any existing one.

    The workspace's data key is made on first use. If it cannot be unwrapped (the master key was
    lost or replaced), the workspace gets a new one and its other secrets, which nobody can read
    any more, are dropped: storing a key again is how a user recovers."""
    now = datetime.now(UTC)
    async with sessions.begin() as session:
        workspace = await session.get(Workspace, workspace_id, with_for_update=True)
        if workspace is None:
            raise WorkspaceNotFoundError(workspace_id)
        dek = await _workspace_dek(session, keys, workspace, now)
        connection = await session.scalar(
            select(Connection).where(
                Connection.workspace_id == workspace_id, Connection.provider == provider
            )
        )
        if connection is None:
            connection = Connection(
                id=uuid4(), workspace_id=workspace_id, provider=provider, created_at=now
            )
            session.add(connection)
        nonce, ciphertext = encrypt(dek, secret, _secret_aad(connection))
        connection.secret_nonce = nonce
        connection.secret_ciphertext = ciphertext
        connection.key_hint = hint(secret)
        connection.updated_at = now
        return _connection_info(connection)


async def delete_connection(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID, provider: str
) -> bool:
    """`False` if the workspace had no such connection."""
    async with sessions.begin() as session:
        if await session.get(Workspace, workspace_id) is None:
            raise WorkspaceNotFoundError(workspace_id)
        deleted = await session.scalar(
            delete(Connection)
            .where(Connection.workspace_id == workspace_id, Connection.provider == provider)
            .returning(Connection.id)
        )
    return deleted is not None


async def load_secret(
    sessions: async_sessionmaker[AsyncSession],
    keys: KeyProvider,
    workspace_id: UUID,
    provider: str,
) -> SecretStr | None:
    """The decrypted secret of the workspace's `provider` connection, or `None` if it has none.

    Raises `SecretDecryptError` if it was stored under another master key or was tampered with."""
    async with sessions() as session:
        row = (
            await session.execute(
                select(Workspace, Connection)
                .join(Connection, Connection.workspace_id == Workspace.id)
                .where(Workspace.id == workspace_id, Connection.provider == provider)
            )
        ).one_or_none()
    if row is None:
        return None
    workspace, connection = row
    if workspace.wrapped_dek is None or workspace.key_id is None:
        raise SecretDecryptError("the workspace has no data key")
    dek = keys.unwrap(WrappedKey(workspace.key_id, workspace.wrapped_dek), _dek_context(workspace))
    return decrypt(
        dek, connection.secret_nonce, connection.secret_ciphertext, _secret_aad(connection)
    )


async def _workspace_dek(
    session: AsyncSession, keys: KeyProvider, workspace: Workspace, now: datetime
) -> bytes:
    if workspace.wrapped_dek is not None and workspace.key_id is not None:
        try:
            return keys.unwrap(
                WrappedKey(workspace.key_id, workspace.wrapped_dek), _dek_context(workspace)
            )
        except SecretDecryptError:
            log.warning(
                "workspace %s: its data key cannot be unwrapped by master key %s; "
                "replacing it and dropping the secrets it protected",
                workspace.id,
                keys.key_id,
            )
            await session.execute(delete(Connection).where(Connection.workspace_id == workspace.id))
    dek = new_dek()
    wrapped = keys.wrap(dek, _dek_context(workspace))
    workspace.wrapped_dek = wrapped.blob
    workspace.key_id = wrapped.key_id
    workspace.updated_at = now
    return dek


def _dek_context(workspace: Workspace) -> bytes:
    return f"agentic-dek:{workspace.id}".encode()


def _secret_aad(connection: Connection) -> bytes:
    return (
        f"agentic-secret:{connection.workspace_id}:{connection.id}:{connection.provider}".encode()
    )


def _workspace_info(workspace: Workspace) -> WorkspaceInfo:
    return WorkspaceInfo(id=workspace.id, name=workspace.name, created_at=workspace.created_at)


def _connection_info(connection: Connection) -> ConnectionInfo:
    return ConnectionInfo(
        id=connection.id,
        workspace_id=connection.workspace_id,
        provider=connection.provider,
        key_hint=connection.key_hint,
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )
