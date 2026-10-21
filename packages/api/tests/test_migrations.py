import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


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

    assert version == "0003_run_spec"
    assert {"runs", "run_events"} <= set(table_names)
    # The migrations match the `agentic_store` models.
    await asyncio.to_thread(command.check, config)
