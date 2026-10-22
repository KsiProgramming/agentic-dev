import asyncio
import contextlib
from collections.abc import AsyncIterable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api.runs.listener import RunEventListener
from agentic_api.runs.models import (
    ApprovalRequest,
    ApprovalResponse,
    CreateRunRequest,
    CreateRunResponse,
)
from agentic_engine.events import RUN_END_STATUS
from agentic_engine.gate import GateDecision
from agentic_store import (
    DEFAULT_WORKSPACE_ID,
    ApprovalError,
    RunNotFoundError,
    create_run,
    enqueue_run,
    get_github_installation,
    get_run,
    get_workspace,
    list_run_events,
    record_approval,
)

router = APIRouter(prefix="/runs", tags=["runs"])

# Streams re-read the log this often even with no notification, in case one was lost.
RECHECK_S = 15.0

# Each frame's `data` is a `RunEvent`. FastAPI documents this itself only for plain yielded
# models, not `ServerSentEvent`, so it is spelled out here (the component is added in app.py).
_SSE_RUN_EVENTS: dict[str, Any] = {
    "responses": {
        "200": {
            "content": {
                "text/event-stream": {
                    "itemSchema": {
                        "required": ["data"],
                        "properties": {
                            "data": {
                                "type": "string",
                                "contentMediaType": "application/json",
                                "contentSchema": {"$ref": "#/components/schemas/RunEvent"},
                            }
                        },
                    }
                }
            }
        }
    }
}


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.sessions


async def existing_run(run_id: UUID, request: Request) -> UUID:
    if await get_run(_sessions(request), run_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id} not found")
    return run_id


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="createRun",
    responses={
        404: {"description": "No workspace with this id"},
        409: {
            "description": "The workflow uses `github.*` tools, but the workspace has no "
            "GitHub connection"
        },
    },
)
async def create(body: CreateRunRequest, request: Request) -> CreateRunResponse:
    """Queue a run of `workflow`, or of the workflow `template` builds, with `input` for its first
    node, working on `repo` if given. Stream it from `events_url`. A workflow that publishes
    (`github.openPR`) must have a gate between the writer and the publishing node, or it is
    refused with `422`."""
    redis: Redis = request.app.state.redis
    sessions = _sessions(request)
    workspace_id = body.workspace_id or DEFAULT_WORKSPACE_ID
    if await get_workspace(sessions, workspace_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"workspace {workspace_id} not found")
    if body.uses_github() and await get_github_installation(sessions, workspace_id) is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "the workflow uses github.* tools, but the workspace has no GitHub connection; "
            "install the GitHub App first",
        )
    run_id = await create_run(sessions, body.spec(), body.input, body.repo, workspace_id)
    await enqueue_run(redis, run_id)
    return CreateRunResponse(
        run_id=run_id, events_url=str(request.url_for("stream_run_events", run_id=run_id))
    )


@router.post(
    "/{run_id}/approvals",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="approveRun",
    responses={
        404: {"description": "No run with this id"},
        409: {"description": "The run is not waiting at this gate, or it was already decided"},
    },
)
async def approve(run_id: UUID, body: ApprovalRequest, request: Request) -> ApprovalResponse:
    """Decide the gate the run is waiting at: `approve` continues the run, `reject` ends it
    `cancelled`. The run is queued again; its stream carries on with `gate_decided`."""
    decision = GateDecision(decision=body.decision, comment=body.comment)
    try:
        await record_approval(_sessions(request), run_id, body.node_id, decision)
    except RunNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except ApprovalError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    await enqueue_run(request.app.state.redis, run_id)
    return ApprovalResponse(run_id=run_id, node_id=body.node_id, decision=body.decision)


@router.get(
    "/{run_id}/events",
    response_class=EventSourceResponse,
    operation_id="streamRunEvents",
    name="stream_run_events",
    responses={404: {"description": "No run with this id"}},
    openapi_extra=_SSE_RUN_EVENTS,
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
