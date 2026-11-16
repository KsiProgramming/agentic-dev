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

from agentic_jira import (
    FAKE_ACCOUNT,
    FAKE_CODE,
    FAKE_SITES,
    SCOPES,
    FakeAtlassian,
    Grant,
    JiraApiError,
    Site,
    access_token,
    call,
)
from agentic_secrets import KEY_BYTES, LocalKeyProvider
from agentic_store import (
    JiraNeedsAttentionError,
    JiraSiteRef,
    Workspace,
    get_jira_connection,
    put_jira_connection,
    refresh_jira_secret,
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


async def connected(sessions: Sessions, atlassian: FakeAtlassian) -> UUID:
    workspace_id = uuid4()
    async with sessions.begin() as session:
        session.add(Workspace(id=workspace_id, name=f"ws-{workspace_id.hex[:6]}"))
    grant = await atlassian.exchange(FAKE_CODE)
    await put_jira_connection(
        sessions,
        KEYS,
        workspace_id,
        grant.to_secret(),
        account=FAKE_ACCOUNT.name,
        scopes=grant.scopes,
        sites=[JiraSiteRef(s.cloud_id, s.url, s.name) for s in FAKE_SITES],
    )
    return workspace_id


async def test_a_fresh_token_is_used_as_it_is(sessions: Sessions) -> None:
    atlassian = FakeAtlassian("http://api.test")
    workspace_id = await connected(sessions, atlassian)

    token = await access_token(sessions, KEYS, atlassian, workspace_id)

    assert token == atlassian.issued[0].access_token
    assert atlassian.refreshes == 0


async def test_a_token_about_to_expire_is_refreshed_and_the_pair_stored(
    sessions: Sessions,
) -> None:
    atlassian = FakeAtlassian("http://api.test")
    atlassian.expires_in_s = 30
    workspace_id = await connected(sessions, atlassian)
    atlassian.expires_in_s = 3600

    token = await access_token(sessions, KEYS, atlassian, workspace_id)
    again = await access_token(sessions, KEYS, atlassian, workspace_id)

    assert token == again == atlassian.issued[1].access_token
    assert atlassian.refreshes == 1


async def test_a_refresh_keeps_the_scopes_when_atlassian_leaves_them_out(
    sessions: Sessions,
) -> None:
    atlassian = FakeAtlassian("http://api.test")
    workspace_id = await connected(sessions, atlassian)
    atlassian.granted_scopes = ()

    await access_token(sessions, KEYS, atlassian, workspace_id, force=True)

    async def keep(secret: SecretStr) -> SecretStr | None:
        return None

    stored = Grant.from_secret(await refresh_jira_secret(sessions, KEYS, workspace_id, keep))
    assert stored.scopes == SCOPES
    assert stored.access_token == atlassian.issued[1].access_token


async def test_a_refused_refresh_marks_the_connection(sessions: Sessions) -> None:
    atlassian = FakeAtlassian("http://api.test")
    workspace_id = await connected(sessions, atlassian)
    atlassian.refuse_refresh = True

    with pytest.raises(JiraNeedsAttentionError) as refused:
        await access_token(sessions, KEYS, atlassian, workspace_id, force=True)

    assert refused.value.reason == "invalid_grant"
    connection = await get_jira_connection(sessions, workspace_id)
    assert connection is not None and connection.needs_attention == "invalid_grant"
    with pytest.raises(JiraNeedsAttentionError):
        await access_token(sessions, KEYS, atlassian, workspace_id)
    assert atlassian.refreshes == 1


async def test_an_unreachable_atlassian_marks_nothing(sessions: Sessions) -> None:
    atlassian = FakeAtlassian("http://api.test")
    workspace_id = await connected(sessions, atlassian)
    atlassian.unavailable = True

    with pytest.raises(JiraApiError):
        await access_token(sessions, KEYS, atlassian, workspace_id, force=True)

    connection = await get_jira_connection(sessions, workspace_id)
    assert connection is not None and connection.needs_attention is None


async def test_a_call_refreshes_once_when_the_token_is_not_accepted(sessions: Sessions) -> None:
    atlassian = FakeAtlassian("http://api.test")
    workspace_id = await connected(sessions, atlassian)
    tokens: list[SecretStr] = []

    async def sites(token: SecretStr) -> list[Site]:
        tokens.append(token)
        atlassian.unauthorized = len(tokens) == 1
        return await atlassian.sites(token)

    atlassian.unauthorized = True
    found = await call(sessions, KEYS, atlassian, workspace_id, sites)

    assert found == list(FAKE_SITES)
    assert tokens == [g.access_token for g in atlassian.issued]
    assert atlassian.refreshes == 1


async def test_a_call_refused_twice_marks_the_connection(sessions: Sessions) -> None:
    atlassian = FakeAtlassian("http://api.test")
    workspace_id = await connected(sessions, atlassian)
    atlassian.unauthorized = True

    with pytest.raises(JiraNeedsAttentionError) as refused:
        await call(sessions, KEYS, atlassian, workspace_id, atlassian.sites)

    assert refused.value.reason == "unauthorized"
    connection = await get_jira_connection(sessions, workspace_id)
    assert connection is not None and connection.needs_attention == "unauthorized"
