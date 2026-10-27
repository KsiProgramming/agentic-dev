import asyncio
import contextlib
from collections.abc import AsyncIterable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api.github.models import GithubErrorDetail
from agentic_api.github.routes import NewRepoRefused, github_app, new_repo_owner
from agentic_api.runs.listener import RunEventListener
from agentic_api.runs.models import (
    ApprovalRequest,
    ApprovalResponse,
    CancelResponse,
    CreateRunRequest,
    CreateRunResponse,
    EditErrorDetail,
    PolicyErrorDetail,
    RerunRequest,
    RunDetail,
    RunStatus,
    RunSummary,
    RunSummaryPage,
    RunUsage,
    WaitingGate,
    WorkflowRef,
    uses_github,
)
from agentic_api.workspaces.models import to_usd
from agentic_engine.events import RUN_END_STATUS
from agentic_engine.gate import GateDecision
from agentic_engine.spec import WorkflowSpec, creates_repo
from agentic_engine.templates import wrap_with_create_repo
from agentic_github import GithubApiError, github_remote
from agentic_sandbox import RepoSource
from agentic_store import (
    DEFAULT_WORKSPACE_ID,
    ApprovalError,
    InvalidCursorError,
    InvalidEditsError,
    PolicyViolationError,
    RunEndedError,
    RunNotEndedError,
    RunNotFoundError,
    RunSummaryRow,
    WorkspaceNotFoundError,
    create_rerun,
    create_run,
    enqueue_run,
    get_github_installation,
    get_run,
    get_run_summary,
    get_workspace,
    list_changed_run_summaries,
    list_run_events,
    list_run_summaries,
    record_approval,
    request_cancel,
)

router = APIRouter(prefix="/runs", tags=["runs"])

# Streams re-read the log this often even with no notification, in case one was lost.
RECHECK_S = 15.0

# The summaries stream re-reads changes this far back, so a change committed after a later one
# (two workers writing at once) is still sent. Changes already sent are not sent again.
SUMMARY_LOOKBACK = timedelta(seconds=5)
# After a wake-up the summaries stream waits this long, so a burst of events is read once.
SUMMARY_COALESCE_S = 0.2


def _sse_of(model: str) -> dict[str, Any]:
    """OpenAPI for an SSE response whose frames carry `model` as `data`. FastAPI documents this
    itself only for plain yielded models, not `ServerSentEvent`, so it is spelled out here."""
    return {
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
                                    "contentSchema": {"$ref": f"#/components/schemas/{model}"},
                                }
                            },
                        }
                    }
                }
            }
        }
    }


# `RunEvent` is added to the components in app.py.
_SSE_RUN_EVENTS = _sse_of("RunEvent")


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.sessions


async def existing_run(run_id: UUID, request: Request) -> UUID:
    if await get_run(_sessions(request), run_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id} not found")
    return run_id


async def existing_workspace(
    request: Request,
    workspace_id: Annotated[
        UUID | None, Query(description="Default: the default workspace.")
    ] = None,
) -> UUID:
    workspace_id = workspace_id or DEFAULT_WORKSPACE_ID
    if await get_workspace(_sessions(request), workspace_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"workspace {workspace_id} not found")
    return workspace_id


def _summary_fields(row: RunSummaryRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "status": row.status,
        "workflow": WorkflowRef(id=row.workflow_id, name=row.workflow_name),
        "template_id": row.template_id,
        "repo": row.repo,
        "created_at": row.created_at,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "pr_url": row.pr_url,
        "waiting_gate": WaitingGate.model_validate(row.waiting_gate) if row.waiting_gate else None,
        "rerun_of": row.rerun_of,
        "usage": RunUsage.model_validate(row.usage, from_attributes=True),
    }


@router.get(
    "",
    operation_id="listRuns",
    responses={
        404: {"description": "No workspace with this id"},
        422: {"description": "Invalid filter, `limit` or `cursor`"},
    },
)
async def list_runs(
    request: Request,
    workspace_id: Annotated[
        UUID | None, Query(description="Default: the default workspace.")
    ] = None,
    run_status: Annotated[
        list[RunStatus] | None,
        Query(alias="status", description="Only runs with one of these statuses."),
    ] = None,
    template: Annotated[str | None, Query(description="Only runs of this template id.")] = None,
    repo: Annotated[str | None, Query(description="Only runs on this repo URL.")] = None,
    cursor: Annotated[str | None, Query(description="`next_cursor` of the previous page.")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> RunSummaryPage:
    """The workspace's runs, newest first, one page at a time. Filters combine; `status` may be
    given several times. Status, timings, PR URL and the waiting gate come from each run's
    events."""
    sessions = _sessions(request)
    workspace_id = workspace_id or DEFAULT_WORKSPACE_ID
    if await get_workspace(sessions, workspace_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"workspace {workspace_id} not found")
    try:
        rows, next_cursor = await list_run_summaries(
            sessions,
            workspace_id,
            statuses=run_status or (),
            template_id=template,
            repo_url=repo,
            cursor=cursor,
            limit=limit,
        )
    except InvalidCursorError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    return RunSummaryPage(
        items=[RunSummary(**_summary_fields(row)) for row in rows], next_cursor=next_cursor
    )


@router.get(
    "/stream",
    response_class=EventSourceResponse,
    operation_id="streamRunSummaries",
    responses={404: {"description": "No workspace with this id"}},
    openapi_extra=_sse_of("RunSummary"),
)
async def stream_summaries(
    request: Request, workspace_id: Annotated[UUID, Depends(existing_workspace)]
) -> AsyncIterable[ServerSentEvent]:
    """Live changes to the workspace's runs as Server-Sent Events: a `run_summary` frame with
    the run's `RunSummary` whenever its status, timings, PR URL, waiting gate or usage change,
    including new runs. Each frame's `id` is when the run last changed. Only changes after
    connecting are sent; after a reconnect, list the runs again. The stream stays open."""
    sessions = _sessions(request)
    listener: RunEventListener = request.app.state.run_events
    watermark = datetime.now(UTC)
    # What was last sent per run, kept while the run is inside the lookback window.
    sent: dict[UUID, tuple[datetime, RunSummary]] = {}
    # Subscribe before reading, so a change written in between still wakes us.
    with listener.subscribe_all() as woke:
        while True:
            woke.clear()
            changed = await list_changed_run_summaries(
                sessions, workspace_id, since=watermark - SUMMARY_LOOKBACK
            )
            for updated_at, row in changed:
                summary = RunSummary(**_summary_fields(row))
                if (last := sent.get(row.id)) is None or last[1] != summary:
                    yield ServerSentEvent(
                        id=updated_at.isoformat(), event="run_summary", data=summary
                    )
                sent[row.id] = (updated_at, summary)
                watermark = max(watermark, updated_at)
            sent = {
                run_id: kept
                for run_id, kept in sent.items()
                if kept[0] > watermark - SUMMARY_LOOKBACK
            }
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(woke.wait(), RECHECK_S)
            await asyncio.sleep(SUMMARY_COALESCE_S)


@router.get(
    "/{run_id}",
    operation_id="getRun",
    responses={404: {"description": "No run with this id"}},
)
async def get(run_id: UUID, request: Request) -> RunDetail:
    """One run's summary, with its `input`, its workflow `spec` and, if it failed, why."""
    row = await get_run_summary(_sessions(request), run_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id} not found")
    return RunDetail(
        **_summary_fields(row),
        input=row.input,
        failure_reason=row.failure_reason,
        spec=WorkflowSpec.model_validate(row.spec),
    )


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="createRun",
    responses={
        404: {"description": "No workspace with this id"},
        409: {
            "description": "The workflow uses `github.*` tools, but the workspace has no "
            "GitHub connection. With `new_repo`, a `GithubErrorDetail`: `no_connection`, "
            "`installation_gone`, `personal_account` (repos are created in organisations only) "
            "or `repo_exists`."
        },
        422: {"description": "Invalid request, or the workflow is above the workspace's limits"},
        502: {"description": "With `new_repo`: GitHub could not be asked about the repo"},
        503: {"description": "With `new_repo`: the GitHub App is not configured on the API"},
    },
)
async def create(body: CreateRunRequest, request: Request) -> CreateRunResponse:
    """Queue a run of `workflow`, or of the workflow `template` builds, with `input` for its first
    node, working on `repo` if given. Stream it from `events_url`. A workflow that publishes
    (`github.openPR`) must have a gate between the writer and the publishing node, or it is
    refused with `422`. So is one above the workspace's run limits (`GET
    /workspaces/{id}/policy`), with a `PolicyErrorDetail`; the run keeps the limits it was
    created with. Its budget is `budget_usd`, else the workspace's default; with a budget, every
    agent's model must have a price (`GET /workspaces/{id}/pricing`), or the run is refused the
    same way.

    With `new_repo`, the run works on a repo it creates in the organisation the workspace's GitHub
    App is installed on: two steps come before the workflow's own, a gate (`approve_repo`) and
    `github.createRepo` (`create_repo`), and the run's `repo` is the new repo's URL from the
    start."""
    redis: Redis = request.app.state.redis
    sessions = _sessions(request)
    workspace_id = body.workspace_id or DEFAULT_WORKSPACE_ID
    if await get_workspace(sessions, workspace_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"workspace {workspace_id} not found")
    spec, repo = body.spec(), body.repo
    if body.new_repo is not None:
        spec, repo = await _on_new_repo(request, workspace_id, body)
    elif body.uses_github() and await get_github_installation(sessions, workspace_id) is None:
        raise HTTPException(status.HTTP_409_CONFLICT, _NO_GITHUB)
    try:
        run_id = await create_run(
            sessions,
            spec,
            body.input,
            repo,
            workspace_id,
            template_id=body.template.id if body.template else None,
            template_parameters=dict(body.template.parameters) if body.template else None,
            budget_usd=to_usd(body.budget_usd),
        )
    except PolicyViolationError as e:
        raise _over_policy(e) from e
    await enqueue_run(redis, run_id)
    return CreateRunResponse(
        run_id=run_id, events_url=str(request.url_for("stream_run_events", run_id=run_id))
    )


async def _on_new_repo(
    request: Request, workspace_id: UUID, body: CreateRunRequest
) -> tuple[WorkflowSpec, RepoSource]:
    """The workflow wrapped with the steps that create `body.new_repo`, and the repo's URL. A
    name already taken is refused before any approval is asked for."""
    assert body.new_repo is not None
    github = github_app(request)
    try:
        installation_id, owner = await new_repo_owner(_sessions(request), github, workspace_id)
        full_name = f"{owner}/{body.new_repo.name}"
        taken = await github.get_repo(installation_id, full_name) is not None
    except NewRepoRefused as e:
        raise e.http() from None
    except WorkspaceNotFoundError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"workspace {workspace_id} not found"
        ) from None
    except GithubApiError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from None
    if taken:
        raise _repo_exists(f"repo {full_name} already exists; pick another name")
    spec = wrap_with_create_repo(body.spec(), body.new_repo, owner)
    return spec, RepoSource(url=github_remote(full_name).removesuffix(".git"))


def _repo_exists(message: str) -> HTTPException:
    detail = GithubErrorDetail(code="repo_exists", message=message)
    return HTTPException(status.HTTP_409_CONFLICT, detail.model_dump())


def _over_policy(error: PolicyViolationError) -> HTTPException:
    detail = PolicyErrorDetail(
        message=f"The workflow is above the workspace's run limits: {error}",
        errors=error.errors,
        issues=error.issues,
    )
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail.model_dump())


_NO_GITHUB = (
    "the workflow uses github.* tools, but the workspace has no GitHub connection; "
    "install the GitHub App first"
)


@router.post(
    "/{run_id}/rerun",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="rerunRun",
    responses={
        404: {"description": "No run with this id"},
        409: {
            "description": "The run has not ended yet, its workflow uses `github.*` tools and "
            "the workspace no longer has a GitHub connection, or it created its repo "
            "(`repo_exists`)"
        },
        422: {"description": "The workflow is above the workspace's limits as they are now"},
    },
)
async def rerun(
    run_id: UUID, request: Request, body: RerunRequest | None = None
) -> CreateRunResponse:
    """Queue a new run with the same workflow spec, input, repo and workspace as the ended run
    `run_id` (failed, cancelled or completed), linked to it by `rerun_of`. The original run is
    not changed. The spec is the one the original ran, even if its template has changed since;
    the limits are the workspace's as they are now, and a spec above them is refused with
    `422`. The budget is `budget_usd` if given, else the workspace's default as it is now; the
    original run's spend does not count. A run that created its repo is not rerun: the repo
    exists now, so start a run on it instead."""
    sessions = _sessions(request)
    original = await get_run(sessions, run_id)
    if original is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id} not found")
    if creates_repo(original.spec.root):
        repo = original.repo.url if original.repo else "its repo"
        raise _repo_exists(f"this run created {repo}; start a new run on it instead")
    if uses_github(original.spec) and (
        await get_github_installation(sessions, original.workspace_id) is None
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, _NO_GITHUB)
    try:
        new_id = await create_rerun(sessions, run_id, to_usd(body.budget_usd) if body else None)
    except RunNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except RunNotEndedError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except PolicyViolationError as e:
        raise _over_policy(e) from e
    await enqueue_run(request.app.state.redis, new_id)
    return CreateRunResponse(
        run_id=new_id, events_url=str(request.url_for("stream_run_events", run_id=new_id))
    )


@router.post(
    "/{run_id}/approvals",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="approveRun",
    responses={
        404: {"description": "No run with this id"},
        409: {"description": "The run is not waiting at this gate, or it was already decided"},
        422: {
            "description": "The edits do not fit the files the gate showed",
            "model": EditErrorDetail,
        },
    },
)
async def approve(run_id: UUID, body: ApprovalRequest, request: Request) -> ApprovalResponse:
    """Decide the gate the run is waiting at: `approve` continues the run, `reject` ends it
    `cancelled`. An approval may edit the files the gate showed as editable; the gate commits
    the edits on the writers' branches before the run goes on. The run is queued again; its
    stream carries on with `gate_decided`."""
    decision = GateDecision(decision=body.decision, comment=body.comment, edits=body.edits)
    try:
        recorded = await record_approval(_sessions(request), run_id, body.node_id, decision)
    except RunNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except InvalidEditsError as e:
        detail = EditErrorDetail(code=e.code, message=str(e), path=e.path)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail.model_dump()) from e
    except ApprovalError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    await enqueue_run(request.app.state.redis, run_id)
    return ApprovalResponse(
        run_id=run_id,
        node_id=body.node_id,
        decision=body.decision,
        edited_files=len(recorded.edits),
    )


@router.post(
    "/{run_id}/cancel",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="cancelRun",
    responses={
        404: {"description": "No run with this id"},
        409: {"description": "The run has already ended"},
    },
)
async def cancel(run_id: UUID, request: Request) -> CancelResponse:
    """Ask for the run to be cancelled. Its worker stops it within a few seconds and writes
    `run_cancelled` (reason `cancelled by user`); a queued run, or one waiting at a gate, is ended
    by the worker that picks it up. Asking again before it has ended is accepted."""
    try:
        before = await request_cancel(_sessions(request), run_id)
    except RunNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except RunEndedError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    if before == "waiting":
        # No worker holds a run paused at a gate: queue it, so one ends it.
        await enqueue_run(request.app.state.redis, run_id)
    return CancelResponse(run_id=run_id)


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
