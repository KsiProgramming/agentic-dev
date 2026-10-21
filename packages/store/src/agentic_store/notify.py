"""Postgres `LISTEN` on a dedicated connection."""

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any

import asyncpg  # pyright: ignore[reportMissingTypeStubs]

# asyncpg ships no type information.
_asyncpg: Any = asyncpg


@asynccontextmanager
async def listen(
    database_url: str, channel: str, on_notify: Callable[[str], None]
) -> AsyncGenerator[None]:
    """Call `on_notify(payload)` for each notification on `channel` while the context is open.

    `database_url` may be a SQLAlchemy URL (`postgresql+asyncpg://…`)."""

    def callback(_conn: object, _pid: int, _channel: str, payload: str) -> None:
        on_notify(payload)

    conn: Any = await _asyncpg.connect(database_url.replace("+asyncpg", "", 1))
    try:
        await conn.add_listener(channel, callback)
        yield
    finally:
        await conn.close()
