"""Postgres `LISTEN` on a dedicated connection."""

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any

import asyncpg  # pyright: ignore[reportMissingTypeStubs]

# asyncpg ships no type information.
_asyncpg: Any = asyncpg


@asynccontextmanager
async def listen(
    database_url: str,
    channel: str,
    on_notify: Callable[[str], None],
    on_lost: Callable[[], None] | None = None,
) -> AsyncGenerator[None]:
    """Call `on_notify(payload)` for each notification on `channel` while the context is open,
    and `on_lost()` if the connection drops (notifications then stop).

    `database_url` may be a SQLAlchemy URL (`postgresql+asyncpg://…`)."""

    def notified(_conn: object, _pid: int, _channel: str, payload: str) -> None:
        on_notify(payload)

    def terminated(_conn: object) -> None:
        if on_lost is not None:
            on_lost()

    conn: Any = await _asyncpg.connect(database_url.replace("+asyncpg", "", 1))
    try:
        conn.add_termination_listener(terminated)
        await conn.add_listener(channel, notified)
        yield
    finally:
        await conn.close()
