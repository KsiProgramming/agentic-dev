import os
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_secrets import KEY_BYTES, LocalKeyProvider, SecretDecryptError
from agentic_store import (
    DEFAULT_WORKSPACE_ID,
    Connection,
    Workspace,
    WorkspaceNotFoundError,
    delete_connection,
    get_github_installation,
    get_workspace,
    list_connections,
    list_workspaces,
    load_secret,
    put_connection,
    put_github_connection,
)

pytestmark = pytest.mark.integration

KEYS = LocalKeyProvider(os.urandom(KEY_BYTES))


async def new_workspace(sessions: async_sessionmaker[AsyncSession]) -> UUID:
    workspace_id = uuid4()
    async with sessions.begin() as session:
        session.add(Workspace(id=workspace_id, name=f"ws-{workspace_id.hex[:6]}"))
    return workspace_id


async def stored_row(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID
) -> tuple[Workspace, Connection]:
    async with sessions() as session:
        workspace = await session.get_one(Workspace, workspace_id)
        connection = await session.scalar(
            select(Connection).where(Connection.workspace_id == workspace_id)
        )
        assert connection is not None
        return workspace, connection


async def test_the_default_workspace_exists(sessions: async_sessionmaker[AsyncSession]) -> None:
    workspace = await get_workspace(sessions, DEFAULT_WORKSPACE_ID)

    assert workspace is not None
    assert workspace.name == "Default"
    assert DEFAULT_WORKSPACE_ID in {w.id for w in await list_workspaces(sessions)}


async def test_a_secret_round_trips_and_is_stored_encrypted(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await new_workspace(sessions)
    secret = SecretStr("sk-ant-store-test-1234")

    info = await put_connection(sessions, KEYS, workspace_id, "claude", secret)

    assert info.key_hint == "1234"
    assert await load_secret(sessions, KEYS, workspace_id, "claude") == secret
    workspace, connection = await stored_row(sessions, workspace_id)
    assert workspace.key_id == KEYS.key_id
    assert workspace.wrapped_dek is not None
    assert connection.secret_ciphertext is not None
    assert secret.get_secret_value().encode() not in connection.secret_ciphertext
    assert secret.get_secret_value().encode() not in workspace.wrapped_dek


async def test_put_replaces_and_keeps_the_data_key(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await new_workspace(sessions)
    first = await put_connection(sessions, KEYS, workspace_id, "claude", SecretStr("sk-first-aaaa"))
    workspace, _ = await stored_row(sessions, workspace_id)

    second = await put_connection(
        sessions, KEYS, workspace_id, "claude", SecretStr("sk-second-bbbb")
    )

    assert second.id == first.id
    assert second.key_hint == "bbbb"
    assert [c.key_hint for c in await list_connections(sessions, workspace_id)] == ["bbbb"]
    assert (await stored_row(sessions, workspace_id))[0].wrapped_dek == workspace.wrapped_dek
    assert await load_secret(sessions, KEYS, workspace_id, "claude") == SecretStr("sk-second-bbbb")


async def test_listing_carries_no_secret(sessions: async_sessionmaker[AsyncSession]) -> None:
    workspace_id = await new_workspace(sessions)
    await put_connection(sessions, KEYS, workspace_id, "claude", SecretStr("sk-listed-cccc"))

    [listed] = await list_connections(sessions, workspace_id)

    assert listed.provider == "claude"
    assert "sk-listed-cccc" not in repr(listed)


async def test_a_ciphertext_moved_to_another_workspace_fails(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    victim, attacker = await new_workspace(sessions), await new_workspace(sessions)
    await put_connection(sessions, KEYS, victim, "claude", SecretStr("sk-victim-dddd"))
    await put_connection(sessions, KEYS, attacker, "claude", SecretStr("sk-attacker-eeee"))
    _, stolen = await stored_row(sessions, victim)

    async with sessions.begin() as session:
        await session.execute(
            update(Connection)
            .where(Connection.workspace_id == attacker)
            .values(secret_nonce=stolen.secret_nonce, secret_ciphertext=stolen.secret_ciphertext)
        )

    with pytest.raises(SecretDecryptError):
        await load_secret(sessions, KEYS, attacker, "claude")


async def test_another_master_key_cannot_read_and_a_new_put_recovers(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await new_workspace(sessions)
    await put_connection(sessions, KEYS, workspace_id, "claude", SecretStr("sk-old-ffff"))
    replaced = LocalKeyProvider(os.urandom(KEY_BYTES))

    with pytest.raises(SecretDecryptError):
        await load_secret(sessions, replaced, workspace_id, "claude")

    await put_connection(sessions, replaced, workspace_id, "claude", SecretStr("sk-new-gggg"))
    assert await load_secret(sessions, replaced, workspace_id, "claude") == SecretStr("sk-new-gggg")


async def test_delete_then_load_is_none(sessions: async_sessionmaker[AsyncSession]) -> None:
    workspace_id = await new_workspace(sessions)
    await put_connection(sessions, KEYS, workspace_id, "claude", SecretStr("sk-gone-hhhh"))

    assert await delete_connection(sessions, workspace_id, "claude") is True
    assert await delete_connection(sessions, workspace_id, "claude") is False
    assert await load_secret(sessions, KEYS, workspace_id, "claude") is None
    assert await list_connections(sessions, workspace_id) == []


async def test_an_unknown_workspace_is_reported(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    missing = uuid4()
    with pytest.raises(WorkspaceNotFoundError):
        await put_connection(sessions, KEYS, missing, "claude", SecretStr("sk-none-iiii"))
    with pytest.raises(WorkspaceNotFoundError):
        await list_connections(sessions, missing)
    with pytest.raises(WorkspaceNotFoundError):
        await delete_connection(sessions, missing, "claude")
    assert await get_workspace(sessions, missing) is None


async def test_a_github_installation_round_trips_without_a_data_key(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await new_workspace(sessions)
    assert await get_github_installation(sessions, workspace_id) is None

    info = await put_github_connection(sessions, workspace_id, 42, "acme")

    assert (info.provider, info.account_login, info.key_hint) == ("github", "acme", None)
    assert await get_github_installation(sessions, workspace_id) == 42
    workspace, connection = await stored_row(sessions, workspace_id)
    assert workspace.wrapped_dek is None
    assert connection.secret_ciphertext is None
    assert await load_secret(sessions, KEYS, workspace_id, "github") is None


async def test_a_new_installation_replaces_the_old_one(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await new_workspace(sessions)
    first = await put_github_connection(sessions, workspace_id, 42, "acme")

    second = await put_github_connection(sessions, workspace_id, 43, "acme-two")

    assert second.id == first.id
    assert await get_github_installation(sessions, workspace_id) == 43
    assert [c.account_login for c in await list_connections(sessions, workspace_id)] == ["acme-two"]
    assert await delete_connection(sessions, workspace_id, "github") is True
    assert await get_github_installation(sessions, workspace_id) is None


async def test_claude_and_github_connections_coexist(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await new_workspace(sessions)
    await put_connection(sessions, KEYS, workspace_id, "claude", SecretStr("sk-both-jjjj"))
    await put_github_connection(sessions, workspace_id, 42, "acme")

    listed = await list_connections(sessions, workspace_id)

    assert [(c.provider, c.key_hint, c.account_login) for c in listed] == [
        ("claude", "jjjj", None),
        ("github", None, "acme"),
    ]
    assert await load_secret(sessions, KEYS, workspace_id, "claude") == SecretStr("sk-both-jjjj")


async def test_a_lost_master_key_keeps_the_github_connection(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await new_workspace(sessions)
    await put_connection(sessions, KEYS, workspace_id, "claude", SecretStr("sk-lost-kkkk"))
    await put_github_connection(sessions, workspace_id, 42, "acme")
    replaced = LocalKeyProvider(os.urandom(KEY_BYTES))

    await put_connection(sessions, replaced, workspace_id, "openai", SecretStr("sk-other-llll"))

    providers = [c.provider for c in await list_connections(sessions, workspace_id)]
    assert providers == ["github", "openai"]


async def test_the_columns_each_provider_needs_are_enforced(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await new_workspace(sessions)

    with pytest.raises(IntegrityError):
        async with sessions.begin() as session:
            session.add(Connection(id=uuid4(), workspace_id=workspace_id, provider="github"))
    with pytest.raises(IntegrityError):
        async with sessions.begin() as session:
            session.add(
                Connection(id=uuid4(), workspace_id=workspace_id, provider="claude", external_id=1)
            )


async def test_github_lookups_report_an_unknown_workspace(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    missing = uuid4()
    with pytest.raises(WorkspaceNotFoundError):
        await put_github_connection(sessions, missing, 42, "acme")
    with pytest.raises(WorkspaceNotFoundError):
        await get_github_installation(sessions, missing)
