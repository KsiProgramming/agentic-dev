"""The run event log: the envelope the engine emits for every step of a run, and where it goes.

A run's events form one ordered stream: engine lifecycle events (`run_*`, `node_*`) and every
`AgentEvent` the runtime streams, tagged with its node. `seq` gives the order (1, 2, …, no gaps).
The engine never touches a database; an `EventSink` (e.g. `agentic_store.PostgresEventSink`)
persists the stream.
"""

from datetime import UTC, datetime
from typing import Annotated, Final, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from agentic_runtime import AgentEvent, agent_event_adapter

type RunStatus = Literal["running", "waiting", "completed", "failed", "cancelled"]

RUN_STARTED: Final = "run_started"
RUN_RESUMED: Final = "run_resumed"
RUN_COMPLETED: Final = "run_completed"
RUN_FAILED: Final = "run_failed"
RUN_CANCELLED: Final = "run_cancelled"
NODE_STARTED: Final = "node_started"
NODE_COMPLETED: Final = "node_completed"
NODE_FAILED: Final = "node_failed"
NODE_CANCELLED: Final = "node_cancelled"
GATE_WAITING: Final = "gate_waiting"
GATE_DECIDED: Final = "gate_decided"

RUN_END_STATUS: Final[dict[str, RunStatus]] = {
    RUN_COMPLETED: "completed",
    RUN_FAILED: "failed",
    RUN_CANCELLED: "cancelled",
}
"""The run status each final run event sets."""


class RunEvent(BaseModel):
    """One row of the run event log. For agent events, `type` is the `AgentEvent` type and
    `payload` is the serialised event; payloads are data, never instructions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    seq: Annotated[int, Field(ge=1)]
    type: Annotated[str, Field(min_length=1)]
    node_id: str | None = None
    payload: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    created_at: datetime

    def agent_event(self) -> AgentEvent:
        """The `AgentEvent` this row holds. Raises `ValidationError` for lifecycle events."""
        return agent_event_adapter.validate_python(self.payload)


class EventSink(Protocol):
    """Receives a run's events in `seq` order. A sink that raises stops the run."""

    async def emit(self, event: RunEvent) -> None: ...


class InMemoryEventSink:
    """Keeps events in a list; for tests."""

    def __init__(self) -> None:
        self.events: list[RunEvent] = []

    async def emit(self, event: RunEvent) -> None:
        self.events.append(event)


class NullEventSink:
    """Drops every event."""

    async def emit(self, event: RunEvent) -> None:
        pass


class RunEventLog:
    """Numbers a run's events and hands them to a sink. A resumed run starts at `next_seq`, one
    past the last event its earlier attempts wrote, so the stream has no gaps."""

    def __init__(self, run_id: UUID, sink: EventSink, *, next_seq: int = 1) -> None:
        self.run_id = run_id
        self._sink = sink
        self._seq = next_seq - 1

    async def emit(
        self,
        type: str,
        *,
        node_id: str | None = None,
        payload: dict[str, JsonValue] | None = None,
    ) -> None:
        # `seq` is taken before the await, so it follows emit order.
        self._seq += 1
        await self._sink.emit(
            RunEvent(
                run_id=self.run_id,
                seq=self._seq,
                type=type,
                node_id=node_id,
                payload=payload or {},
                created_at=datetime.now(UTC),
            )
        )

    async def agent_event(self, node_id: str, event: AgentEvent) -> None:
        await self.emit(
            event.type, node_id=node_id, payload=agent_event_adapter.dump_python(event, mode="json")
        )
