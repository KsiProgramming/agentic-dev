"""The `AgentRuntime` interface every provider adapter implements.

Contract for the event stream of an `AgentRun` (checked by `check_events`):

- It ends with exactly one terminal event: `completed`, `failed` or `cancelled`.
- Nothing comes after the terminal event.
- Every `tool_result` follows a `tool_call` with the same `call_id`; each call has one result at
  most, and call ids are unique within a run.
- At least one `usage` event comes before `completed`.

Cancellation is cooperative:

- `cancel()` is idempotent and safe to call before, during or after iteration.
- After `cancel()`, a stream that has not ended yields `cancelled` and stops.
- Cancelling a run that has already ended is a no-op.
"""

from collections.abc import AsyncIterator
from typing import Protocol

from agentic_runtime.events import AgentEvent
from agentic_runtime.request import AgentRequest


class AgentRun(Protocol):
    """A started agent run. Iterate it once to receive its events."""

    def __aiter__(self) -> AsyncIterator[AgentEvent]: ...

    def cancel(self) -> None: ...


class AgentRuntime(Protocol):
    """Starts agent runs on one provider."""

    def start(self, request: AgentRequest) -> AgentRun:
        """Return a handle for the run; work starts when the handle is iterated."""
        ...
