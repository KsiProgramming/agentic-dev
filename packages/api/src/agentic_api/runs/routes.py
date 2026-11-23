import asyncio
import contextlib
import hashlib
import logging
from collections.abc import AsyncIterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, status
from fastapi.responses import Response
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import JsonValue, ValidationError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api.github.models import GithubErrorDetail
from agentic_api.github.routes import NewRepoRefused, github_app, new_repo_owner
from agentic_api.runs.listener import RunEventListener
from agentic_api.runs.models import (
    MAX_SPEC_FILE_BYTES,
    SPEC_FILE_EXTENSIONS,
    AnswerCheckResponse,
    ApprovalRequest,
    ApprovalResponse,
    CancelResponse,
    CreateRunRequest,
    CreateRunResponse,
    EditErrorDetail,
    GateBranch,
    GateProtectedAttempt,
    JiraIssueRef,
    PolicyErrorDetail,
    PrReviewRef,
    RerunFrom,
    RerunFromRef,
    RerunRequest,
    RunArtifact,
    RunArtifactContent,
    RunCall,
    RunCounts,
    RunDetail,
    RunGate,
    RunSandbox,
    RunSpecFile,
    RunStatus,
    RunSummary,
    RunSummaryPage,
    RunUsage,
    SavedBranchChanges,
    SpecFileUpload,
    WaitingGate,
    WorkflowRef,
    uses_github,
    uses_jira,
)
from agentic_api.workspaces.models import to_usd
from agentic_engine.agent import IssueBrief, ReviewBrief
from agentic_engine.events import RUN_END_STATUS
from agentic_engine.gate import GateDecision
from agentic_engine.graph import StepNotFoundError
from agentic_engine.graph.compile import ISSUE_KEY
from agentic_engine.spec import (
    ValidationIssue,
    WorkflowSpec,
    call_documents,
    creates_repo,
    messages,
    task_writer_orchestrator,
)
from agentic_engine.spec.ops import OpError
from agentic_engine.templates import wrap_with_create_repo
from agentic_github import (
    GithubApiError,
    InstallationNotFoundError,
    NotAFileError,
    github_remote,
    repo_full_name,
)
from agentic_jira import check_and_answer
from agentic_runtime import Provider
from agentic_sandbox import ARTIFACT_NAME, RepoSource, branch_name
from agentic_store import (
    ANSWERS_EXPIRED_REASON,
    APPROVAL_EXPIRED_REASON,
    DEFAULT_WORKSPACE_ID,
    ApprovalError,
    InvalidCursorError,
    InvalidEditsError,
    InvalidSelectionError,
    JiraOrigin,
    PolicyViolationError,
    ProviderGapError,
    RerunFromStep,
    RunEndedError,
    RunNotEndedError,
    RunNotFoundError,
    RunSummaryRow,
    SandboxInfo,
    SandboxNotKeptError,
    StepNotRerunnableError,
    StoredArtifact,
    WorkflowNotFoundError,
    WorkspaceNotFoundError,
    count_runs,
    create_rerun,
    create_run,
    enqueue_run,
    get_github_installation,
    get_github_user_connection,
    get_jira_connection,
    get_run,
    get_run_artifact,
    get_run_summary,
    get_workflow_version,
    get_workspace,
    list_changed_run_summaries,
    list_run_artifacts,
    list_run_events,
    list_run_summaries,
    pending_gate,
    record_approval,
    request_cancel,
    request_sandbox_removal,
    resolve_workflow,
    run_spec,
    saved_changes,
    waiting_runs,
)

log = logging.getLogger(__name__)
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


def _summary_fields(request: Request, row: RunSummaryRow) -> dict[str, Any]:
    now = datetime.now(UTC)
    active_ms, waiting_ms = row.times.at(now)
    stale_s: float = request.app.state.settings.queue_stale_s
    unclaimed = row.status == "queued" and (
        row.lease_expires_at is None or row.lease_expires_at <= now
    )
    cancel_reason = row.cancel_reason if row.status == "cancelled" else None
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "status": row.status,
        "workflow": WorkflowRef(
            id=row.workflow_id, name=row.workflow_name, version=row.workflow_version
        ),
        "template_id": row.template_id,
        "repo": row.repo,
        "created_at": row.created_at,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "pr_url": row.pr_url,
        "queued_at": row.queued_at,
        "queue_stalled_at": row.queued_at + timedelta(seconds=stale_s) if unclaimed else None,
        "waiting_gate": WaitingGate.model_validate(row.waiting_gate) if row.waiting_gate else None,
        "cancel_reason": cancel_reason,
        "expired": cancel_reason in (APPROVAL_EXPIRED_REASON, ANSWERS_EXPIRED_REASON),
        "rerun_of": row.rerun_of,
        "rerun_from": (
            RerunFromRef(run_id=row.rerun_of, **row.rerun_from)
            if row.rerun_from is not None and row.rerun_of is not None
            else None
        ),
        "trigger": row.trigger,
        "branch": row.branch,
        "jira_issue": JiraIssueRef.model_validate(row.jira_issue) if row.jira_issue else None,
        "copilot_login": row.copilot_login,
        "provider": row.provider,
        "providers": row.providers,
        "pr_review": PrReviewRef.model_validate(row.pr_review) if row.pr_review else None,
        "usage": RunUsage.model_validate(row.usage, from_attributes=True),
        "protected_attempts": row.protected_attempts,
        "active_ms": active_ms,
        "waiting_ms": waiting_ms,
        "measured_at": now,
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
    provider: Annotated[
        Provider | None,
        Query(
            description="Only runs that used this provider (8.3): any of their agents ran on it."
        ),
    ] = None,
    q: Annotated[
        str | None,
        Query(
            max_length=100,
            description="Only runs whose id starts with this (4 characters or more), whose last "
            "pull request has this number (`42` or `#42`), or whose workflow name contains it, "
            "ignoring case.",
        ),
    ] = None,
    cursor: Annotated[str | None, Query(description="`next_cursor` of the previous page.")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> RunSummaryPage:
    """The workspace's runs, newest first, one page at a time. Filters combine; `status` may be
    given several times; `q` finds a run as the command palette does. Status, timings, PR URL
    and the waiting gate come from each run's events."""
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
            search=q,
            provider=provider,
            cursor=cursor,
            limit=limit,
        )
    except InvalidCursorError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    return RunSummaryPage(
        items=[RunSummary(**_summary_fields(request, row)) for row in rows], next_cursor=next_cursor
    )


@router.get(
    "/counts",
    operation_id="countRuns",
    responses={404: {"description": "No workspace with this id"}},
)
async def counts(
    request: Request,
    workspace_id: Annotated[UUID, Depends(existing_workspace)],
    template: Annotated[str | None, Query(description="Only runs of this template id.")] = None,
    repo: Annotated[str | None, Query(description="Only runs on this repo URL.")] = None,
    provider: Annotated[
        Provider | None, Query(description="Only runs that used this provider (8.3).")
    ] = None,
) -> RunCounts:
    """How many runs each saved view of the runs list holds (All, Running, Needs approval,
    Failed), with the same `template` and `repo` filters as `GET /runs`. A run waiting at a gate
    past its expiry is not counted as waiting, even before a worker cancels it."""
    row = await count_runs(
        _sessions(request),
        workspace_id,
        template_id=template,
        repo_url=repo,
        provider=provider,
    )
    return RunCounts(all=row.all, running=row.running, waiting=row.waiting, failed=row.failed)


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
    sent: dict[UUID, tuple[datetime, object]] = {}
    # Subscribe before reading, so a change written in between still wakes us.
    with listener.subscribe_all() as woke:
        while True:
            woke.clear()
            changed = await list_changed_run_summaries(
                sessions, workspace_id, since=watermark - SUMMARY_LOOKBACK
            )
            for updated_at, row in changed:
                summary = RunSummary(**_summary_fields(request, row))
                # Its times grow with the clock, which the client follows by itself.
                seen = (
                    row.times,
                    summary.model_dump(exclude={"active_ms", "waiting_ms", "measured_at"}),
                )
                if (last := sent.get(row.id)) is None or last[1] != seen:
                    yield ServerSentEvent(
                        id=updated_at.isoformat(), event="run_summary", data=summary
                    )
                sent[row.id] = (updated_at, seen)
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
    """One run's summary, with its `input`, its workflow `spec` and the workflows it calls
    (`calls`), and, if it failed, why."""
    row = await get_run_summary(_sessions(request), run_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id} not found")
    return RunDetail(
        **_summary_fields(request, row),
        input=row.input,
        failure_reason=row.failure_reason,
        sandbox=_sandbox(row.sandbox),
        spec=WorkflowSpec.model_validate(row.spec),
        calls=_calls(row.spec, row.subflows),
        jira_brief=IssueBrief.model_validate(row.jira_brief) if row.jira_brief else None,
        pr_review_brief=(
            ReviewBrief.model_validate(row.pr_review_brief) if row.pr_review_brief else None
        ),
        spec_file=RunSpecFile.model_validate(row.spec_file) if row.spec_file else None,
    )


def _sandbox(info: SandboxInfo) -> RunSandbox:
    return RunSandbox.model_validate(info.model_dump())


@router.get(
    "/{run_id}/changes",
    operation_id="listRunChanges",
    responses={404: {"description": "No run with this id"}},
)
async def changes(
    run_id: Annotated[UUID, Depends(existing_run)], request: Request
) -> list[SavedBranchChanges]:
    """What the run's writers changed (12.3): the latest saved version of each of its branches,
    by branch, with the files it changed. Read from what was saved, so it is there after the
    run's sandbox, and its saved commits, are gone."""
    return [
        SavedBranchChanges(
            node_id=task_writer_orchestrator(saved.node_key) or saved.node_key,
            key=saved.node_key,
            branch=saved.branch,
            kind=saved.kind,
            version=saved.version,
            head=saved.head_sha,
            commits=saved.commits,
            saved_at=saved.created_at,
            changes=saved.changes,
            changes_error=saved.changes_error,
            bundle_removed_at=saved.bundle_removed_at,
        )
        for saved in await saved_changes(_sessions(request), run_id)
    ]


@router.delete(
    "/{run_id}/sandbox",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="removeRunSandbox",
    responses={
        404: {"description": "No run with this id"},
        409: {"description": "The run has no kept sandbox: it has not ended, or it is removed"},
    },
)
async def remove_sandbox(run_id: UUID, request: Request) -> RunSandbox:
    """Ask for the run's kept sandbox to be removed now instead of at the end of its time to
    live. A worker removes it within a minute; its saved commits and changes stay. Asking
    again before then is accepted."""
    try:
        info = await request_sandbox_removal(_sessions(request), run_id)
    except RunNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except SandboxNotKeptError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    return _sandbox(info)


def _calls(spec: dict[str, Any] | None, subflows: dict[str, Any] | None) -> dict[str, RunCall]:
    """The run's subflows as they run, from its spec and the copies it was created with."""
    if spec is None or not subflows:
        return {}
    documents = call_documents(run_spec(spec, subflows).root)
    return {node_id: RunCall.model_validate(found) for node_id, found in documents.items()}


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="createRun",
    responses={
        404: {"description": "No workspace with this id, or no such stored workflow or version"},
        409: {
            "description": "The workflow uses `github.*` tools, but the workspace has no "
            "GitHub connection; or `jira.*` tools, but its Jira connection is missing or needs "
            "attention. With `new_repo`, a `GithubErrorDetail`: `no_connection`, "
            "`installation_gone`, `personal_account` (repos are created in organisations only) "
            "or `repo_exists`."
        },
        422: {
            "description": "Invalid request, the workflow is above the workspace's limits, or it "
            "requires an input (`input.required`) and none was given"
        },
        502: {"description": "With `new_repo`: GitHub could not be asked about the repo"},
        503: {"description": "With `new_repo`: the GitHub App is not configured on the API"},
    },
)
async def create(body: CreateRunRequest, request: Request) -> CreateRunResponse:
    """Queue a run of `workflow`, of the workflow `template` builds, or of a version of a stored
    workflow (`stored_workflow`, which the run records), with `input` for its first node,
    working on `repo` if given. Stream it from `events_url`. A workflow that publishes
    (`github.openPR`) must have a gate between the writer and the publishing node, or it is
    refused with `422`. So is one above the workspace's run limits (`GET
    /workspaces/{id}/policy`), with a `PolicyErrorDetail`; the run keeps the limits it was
    created with. Its budget is `budget_usd`, else the workflow's own (`budget_usd` in the spec),
    else the workspace's default; with a budget, every agent's model must have a price (`GET
    /workspaces/{id}/pricing`), or the run is refused the same way.

    With `new_repo`, the run works on a repo it creates in the organisation the workspace's GitHub
    App is installed on: two steps come before the workflow's own, a gate (`approve_repo`) and
    `github.createRepo` (`create_repo`), and the run's `repo` is the new repo's URL from the
    start.

    A workflow that calls other stored workflows (`subflow`, 6.5) runs the versions it names, read
    from the workspace now and kept with the run; one it cannot call (unknown, a cycle, or not
    allowed where it is called) is refused with `422` and the issues. A workflow whose `input` is
    `required` is refused with `422` when `input` is empty: "This workflow needs an input: …".

    A workflow whose `input` is a spec file (`kind: "spec_file"`, 7.7) is given one with
    `spec_file`: uploaded, or a path read from `repo` at its ref now. It is refused with `422`:
    `spec_file_required`, `spec_file_invalid` (its name does not end in `.md` or `.markdown`, it
    is empty, over 256 KB or not UTF-8), `path_invalid`, `path_not_found` or `not_a_file`; and
    `spec_file_unexpected` for another workflow. The run's `input` is the file's name or path."""
    return await start_run(request, body)


@dataclass(frozen=True)
class PreparedRun:
    """A run request that passed every check `POST /runs` makes, ready to create."""

    body: CreateRunRequest
    workspace_id: UUID
    spec: WorkflowSpec
    repo: RepoSource | None
    stored: tuple[str, int] | None
    called: dict[str, Any] | None


async def start_run(
    request: Request, body: CreateRunRequest, *, jira_origin: JiraOrigin | None = None
) -> CreateRunResponse:
    """`POST /runs`'s work: check the request, create the run and queue it. A Jira trigger
    (7.3) starts its runs here too, with `jira_origin`; the run is then `TriggerRunActiveError`
    when the rule has a run going on the issue. Refusals are `HTTPException`s."""
    prepared = await prepare_run(request, body)
    body = prepared.body
    manual_issue: dict[str, JsonValue] | None = None
    if jira_origin is None and prepared.spec.input and prepared.spec.input.kind == "jira_issue":
        manual_issue = await _manual_jira_issue(
            _sessions(request), prepared.workspace_id, body.input
        )
    copilot = await _copilot_connection(request, prepared, jira_origin)
    spec_file = await _spec_file(request, prepared)
    if spec_file is not None:
        body = body.model_copy(update={"input": spec_file["path"] or spec_file["name"]})
    try:
        run_id = await create_run(
            _sessions(request),
            prepared.spec,
            body.input,
            prepared.repo,
            prepared.workspace_id,
            template_id=body.template.id if body.template else None,
            template_parameters=dict(body.template.parameters) if body.template else None,
            budget_usd=to_usd(body.budget_usd),
            trigger=body.trigger,
            workflow_version=prepared.stored,
            subflows=prepared.called,
            jira_origin=jira_origin,
            jira_issue=manual_issue,
            spec_file=spec_file,
            copilot_connection=copilot,
            provider=body.provider,
        )
    except PolicyViolationError as e:
        raise _over_policy(e) from e
    except ProviderGapError as e:
        raise _no_copilot(e) from e
    redis: Redis = request.app.state.redis
    await enqueue_run(redis, run_id)
    return CreateRunResponse(
        run_id=run_id, events_url=str(request.url_for("stream_run_events", run_id=run_id))
    )


async def _copilot_connection(
    request: Request, prepared: PreparedRun, jira_origin: JiraOrigin | None
) -> tuple[UUID, str] | None:
    """`(id, login)` of the personal GitHub connection whose Copilot the run uses (8.2), or `None`
    for a run on Claude. The connection must be the workspace's own and usable; a run no person
    started (a trigger's) is never given one."""
    connection_id = prepared.body.copilot_connection_id
    if connection_id is None:
        return None
    if jira_origin is not None:
        raise _unprocessable(
            "copilot_not_for_triggers",
            "a run a trigger starts has no person whose Copilot it could use",
        )
    info = await get_github_user_connection(
        _sessions(request), prepared.workspace_id, connection_id
    )
    if info is None:
        raise _unprocessable(
            "copilot_connection_not_found",
            f"the workspace has no personal GitHub connection {connection_id}",
        )
    if info.needs_attention is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"copilot_needs_attention: {info.login}'s GitHub connection needs attention "
            f"({info.needs_attention}); connect it again in Settings > Integrations",
        )
    return info.id, info.login


async def prepare_run(request: Request, body: CreateRunRequest) -> PreparedRun:
    """Every check `POST /runs` makes before it creates a run, without creating one (a Jira
    trigger rule is checked with it when it is saved, 7.3). Refusals are `HTTPException`s."""
    sessions = _sessions(request)
    workspace_id = body.workspace_id or DEFAULT_WORKSPACE_ID
    if await get_workspace(sessions, workspace_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"workspace {workspace_id} not found")
    stored: tuple[str, int] | None = None
    if body.stored_workflow is not None:
        body, stored = await _with_stored_spec(sessions, workspace_id, body)
    spec, repo = body.spec(), body.repo
    # A spec file input (7.7) is checked with the file, once the run is about to be created.
    if (
        spec.input is not None
        and spec.input.kind != "spec_file"
        and spec.input.required
        and not body.input.strip()
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"This workflow needs an input: {spec.input.label}",
        )
    if body.new_repo is not None:
        spec, repo = await _on_new_repo(request, workspace_id, body)
    resolved = await resolve_workflow(sessions, workspace_id, spec)
    if resolved.issues:
        raise _cannot_run(resolved.issues)
    spec = resolved.spec
    if body.new_repo is None:
        if resolved.called:
            # The workflows it calls need what their tools need too.
            try:
                body = body.with_spec(spec)
            except ValueError as e:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None
        if body.uses_github() and await get_github_installation(sessions, workspace_id) is None:
            raise HTTPException(status.HTTP_409_CONFLICT, _NO_GITHUB)
    if uses_jira(spec) and not await _jira_ready(sessions, workspace_id):
        raise HTTPException(status.HTTP_409_CONFLICT, _NO_JIRA)
    return PreparedRun(
        body=body,
        workspace_id=workspace_id,
        spec=spec,
        repo=repo,
        stored=stored,
        called=resolved.called or None,
    )


async def _with_stored_spec(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID, body: CreateRunRequest
) -> tuple[CreateRunRequest, tuple[str, int]]:
    """`body` with the spec of the stored workflow version it names, and that version. A version
    with issues is refused as a `workflow` with them would be."""
    ref = body.stored_workflow
    assert ref is not None
    try:
        stored = await get_workflow_version(sessions, workspace_id, ref.id, ref.version)
    except WorkflowNotFoundError:
        missing = f"workflow {ref.id} not found"
        if ref.version is not None:
            missing = f"workflow {ref.id} has no version {ref.version}"
        raise HTTPException(status.HTTP_404_NOT_FOUND, missing) from None
    try:
        body = body.with_spec(WorkflowSpec.model_validate(stored.spec))
    except ValidationError as e:
        reasons = "; ".join(str(err["msg"]).removeprefix("Value error, ") for err in e.errors())
    except ValueError as e:
        reasons = str(e)
    else:
        return body, (stored.workflow_id, stored.version)
    raise HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        f"version {stored.version} of workflow {ref.id} cannot run: {reasons}",
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


def _cannot_run(issues: list[ValidationIssue]) -> HTTPException:
    """A run refused because a workflow its spec calls (6.5) is unknown, calls back into it, or
    cannot run where it is called."""
    errors = messages(issues)
    detail = PolicyErrorDetail(
        message=f"The workflow cannot run: {'; '.join(errors)}", errors=errors, issues=issues
    )
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail.model_dump())


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

_NO_JIRA = (
    "jira_not_connected: the workflow uses jira.* tools, but the workspace's Jira connection "
    "is missing or needs attention; connect it in Settings > Integrations"
)


def _no_copilot(error: ProviderGapError) -> HTTPException:
    """`copilot_connection_required`, naming the agents that run on Copilot (8.3)."""
    nodes = ", ".join(repr(i.node_id) for i in error.issues if i.node_id)
    return _unprocessable(
        "copilot_connection_required",
        f"{nodes} would run on Copilot, which needs a personal GitHub connection with a Copilot "
        "subscription; connect one in Settings > Integrations, or run on Claude",
    )


def _unprocessable(code: str, message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{code}: {message}")


async def _spec_file(request: Request, prepared: PreparedRun) -> dict[str, JsonValue] | None:
    """The spec file a run of a workflow whose input is one is given (7.7): `{source, name,
    path, ref, size, sha256, text}`, uploaded or read from the run's repo at its ref through the
    GitHub App. `None` for any other workflow, or when an optional one is not given. Refusals
    are `HTTPException`s (`POST /runs`)."""
    given, spec = prepared.body.spec_file, prepared.spec
    if spec.input is None or spec.input.kind != "spec_file":
        if given is not None:
            raise _unprocessable(
                "spec_file_unexpected", "this workflow does not take a spec file as its input"
            )
        return None
    if given is None:
        if spec.input.required:
            raise _unprocessable(
                "spec_file_required", f"This workflow needs a spec file: {spec.input.label}"
            )
        return None
    path: str | None = None
    ref: str | None = None
    text = ""
    if isinstance(given, SpecFileUpload):
        name, text = given.name.strip(), given.content
        if "/" in name or "\\" in name:
            raise _unprocessable("spec_file_invalid", "the file's name must not name a folder")
    else:
        path = _repo_path(given.path)
        name = path.rsplit("/", 1)[-1]
        ref = prepared.repo.ref if prepared.repo is not None else None
    if not name.lower().endswith(SPEC_FILE_EXTENSIONS):
        raise _unprocessable("spec_file_invalid", f"{name} is not a Markdown file (.md)")
    if path is not None:  # read only once the name is known to be Markdown
        text = await _repo_spec_file(request, prepared, path)
    try:
        data = text.encode()
    except UnicodeEncodeError:
        raise _unprocessable("spec_file_invalid", f"{name} is not UTF-8 text") from None
    if not text.strip():
        raise _unprocessable("spec_file_invalid", f"{name} is empty")
    if len(data) > MAX_SPEC_FILE_BYTES:
        raise _unprocessable(
            "spec_file_invalid", f"{name} is over {MAX_SPEC_FILE_BYTES // 1024} KB"
        )
    return {
        "source": given.source,
        "name": name,
        "path": path,
        "ref": ref,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "text": text,
    }


def _repo_path(raw: str) -> str:
    """`raw` as a path from the repo's root (a leading `/` dropped), or `path_invalid`."""
    path = raw.strip().lstrip("/")
    parts = path.split("/")
    if (
        not path
        or "\\" in path
        or any(part in {"", ".", ".."} or part.lower() == ".git" for part in parts)
    ):
        raise _unprocessable(
            "path_invalid",
            f"{raw!r} is not a path in the repo; give one like docs/spec.md, with no '..'",
        )
    return path


async def _repo_spec_file(request: Request, prepared: PreparedRun, path: str) -> str:
    """The text of the spec file at `path` in the run's repo at its ref (7.7)."""
    repo = prepared.repo
    full_name = repo_full_name(repo.url) if repo is not None else None
    if repo is None or full_name is None:
        raise _unprocessable(
            "path_invalid", "a spec file from the repo needs the run's repo, on GitHub"
        )
    installation = await get_github_installation(_sessions(request), prepared.workspace_id)
    if installation is None:
        raise HTTPException(status.HTTP_409_CONFLICT, _NO_GITHUB)
    where = f"{full_name} at {repo.ref}" if repo.ref else f"{full_name}'s default branch"
    try:
        found = await github_app(request).file_at(installation, full_name, path, repo.ref)
    except NotAFileError:
        raise _unprocessable("not_a_file", f"{path} is not a file in {where}") from None
    except (GithubApiError, InstallationNotFoundError) as e:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"GitHub could not be asked for {path}: {e}"
        ) from None
    if found is None:
        raise _unprocessable("path_not_found", f"{path} is not in {where}")
    if found.content is None or found.size > MAX_SPEC_FILE_BYTES:
        raise _unprocessable(
            "spec_file_invalid", f"{path} is over {MAX_SPEC_FILE_BYTES // 1024} KB"
        )
    try:
        return found.content.decode()
    except UnicodeDecodeError:
        raise _unprocessable("spec_file_invalid", f"{path} is not UTF-8 text") from None


async def _manual_jira_issue(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID, input: str
) -> dict[str, JsonValue]:
    """The Jira issue a run started by hand works on (7.5), when its workflow's input is an issue
    key (`input.kind: "jira_issue"`): `{cloud_id, site, key, url}`, on the enabled site where the
    workspace picked its project, as a trigger's run keeps it. Refused with `422`
    (`issue_invalid`, `project_not_allowed`, `site_required` when several sites have that
    project) or `409` (`jira_not_connected`)."""
    key = input.strip().upper()
    if not ISSUE_KEY.match(key):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "issue_invalid: this workflow starts from a Jira issue; give its key, such as PROJ-12",
        )
    connection = await get_jira_connection(sessions, workspace_id)
    if connection is None or connection.needs_attention is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, _NO_JIRA)
    project = key.rsplit("-", 1)[0]
    sites = [
        site
        for site in connection.sites
        if site.enabled and any(p.key.upper() == project for p in site.projects)
    ]
    if not sites:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"project_not_allowed: {project} is not a project this workspace picked for Jira "
            "(Settings > Integrations)",
        )
    if len(sites) > 1:
        hosts = ", ".join(urlsplit(site.url).netloc or site.cloud_id for site in sites)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"site_required: {project} is picked on several Jira sites ({hosts}); start the run "
            "from a trigger on the site you mean",
        )
    site = sites[0]
    return {
        "cloud_id": site.cloud_id,
        "site": urlsplit(site.url).netloc or site.cloud_id,
        "key": key,
        "url": f"{site.url.rstrip('/')}/browse/{key}",
    }


async def _jira_ready(sessions: async_sessionmaker[AsyncSession], workspace_id: UUID) -> bool:
    """Whether the workspace's Jira connection can be used by a run's `jira.*` tools (7.2)."""
    connection = await get_jira_connection(sessions, workspace_id)
    return connection is not None and connection.needs_attention is None


@router.post(
    "/{run_id}/rerun",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="rerunRun",
    responses={
        404: {"description": "No run with this id"},
        409: {
            "description": "The run has not ended yet, its workflow uses `github.*` tools and "
            "the workspace no longer has a GitHub connection, or it created its repo "
            "(`repo_exists`); with `from`, the run never reached the step, its code before it "
            "can no longer be restored, or the step left no uncommitted work for `use_wip`"
        },
        422: {
            "description": "The workflow is above the workspace's limits as they are now; with "
            "`from`, the node is not a top-level step or a parameter cannot be set"
        },
    },
)
async def rerun(
    run_id: UUID, request: Request, body: RerunRequest | None = None
) -> CreateRunResponse:
    """Queue a new run with the same workflow spec, input, repo and workspace as the ended run
    `run_id` (failed, cancelled or completed), linked to it by `rerun_of`. The original run is
    not changed. The spec is the one the original ran, even if its template has changed since;
    the limits are the workspace's as they are now, and a spec above them is refused with
    `422`. The budget is `budget_usd` if given, else the workflow's own, else the workspace's
    default as it is now; the original run's spend does not count. A run that created its repo
    is not rerun: the repo exists now, so start a run on it instead.

    With `from` (12.4) the new run starts at that top-level step, from the original's checkpoint
    before it and with the code the original's writers had then; the steps before it are
    neither run nor charged again. `set_params` change that step's parameters only."""
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
    if uses_jira(original.spec) and not await _jira_ready(sessions, original.workspace_id):
        raise HTTPException(status.HTTP_409_CONFLICT, _NO_JIRA)
    try:
        new_id = await create_rerun(
            sessions,
            run_id,
            to_usd(body.budget_usd) if body else None,
            _from_step(body.from_) if body and body.from_ else None,
        )
    except RunNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except (RunNotEndedError, StepNotRerunnableError) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except (StepNotFoundError, OpError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    except PolicyViolationError as e:
        raise _over_policy(e) from e
    except ProviderGapError as e:
        raise _no_copilot(e) from e
    await enqueue_run(request.app.state.redis, new_id)
    return CreateRunResponse(
        run_id=new_id, events_url=str(request.url_for("stream_run_events", run_id=new_id))
    )


def _from_step(body: RerunFrom) -> RerunFromStep:
    return RerunFromStep(
        node_id=body.node_id,
        set_params=[(p.path, p.value) for p in body.set_params],
        use_wip=body.use_wip,
    )


@router.get(
    "/{run_id}/gate",
    operation_id="getRunGate",
    responses={
        404: {"description": "No run with this id"},
        409: {"description": "The run is not waiting at a gate, or its approval expired"},
    },
)
async def gate(run_id: UUID, request: Request) -> RunGate:
    """The gate the run waits at, for an approver to review without the run's events: its
    title, prompt and artifact, the files the writers changed, when it expires, and the
    branches approving lets go on."""
    sessions = _sessions(request)
    try:
        pending = await pending_gate(sessions, run_id)
    except RunNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except ApprovalError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    row = await get_run_summary(sessions, run_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id} not found")
    writers = dict.fromkeys(change.node_id for change in pending.changes)
    return RunGate(
        node_id=pending.node_id,
        title=pending.title,
        prompt=pending.prompt,
        artifact=pending.artifact,
        changes=pending.changes,
        changes_error=pending.changes_error,
        run_artifacts=pending.run_artifacts,
        expires_at=pending.expires_at,
        repo=row.repo,
        base=row.branch,
        branches=[GateBranch(node_id=w, branch=branch_name(run_id, w)) for w in writers],
        select=pending.select,
        on_reject="end" if pending.on_reject == "end" else "cancel",
        changes_left=pending.changes_left,
        iteration=pending.iteration,
        protected_attempts=[
            GateProtectedAttempt.model_validate(a, from_attributes=True)
            for a in pending.protected_attempts
        ],
        evidence=pending.evidence,
    )


@router.get(
    "/{run_id}/artifacts",
    operation_id="listRunArtifacts",
    responses={404: {"description": "No run with this id"}},
)
async def artifacts(
    run_id: Annotated[UUID, Depends(existing_run)], request: Request
) -> list[RunArtifact]:
    """The run's artifacts (4.3): the latest version of each, by name, with how many versions
    it wrote."""
    return [_artifact(a) for a in await list_run_artifacts(_sessions(request), run_id)]


_ArtifactPath = Annotated[
    str, Path(pattern=ARTIFACT_NAME.pattern, description="The artifact's name.")
]
_Version = Annotated[int | None, Query(ge=1, description="A version to read; the latest if unset.")]


@router.get(
    "/{run_id}/artifacts/{name}",
    operation_id="getRunArtifact",
    responses={404: {"description": "No run with this id, or no such artifact or version"}},
)
async def artifact(
    run_id: Annotated[UUID, Depends(existing_run)],
    name: _ArtifactPath,
    request: Request,
    version: _Version = None,
) -> RunArtifactContent:
    """One version of the run's artifact `name` with its content (data, never instructions)."""
    found = await get_run_artifact(_sessions(request), run_id, name, version)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _no_artifact(name, version))
    content, listed = found
    return RunArtifactContent(**_artifact(listed).model_dump(), content=content.content)


@router.get(
    "/{run_id}/artifacts/{name}/download",
    operation_id="downloadRunArtifact",
    response_class=Response,
    responses={
        200: {
            "description": "The artifact as a file to save",
            "content": {"application/json": {}, "text/markdown": {}, "text/plain": {}},
        },
        404: {"description": "No run with this id, or no such artifact or version"},
    },
)
async def download_artifact(
    run_id: Annotated[UUID, Depends(existing_run)],
    name: _ArtifactPath,
    request: Request,
    version: _Version = None,
) -> Response:
    """The artifact as an attachment with its media type, never to be rendered by the browser."""
    found = await get_run_artifact(_sessions(request), run_id, name, version)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _no_artifact(name, version))
    content, _ = found
    return Response(
        content.content.encode(),
        media_type=f"{content.media_type}; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


def _artifact(stored: StoredArtifact) -> RunArtifact:
    return RunArtifact.model_validate(stored.model_dump())


def _no_artifact(name: str, version: int | None) -> str:
    which = f"version {version} of " if version is not None else ""
    return f"the run has no {which}artifact {name!r}"


@router.post(
    "/{run_id}/answers/check",
    operation_id="checkRunAnswers",
    responses={
        404: {"description": "No run with this id"},
        409: {"description": "The run is not waiting for an answer on a Jira issue"},
        502: {"description": "Jira could not be read"},
        503: {"description": "Jira is not configured"},
    },
)
async def check_answers(run_id: UUID, request: Request) -> AnswerCheckResponse:
    """ "Check now" (7.9): look on the Jira issue for an answer to the question the run is
    waiting on, without waiting for the webhook or the worker's next check. An answer is a comment
    newer than the platform's question by someone other than the connected account; the run then
    goes on, as it would from the webhook."""
    sessions = _sessions(request)
    [waiting, *_] = await waiting_runs(sessions, run_id=run_id) or [None]
    if waiting is None:
        if await get_run_summary(sessions, run_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id} not found")
        raise HTTPException(status.HTTP_409_CONFLICT, "the run is not waiting for an answer")
    jira = request.app.state.jira
    keys = request.app.state.keys
    if jira is None or keys is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Jira is not configured")
    try:
        found = await check_and_answer(sessions, keys, jira, request.app.state.redis, waiting)
    except Exception as e:
        log.warning("could not check run %s for an answer", run_id, exc_info=True)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Jira could not be read") from e
    return AnswerCheckResponse(run_id=run_id, found=found)


@router.post(
    "/{run_id}/approvals",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="approveRun",
    responses={
        404: {"description": "No run with this id"},
        409: {
            "description": "The run is not waiting at this gate, the gate was already decided, "
            "or its approval expired"
        },
        422: {
            "description": "The edits do not fit the files the gate showed, or the selection "
            "the items it showed",
            "model": EditErrorDetail,
        },
    },
)
async def approve(run_id: UUID, body: ApprovalRequest, request: Request) -> ApprovalResponse:
    """Decide the gate the run is waiting at: `approve` continues the run, `reject` ends it
    `cancelled`. An approval may edit the files the gate showed as editable; the gate commits
    the edits on the writers' branches before the run goes on. The run is queued again; its
    stream carries on with `gate_decided`. A gate past its `expires_at` takes no decision. A
    selection gate's approval names the items chosen (`selection`, 6.7); with `on_reject: end`
    a rejection completes the run instead of cancelling it."""
    try:
        decision = GateDecision(
            decision=body.decision,
            comment=body.comment,
            comments=body.comments,
            edits=body.edits,
            selection=body.selection,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    try:
        recorded = await record_approval(_sessions(request), run_id, body.node_id, decision)
    except RunNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except InvalidEditsError as e:
        detail = EditErrorDetail(code=e.code, message=str(e), path=e.path)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail.model_dump()) from e
    except InvalidSelectionError as e:
        detail = EditErrorDetail(code=e.code, message=str(e))
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
