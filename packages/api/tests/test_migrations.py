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

    assert version == "0015_workspace_model_prices"
    assert {
        "runs",
        "run_events",
        "workspaces",
        "connections",
        "approvals",
        "workspace_model_prices",
    } | CHECKPOINT_TABLES <= set(table_names)
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


async def test_the_workspaces_revision_moves_existing_runs_to_the_default_workspace(
    postgres_url: str,
) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")
    await asyncio.to_thread(command.downgrade, config, "0006_checkpoints")
    assert not {"workspaces", "connections"} & await table_names(postgres_url)

    engine = create_async_engine(postgres_url)
    async with engine.begin() as conn:
        run_id = (
            await conn.execute(
                text(
                    "INSERT INTO runs (id, status, spec) "
                    "VALUES (gen_random_uuid(), 'completed', '{}') RETURNING id"
                )
            )
        ).scalar_one()
    await asyncio.to_thread(command.upgrade, config, "head")
    async with engine.connect() as conn:
        workspace_id = (
            await conn.execute(text("SELECT workspace_id FROM runs WHERE id = :id"), {"id": run_id})
        ).scalar_one()
    await engine.dispose()

    assert str(workspace_id) == "00000000-0000-0000-0000-000000000001"


async def connection_columns(postgres_url: str) -> set[str]:
    engine = create_async_engine(postgres_url)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'connections'"
            )
        )
        columns = set(rows.scalars())
    await engine.dispose()
    return columns


async def test_the_github_connections_revision_downgrades_and_upgrades(postgres_url: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")
    engine = create_async_engine(postgres_url)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO connections (id, workspace_id, provider, external_id, account_login) "
                "VALUES (gen_random_uuid(), '00000000-0000-0000-0000-000000000001', 'github', "
                "42, 'acme')"
            )
        )
    await engine.dispose()

    # The downgrade drops GitHub rows, which the restored NOT NULL secret columns cannot hold.
    await asyncio.to_thread(command.downgrade, config, "0007_workspaces_connections")
    assert not {"external_id", "account_login"} & await connection_columns(postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")
    assert {"external_id", "account_login"} <= await connection_columns(postgres_url)
