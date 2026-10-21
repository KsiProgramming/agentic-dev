"""Run worker process.

Phase 0.1 stub: connects to Redis, reports ready and idles until asked to stop.
Job consumption arrives with the run queue (phase 0.4/0.6).
"""

import asyncio
import logging
import signal
from types import FrameType

from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.asyncio import Redis

from agentic_engine.logging import configure_logging

log = logging.getLogger("agentic_engine.worker")


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    redis_url: str = "redis://localhost:6379/0"


async def run(
    settings: WorkerSettings, stop: asyncio.Event, ready: asyncio.Event | None = None
) -> None:
    redis = Redis.from_url(settings.redis_url)  # pyright: ignore[reportUnknownMemberType]
    try:
        await redis.ping()  # pyright: ignore[reportUnknownMemberType]
        log.info("worker ready")
        if ready is not None:
            ready.set()
        await stop.wait()
        log.info("worker stopping")
    finally:
        await redis.aclose()


async def _main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def on_signal(_signum: int, _frame: FrameType | None) -> None:
        loop.call_soon_threadsafe(stop.set)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows event loops
            signal.signal(sig, on_signal)
    await run(WorkerSettings(), stop)


def main() -> None:
    configure_logging()
    asyncio.run(_main())


if __name__ == "__main__":
    main()
