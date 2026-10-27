"""Merges a node's streamed text so the event log gets at most one delta per interval.

A model streams a chunk every few milliseconds; logging each one makes the log (and the replay
the monitor reads) hundreds of rows per message. The buffer writes the first chunk at once, then
joins the chunks that arrive within `interval` into one `text_delta` (or `reasoning_delta`). The
concatenated text and the order of events stay the same: any other event, or a chunk of the other
kind, writes the pending text first.
"""

import asyncio
from collections.abc import Awaitable, Callable

from agentic_runtime import AgentEvent, ReasoningDelta, TextDelta

DELTA_INTERVAL_S = 0.25
"""At most one delta per node (or map item) is written in this many seconds."""

type _Delta = TextDelta | ReasoningDelta


class DeltaBuffer:
    """Sits between one node's agent events and the log. Call `close()` when the node ends."""

    def __init__(
        self,
        write: Callable[[AgentEvent], Awaitable[None]],
        interval: float = DELTA_INTERVAL_S,
    ) -> None:
        self._write = write
        self._interval = interval
        self._kind: type[_Delta] = TextDelta
        self._pending: list[str] = []
        self._written_at: float | None = None
        self._timer: asyncio.Task[None] | None = None

    async def emit(self, event: AgentEvent) -> None:
        if not isinstance(event, TextDelta | ReasoningDelta):
            await self.flush()
            await self._write(event)
            return
        if type(event) is not self._kind:
            await self.flush()
            self._kind = type(event)
        self._pending.append(event.text)
        now = asyncio.get_running_loop().time()
        due = self._written_at is None or now - self._written_at >= self._interval
        if due:
            await self.flush()
        elif self._timer is None:
            assert self._written_at is not None
            delay = self._written_at + self._interval - now
            self._timer = asyncio.create_task(self._flush_after(delay))

    async def flush(self) -> None:
        """Write the pending text now, as one delta of its kind."""
        self._stop_timer()
        if not self._pending:
            return
        text = "".join(self._pending)
        self._pending.clear()
        self._written_at = asyncio.get_running_loop().time()
        await self._write(self._kind(text=text))

    async def close(self) -> None:
        """Write what is pending; the buffer is not used after this."""
        await self.flush()

    async def _flush_after(self, delay: float) -> None:
        await asyncio.sleep(delay)
        self._timer = None
        await self.flush()

    def _stop_timer(self) -> None:
        # A timer that is still set is only sleeping: once it wakes it clears `_timer` before
        # it writes, so cancelling it never cuts a write short.
        timer, self._timer = self._timer, None
        if timer is not None and timer is not asyncio.current_task():
            timer.cancel()
