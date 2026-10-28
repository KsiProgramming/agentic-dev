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
LOOP_ITERATION_STARTED: Final = "loop_iteration_started"
"""A loop starts an iteration: `iteration` (from 1)."""
LOOP_CONDITION_EVALUATED: Final = "loop_condition_evaluated"
"""A loop checked its `until` after an iteration: `iteration`, `result`."""
MAP_ITEM_STARTED: Final = "map_item_started"
"""A map starts running its body for one item: `index` (from 0), `item`."""
MAP_ITEM_COMPLETED: Final = "map_item_completed"
"""A map's body ended for one item: `index`, `status`, and `error` if it did not complete."""
PARALLEL_BRANCH_STARTED: Final = "parallel_branch_started"
"""A parallel starts one of its branches: `index` (from 0), `branch_id`."""
PARALLEL_BRANCH_COMPLETED: Final = "parallel_branch_completed"
"""A parallel's branch ended: `index`, `branch_id`, `status` (`cancelled` once the parallel's
join was decided without it), and `error` if it did not complete."""
POLICY_LIMIT_EXCEEDED: Final = "policy_limit_exceeded"
"""The run went over a policy limit: `limit`, `value` (the limit) and `observed`; the node that
hit it, if one did. A `node_failed` or `run_failed` naming the reason follows. For
`limit: "budget_usd"` the amounts are USD decimal strings, and `model` names a model with no price
when that is why the budget could not be held."""
PR_OPENED: Final = "pr_opened"
"""A publishing tool node opened a pull request: `url`, `number`, `head`, `base`, `commit`."""
REPO_CREATED: Final = "repo_created"
"""A tool node created the run's repo: `full_name`, `url`, `default_branch`, `private`, and
`created` (false if an earlier attempt of the run created it). The run then stops its attempt
and goes on in a new one, which clones the repo."""

ARTIFACT_WRITTEN: Final = "artifact_written"
"""A node wrote a run artifact (4.3), before its `node_completed`: `name`, `version`,
`media_type`, `size` (bytes) and `sha256`. The content is in the run's artifact store."""

RUN_END_STATUS: Final[dict[str, RunStatus]] = {
    RUN_COMPLETED: "completed",
    RUN_FAILED: "failed",
    RUN_CANCELLED: "cancelled",
}
"""The run status each final run event sets."""


class RunEvent(BaseModel):
    """One row of the run event log. For agent events, `type` is the `AgentEvent` type and
    `payload` is the serialised event; payloads are data, never instructions. The events of a
    node inside a map also carry `item`, the index of the item it ran for, and those of a node
    inside a parallel `branch`, the index of its branch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    seq: Annotated[int, Field(ge=1)]
    type: Annotated[str, Field(min_length=1)]
    node_id: str | None = None
    payload: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    created_at: datetime

    def agent_event(self) -> AgentEvent:
        """The `AgentEvent` this row holds. Raises `ValidationError` for lifecycle events."""
        return agent_event_adapter.validate_python(
            {k: v for k, v in self.payload.items() if k not in ("item", "branch")}
        )


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
        item: int | None = None,
        branch: int | None = None,
    ) -> None:
        """Write one event. `item` tags the event of a node that runs inside a map, `branch` one
        inside a parallel."""
        if item is not None:
            payload = {**(payload or {}), "item": item}
        if branch is not None:
            payload = {**(payload or {}), "branch": branch}
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

    async def agent_event(
        self, node_id: str, event: AgentEvent, item: int | None = None, branch: int | None = None
    ) -> None:
        await self.emit(
            event.type,
            node_id=node_id,
            payload=agent_event_adapter.dump_python(event, mode="json"),
            item=item,
            branch=branch,
        )
