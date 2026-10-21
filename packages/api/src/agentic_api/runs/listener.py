"""Fans Postgres run event notifications out to the streams waiting on them."""

import asyncio
import contextlib
import logging
from collections import defaultdict
from collections.abc import Generator
from uuid import UUID

from agentic_store import RUN_EVENTS_CHANNEL, listen

log = logging.getLogger("agentic_api.runs")


class RunEventListener:
    """Holds one `LISTEN` connection per API process and wakes the subscribers of a run when it
    gets a new event. A wake-up only means "read again": streams re-read `run_events` after
    their last `seq`, so a lost or merged notification never loses an event."""

    def __init__(self, database_url: str, retry_s: float = 1.0) -> None:
        self._database_url = database_url
        self._retry_s = retry_s
        self._subscribers: defaultdict[UUID, set[asyncio.Event]] = defaultdict(set)

    @contextlib.contextmanager
    def subscribe(self, run_id: UUID) -> Generator[asyncio.Event]:
        """An event that is set whenever `run_id` may have new events."""
        woke = asyncio.Event()
        self._subscribers[run_id].add(woke)
        try:
            yield woke
        finally:
            self._subscribers[run_id].discard(woke)
            if not self._subscribers[run_id]:
                del self._subscribers[run_id]

    def notify(self, payload: str) -> None:
        try:
            run_id = UUID(payload.partition(":")[0])
        except ValueError:
            log.warning("ignored malformed notification %r", payload)
            return
        for woke in self._subscribers.get(run_id, ()):
            woke.set()

    def _wake_all(self) -> None:
        for subscribers in self._subscribers.values():
            for woke in subscribers:
                woke.set()

    async def run(self) -> None:
        """Listen until cancelled, reconnecting if the connection fails or drops."""
        while True:
            lost = asyncio.Event()
            try:
                async with listen(self._database_url, RUN_EVENTS_CHANNEL, self.notify, lost.set):
                    # Anything committed while we were not listening must still be read.
                    self._wake_all()
                    await lost.wait()
                log.warning("run event listener lost its connection; reconnecting")
            except OSError as exc:
                log.warning("run event listener cannot connect: %s", exc)
            except Exception:
                log.exception("run event listener failed")
            await asyncio.sleep(self._retry_s)
