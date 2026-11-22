import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from agentic_github import (
    FakeGithubUserAuth,
    GithubApiError,
    UserGrant,
    user_access_token,
)
from agentic_secrets import KEY_BYTES, LocalKeyProvider
from agentic_store import (
    GithubUserNeedsAttentionError,
    Workspace,
    list_github_user_connections,
    put_github_user_connection,
)

pytestmark = pytest.mark.integration

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "api" / "alembic.ini"
KEYS = LocalKeyProvider(os.urandom(KEY_BYTES))

Sessions = async_sessionmaker[AsyncSession]


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
async def sessions(postgres_url: str) -> AsyncIterator[Sessions]:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_url)
    # env.py calls asyncio.run, so the command must run outside this event loop.
    await asyncio.to_thread(command.upgrade, config, "head")
    engine = create_async_engine(postgres_url)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def connected(sessions: Sessions, auth: FakeGithubUserAuth) -> tuple[UUID, UUID]:
    workspace_id = uuid4()
    async with sessions.begin() as session:
        session.add(Workspace(id=workspace_id, name=f"ws-{workspace_id.hex[:6]}"))
    grant = await auth.exchange(f"fake-user-code-{auth.login}")
    user = await auth.user(grant.access_token)
    info = await put_github_user_connection(
        sessions,
        KEYS,
        workspace_id,
        github_user_id=user.id,
        login=user.login,
        scopes=list(grant.scopes),
        secret=grant.to_secret(),
    )
    return workspace_id, info.id


async def test_a_token_that_never_expires_is_used_as_it_is(sessions: Sessions) -> None:
    auth = FakeGithubUserAuth("http://api.test")
    workspace_id, connection_id = await connected(sessions, auth)

    token = await user_access_token(sessions, KEYS, auth, workspace_id, connection_id)

    assert token == auth.issued[0].access_token
    assert auth.refreshes == 0


async def test_a_token_about_to_expire_is_refreshed_and_the_rotated_grant_stored(
    sessions: Sessions,
) -> None:
    auth = FakeGithubUserAuth("http://api.test", expires_in_s=60)
    workspace_id, connection_id = await connected(sessions, auth)
    auth.expires_in_s = 28800

    token = await user_access_token(sessions, KEYS, auth, workspace_id, connection_id)
    again = await user_access_token(sessions, KEYS, auth, workspace_id, connection_id)

    assert token == again == auth.issued[1].access_token
    assert auth.refreshes == 1  # the second call found a fresh token


async def test_a_fresh_expiring_token_is_not_refreshed(sessions: Sessions) -> None:
    auth = FakeGithubUserAuth("http://api.test", expires_in_s=28800)
    workspace_id, connection_id = await connected(sessions, auth)

    await user_access_token(sessions, KEYS, auth, workspace_id, connection_id)

    assert auth.refreshes == 0


async def test_force_refreshes_a_token_github_would_not_accept(sessions: Sessions) -> None:
    auth = FakeGithubUserAuth("http://api.test", expires_in_s=28800)
    workspace_id, connection_id = await connected(sessions, auth)

    token = await user_access_token(sessions, KEYS, auth, workspace_id, connection_id, force=True)

    assert token == auth.issued[1].access_token


async def test_a_refresh_github_refuses_marks_the_connection_as_needing_attention(
    sessions: Sessions,
) -> None:
    auth = FakeGithubUserAuth("http://api.test", expires_in_s=60)
    workspace_id, connection_id = await connected(sessions, auth)
    auth.refuse_refresh = True

    with pytest.raises(GithubUserNeedsAttentionError) as raised:
        await user_access_token(sessions, KEYS, auth, workspace_id, connection_id)

    assert raised.value.reason == "invalid_grant"
    (only,) = await list_github_user_connections(sessions, workspace_id)
    assert only.needs_attention == "invalid_grant"
    with pytest.raises(GithubUserNeedsAttentionError):  # and it stays unusable until reconnected
        await user_access_token(sessions, KEYS, auth, workspace_id, connection_id)


async def test_github_being_down_leaves_the_connection_usable(sessions: Sessions) -> None:
    auth = FakeGithubUserAuth("http://api.test", expires_in_s=60)
    workspace_id, connection_id = await connected(sessions, auth)
    auth.unavailable = True

    with pytest.raises(GithubApiError):
        await user_access_token(sessions, KEYS, auth, workspace_id, connection_id)

    (only,) = await list_github_user_connections(sessions, workspace_id)
    assert only.needs_attention is None


async def test_the_stored_grant_keeps_its_refresh_token_when_github_omits_a_new_one(
    sessions: Sessions,
) -> None:
    auth = FakeGithubUserAuth("http://api.test", expires_in_s=60)
    workspace_id, connection_id = await connected(sessions, auth)
    original = auth.issued[0]
    assert original.refresh_token is not None

    class KeepsRefreshToken(FakeGithubUserAuth):
        async def refresh(self, refresh_token: SecretStr) -> UserGrant:
            grant = await super().refresh(refresh_token)
            return UserGrant(grant.access_token, None, None, grant.scopes)

    keeping = KeepsRefreshToken("http://api.test", expires_in_s=60)
    await keeping.exchange("fake-user-code-ada")  # so its next tokens are numbered after the first

    token = await user_access_token(sessions, KEYS, keeping, workspace_id, connection_id)

    assert token != original.access_token
    # A later refresh still has the original refresh token to use.
    again = await user_access_token(
        sessions, KEYS, keeping, workspace_id, connection_id, force=True
    )
    assert again != token
