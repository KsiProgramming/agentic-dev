import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.redis import RedisContainer

from agentic_worker.main import WorkerSettings

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "api" / "alembic.ini"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings come only from each test, not from the developer's shell or `.env` (which may
    select Claude and hold a real key)."""
    for name in (
        "AGENTIC_RUNTIME",
        "ANTHROPIC_API_KEY",
        "CLAUDE_MODEL",
        "RUNTIME",
        "SANDBOX_BACKEND",
        "SANDBOX_IMAGE",
        "SANDBOX_LOCAL_ROOT",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(WorkerSettings.model_config, "env_file", None)


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
async def sessions(postgres_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessions on a Postgres migrated to head with the api package's Alembic revisions."""
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_url)
    # env.py calls asyncio.run, so the command must run outside this event loop.
    await asyncio.to_thread(command.upgrade, config, "head")
    engine = create_async_engine(postgres_url)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    with RedisContainer("redis:7-alpine") as rc:
        yield f"redis://{rc.get_container_host_ip()}:{rc.get_exposed_port(6379)}/0"
