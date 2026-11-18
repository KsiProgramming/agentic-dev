import asyncio
import os
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_secrets import KEY_BYTES, LocalKeyProvider, SecretDecryptError
from agentic_store import (
    AuditEvent,
    GithubUserConnection,
    GithubUserNeedsAttentionError,
    GithubUserNotConnectedError,
    Workspace,
    delete_github_user_connection,
    get_github_user_connection,
    list_github_user_connections,
    mark_github_user_needs_attention,
    put_connection,
    put_github_user_connection,
    refresh_github_user_secret,
)

pytestmark = pytest.mark.integration

KEYS = LocalKeyProvider(os.urandom(KEY_BYTES))
GRANT = SecretStr('{"access_token":"gho_store0001","refresh_token":null}')

Sessions = async_sessionmaker[AsyncSession]


async def new_workspace(sessions: Sessions) -> UUID:
    workspace_id = uuid4()
    async with sessions.begin() as session:
        session.add(Workspace(id=workspace_id, name=f"ws-{workspace_id.hex[:6]}"))
    return workspace_id


async def connect(
    sessions: Sessions, workspace_id: UUID, *, user_id: int = 1, login: str = "ada"
) -> UUID:
    info = await put_github_user_connection(
        sessions, KEYS, workspace_id, github_user_id=user_id, login=login, scopes=None, secret=GRANT
    )
    return info.id


async def keep(secret: SecretStr) -> SecretStr | None:
    return None


async def audit_rows(sessions: Sessions, workspace_id: UUID) -> list[AuditEvent]:
    async with sessions() as session:
        rows = await session.scalars(
            select(AuditEvent)
            .where(AuditEvent.workspace_id == workspace_id)
            .order_by(AuditEvent.id)
        )
        return list(rows)


async def test_each_person_has_a_connection_and_the_listing_never_shows_the_secret(
    sessions: Sessions,
) -> None:
    workspace_id = await new_workspace(sessions)
    await connect(sessions, workspace_id, user_id=1, login="ada")
    await connect(sessions, workspace_id, user_id=2, login="grace")

    listed = await list_github_user_connections(sessions, workspace_id)

    assert [c.login for c in listed] == ["ada", "grace"]
    assert "gho_store0001" not in repr(listed)


async def test_the_grant_is_stored_encrypted_and_read_back_under_the_lock(
    sessions: Sessions,
) -> None:
    workspace_id = await new_workspace(sessions)
    connection_id = await connect(sessions, workspace_id)

    async with sessions() as session:
        row = await session.get_one(GithubUserConnection, connection_id)
    assert b"gho_store0001" not in row.secret_ciphertext
    assert (
        await refresh_github_user_secret(sessions, KEYS, workspace_id, connection_id, keep) == GRANT
    )


async def test_connecting_again_as_the_same_person_replaces_the_row_and_clears_attention(
    sessions: Sessions,
) -> None:
    workspace_id = await new_workspace(sessions)
    first = await connect(sessions, workspace_id, login="ada")
    assert await mark_github_user_needs_attention(sessions, workspace_id, first, "invalid_grant")

    second = await connect(sessions, workspace_id, login="ada-renamed")

    assert second == first
    (only,) = await list_github_user_connections(sessions, workspace_id)
    assert (only.login, only.needs_attention) == ("ada-renamed", None)


async def test_another_workspaces_connection_is_not_found_or_usable(sessions: Sessions) -> None:
    mine = await new_workspace(sessions)
    theirs = await new_workspace(sessions)
    theirs_id = await connect(sessions, theirs)

    assert await get_github_user_connection(sessions, mine, theirs_id) is None
    assert not await delete_github_user_connection(sessions, mine, theirs_id)
    assert not await mark_github_user_needs_attention(sessions, mine, theirs_id, "x")
    with pytest.raises(GithubUserNotConnectedError):
        await refresh_github_user_secret(sessions, KEYS, mine, theirs_id, keep)
    assert await get_github_user_connection(sessions, theirs, theirs_id) is not None


async def test_refresh_stores_what_it_returns_and_nothing_when_it_raises(
    sessions: Sessions,
) -> None:
    workspace_id = await new_workspace(sessions)
    connection_id = await connect(sessions, workspace_id)
    rotated = SecretStr('{"access_token":"ghu_rotated"}')

    async def rotate(_: SecretStr) -> SecretStr | None:
        return rotated

    async def fail(_: SecretStr) -> SecretStr | None:
        raise RuntimeError("github down")

    assert (
        await refresh_github_user_secret(sessions, KEYS, workspace_id, connection_id, rotate)
        == rotated
    )
    with pytest.raises(RuntimeError, match="github down"):
        await refresh_github_user_secret(sessions, KEYS, workspace_id, connection_id, fail)
    assert (
        await refresh_github_user_secret(sessions, KEYS, workspace_id, connection_id, keep)
        == rotated
    )


async def test_two_refreshes_do_not_race(sessions: Sessions) -> None:
    workspace_id = await new_workspace(sessions)
    connection_id = await connect(sessions, workspace_id)
    seen: list[str] = []

    async def rotate(secret: SecretStr) -> SecretStr | None:
        seen.append(secret.get_secret_value())
        await asyncio.sleep(0.05)  # the other refresh must wait for the row lock meanwhile
        return SecretStr(f'{{"n":{len(seen)}}}')

    await asyncio.gather(
        refresh_github_user_secret(sessions, KEYS, workspace_id, connection_id, rotate),
        refresh_github_user_secret(sessions, KEYS, workspace_id, connection_id, rotate),
    )

    # The second saw what the first stored, not the original grant.
    assert seen == [GRANT.get_secret_value(), '{"n":1}']


async def test_a_connection_that_needs_attention_cannot_be_used_and_is_audited_once(
    sessions: Sessions,
) -> None:
    workspace_id = await new_workspace(sessions)
    connection_id = await connect(sessions, workspace_id)

    assert await mark_github_user_needs_attention(
        sessions, workspace_id, connection_id, "unauthorized"
    )
    assert not await mark_github_user_needs_attention(
        sessions, workspace_id, connection_id, "unauthorized"
    )

    with pytest.raises(GithubUserNeedsAttentionError) as raised:
        await refresh_github_user_secret(sessions, KEYS, workspace_id, connection_id, keep)
    assert raised.value.reason == "unauthorized"
    attention = [
        a
        for a in await audit_rows(sessions, workspace_id)
        if a.action == "connection.needs_attention"
    ]
    assert len(attention) == 1
    assert attention[0].details == {
        "provider": "github_user",
        "account_login": "ada",
        "reason": "unauthorized",
    }


async def test_removing_a_connection_deletes_the_grant_and_is_audited(sessions: Sessions) -> None:
    workspace_id = await new_workspace(sessions)
    connection_id = await connect(sessions, workspace_id)

    assert await delete_github_user_connection(sessions, workspace_id, connection_id)
    assert not await delete_github_user_connection(sessions, workspace_id, connection_id)

    assert await list_github_user_connections(sessions, workspace_id) == []
    with pytest.raises(GithubUserNotConnectedError):
        await refresh_github_user_secret(sessions, KEYS, workspace_id, connection_id, keep)
    last = (await audit_rows(sessions, workspace_id))[-1]
    assert (last.action, last.details) == (
        "connection.removed",
        {"provider": "github_user", "account_login": "ada"},
    )


async def test_audit_entries_never_hold_the_token(sessions: Sessions) -> None:
    workspace_id = await new_workspace(sessions)
    await connect(sessions, workspace_id)

    assert "gho_store0001" not in repr(
        [a.details for a in await audit_rows(sessions, workspace_id)]
    )


async def test_a_replaced_master_key_drops_the_grants_it_protected(sessions: Sessions) -> None:
    workspace_id = await new_workspace(sessions)
    await connect(sessions, workspace_id)
    other_keys = LocalKeyProvider(os.urandom(KEY_BYTES))

    # Storing any secret under a master key that cannot unwrap the data key replaces that key.
    await put_connection(
        sessions, other_keys, workspace_id, "claude", SecretStr("sk-ant-test-1234")
    )

    assert await list_github_user_connections(sessions, workspace_id) == []
    with pytest.raises((SecretDecryptError, GithubUserNotConnectedError)):
        await refresh_github_user_secret(sessions, other_keys, workspace_id, uuid4(), keep)
