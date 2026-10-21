import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from langgraph.checkpoint.postgres.base import BasePostgresSaver
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
CHECKPOINT_TABLES = {
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
    "checkpoint_migrations",
}


async def test_upgrade_head_creates_run_tables(postgres_url: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_url)

    # env.py calls asyncio.run, so the command must run outside this event loop.
    await asyncio.to_thread(command.upgrade, config, "head")

    engine = create_async_engine(postgres_url)
    async with engine.connect() as conn:
        version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
        tables = (
            await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1")
            )
        ).scalars()
        table_names = list(tables)
    await engine.dispose()

    assert version == "0006_checkpoints"
    assert {"runs", "run_events"} | CHECKPOINT_TABLES <= set(table_names)
    # The migrations match the `agentic_store` models.
    await asyncio.to_thread(command.check, config)


async def test_the_run_repo_revision_downgrades_and_upgrades(postgres_url: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")

    await asyncio.to_thread(command.downgrade, config, "0003_run_spec")
    assert "repo" not in await run_columns(postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")
    assert "repo" in await run_columns(postgres_url)


async def run_columns(postgres_url: str) -> set[str]:
    engine = create_async_engine(postgres_url)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = 'runs'")
        )
        columns = set(rows.scalars())
    await engine.dispose()
    return columns


async def test_checkpoint_tables_match_the_installed_saver(postgres_url: str) -> None:
    """Revision 0006 applies every migration the installed saver has, as its `setup()` would.
    If this fails after upgrading `langgraph-checkpoint-postgres`, add a revision for the rest."""
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")

    engine = create_async_engine(postgres_url)
    async with engine.connect() as conn:
        applied = list(
            (await conn.execute(text("SELECT v FROM checkpoint_migrations ORDER BY v"))).scalars()
        )
    await engine.dispose()

    assert applied == list(range(len(BasePostgresSaver.MIGRATIONS)))


async def test_the_lease_and_checkpoint_revisions_downgrade_and_upgrade(postgres_url: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")

    await asyncio.to_thread(command.downgrade, config, "0004_run_repo")
    assert not {"worker_id", "lease_expires_at", "attempt"} & await run_columns(postgres_url)
    assert not CHECKPOINT_TABLES & await table_names(postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")
    assert {"worker_id", "lease_expires_at", "attempt"} <= await run_columns(postgres_url)
    assert await table_names(postgres_url) >= CHECKPOINT_TABLES


async def table_names(postgres_url: str) -> set[str]:
    engine = create_async_engine(postgres_url)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        names = set(rows.scalars())
    await engine.dispose()
    return names
