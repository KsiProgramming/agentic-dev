import asyncio
import contextlib
from collections.abc import AsyncIterable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api.runs.listener import RunEventListener
from agentic_api.runs.models import CreateRunRequest, CreateRunResponse
from agentic_engine.events import RUN_END_STATUS
from agentic_store import create_run, enqueue_run, get_run, list_run_events

router = APIRouter(prefix="/runs", tags=["runs"])

# Streams re-read the log this often even with no notification, in case one was lost.
RECHECK_S = 15.0


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.sessions


async def existing_run(run_id: UUID, request: Request) -> UUID:
    if await get_run(_sessions(request), run_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id} not found")
    return run_id


@router.post("", status_code=status.HTTP_202_ACCEPTED, operation_id="createRun")
async def create(body: CreateRunRequest, request: Request) -> CreateRunResponse:
    """Queue a run of `workflow` with `input` for its first node. Stream it from `events_url`."""
    redis: Redis = request.app.state.redis
    run_id = await create_run(_sessions(request), body.workflow, body.input)
    await enqueue_run(redis, run_id)
    return CreateRunResponse(
        run_id=run_id, events_url=str(request.url_for("stream_run_events", run_id=run_id))
    )


@router.get(
    "/{run_id}/events",
    response_class=EventSourceResponse,
    operation_id="streamRunEvents",
    name="stream_run_events",
    responses={404: {"description": "No run with this id"}},
)
async def stream_events(
    request: Request,
    run_id: Annotated[UUID, Depends(existing_run)],
    last_event_id: Annotated[int | None, Header(ge=0)] = None,
    after: Annotated[
        int | None, Query(ge=0, description="Start after this seq (`Last-Event-ID` wins).")
    ] = None,
) -> AsyncIterable[ServerSentEvent]:
    """The run's events as Server-Sent Events: stored ones first, then live ones as they are
    written. Each frame's `id` is the event's `seq`, `event` its type and `data` the `RunEvent`.
    The stream ends after the run's final event."""
    sessions = _sessions(request)
    listener: RunEventListener = request.app.state.run_events
    last = last_event_id if last_event_id is not None else (after or 0)
    # Subscribe before reading, so an event written in between still wakes us.
    with listener.subscribe(run_id) as woke:
        while True:
            woke.clear()
            for event in await list_run_events(sessions, run_id, after_seq=last):
                yield ServerSentEvent(id=str(event.seq), event=event.type, data=event)
                last = event.seq
                if event.type in RUN_END_STATUS:
                    return
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(woke.wait(), RECHECK_S)
