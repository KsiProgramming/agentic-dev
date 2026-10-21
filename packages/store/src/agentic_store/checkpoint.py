"""The LangGraph Postgres checkpointer, where runs save their graph state after each node.

It shares `DATABASE_URL` with SQLAlchemy but talks to Postgres through psycopg (the saver's
driver). Its tables are created by the api package's Alembic revision `0006_checkpoints`.
On Windows, psycopg's async driver needs a `SelectorEventLoop`.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.engine import make_url

from agentic_engine.graph import checkpoint_serde


def psycopg_conninfo(database_url: str) -> str:
    """`DATABASE_URL` (a SQLAlchemy URL such as `postgresql+asyncpg://…`) as a libpq URI."""
    url = make_url(database_url).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


@asynccontextmanager
async def open_checkpointer(
    database_url: str, *, max_size: int = 4
) -> AsyncGenerator[AsyncPostgresSaver]:
    """A saver on a pool of up to `max_size` connections, closed on exit. It serialises with
    `checkpoint_serde()`, so a checkpoint only ever loads the engine's own state types."""
    async with AsyncConnectionPool(
        psycopg_conninfo(database_url),
        connection_class=AsyncConnection[DictRow],
        max_size=max_size,
        open=False,
        # What the saver expects of its connections (see `AsyncPostgresSaver.from_conn_string`).
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    ) as pool:
        yield AsyncPostgresSaver(pool, serde=checkpoint_serde())
