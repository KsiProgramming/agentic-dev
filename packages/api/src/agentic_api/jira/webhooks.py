"""Jira's webhook deliveries (7.3): `POST /jira/webhooks`, one URL for every workspace (Jira
allows one per account).

A delivery is trusted only once its JWT checks out against the app's client secret; before
that nothing is read or stored. The workspaces it is for are those whose webhook on the site
matched it. For each, the delivery is recorded once (a retry is dropped), then dropped if its
project is not picked, if it is a status move a run made itself, or if no rule matches; else
each matching rule starts a run on the issue through `start_run`, as `POST /runs` would.

Only ids, the project, the status moved to and the labels added are read from the payload: the
issue's text never reaches a run's input (principle 5). Nothing from the payload is logged."""

import logging
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import JsonValue, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api.jira.triggers import refusal, run_request
from agentic_api.runs.routes import start_run
from agentic_jira import (
    COMMENT_CREATED,
    MAX_BODY_BYTES,
    WEBHOOK_EVENTS,
    IssueEvent,
    JiraDeliveryError,
    JiraPlatform,
    WorkspaceJira,
    newer,
    own_account_id,
    parse_event,
)
from agentic_store import (
    JiraOrigin,
    TriggerRunActiveError,
    answer_arrived,
    enqueue_run,
    get_jira_connection,
    is_jira_own_move,
    jira_project_allowed,
    jira_webhook_workspaces,
    matching_jira_triggers,
    record_jira_delivery,
    record_jira_trigger_fire,
    set_jira_delivery_outcome,
    waiting_runs,
)

router = APIRouter(tags=["jira"])
log = logging.getLogger(__name__)


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.sessions


@router.post(
    "/jira/webhooks",
    operation_id="receiveJiraWebhook",
    status_code=status.HTTP_202_ACCEPTED,
    response_class=Response,
    responses={
        400: {"description": "A signed delivery that is not an issue event we can read"},
        401: {"description": "The delivery's JWT is missing or does not check out"},
        413: {"description": "The body is over 1 MB"},
        503: {"description": "No Atlassian OAuth app is configured on the API"},
    },
)
async def receive(request: Request) -> Response:
    """A delivery from Jira. Answers `202` once it is verified, whatever came of it; what did is
    recorded per workspace (`jira_deliveries`, and each rule's fires)."""
    jira: JiraPlatform | None = request.app.state.jira
    if jira is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Jira is not configured")
    body = await _body(request)
    try:
        claims = jira.verify_delivery(request.headers.get("authorization"))
    except JiraDeliveryError as exc:
        log.info("jira delivery refused: %s", exc.reason)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "delivery not verified") from None
    try:
        event = parse_event(request.headers, body)
    except JiraDeliveryError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "not an issue event") from None
    if event.event not in WEBHOOK_EVENTS:
        return Response(status_code=status.HTTP_202_ACCEPTED)
    sessions = _sessions(request)
    for workspace_id in await jira_webhook_workspaces(sessions, claims.cloud_id, event.webhook_ids):
        deliver = _deliver_comment if event.event == COMMENT_CREATED else _deliver
        outcome = await deliver(request, workspace_id, claims.cloud_id, event)
        log.info(
            "jira delivery %s on %s for workspace %s: %s",
            event.delivery_id,
            event.issue_key,
            workspace_id,
            outcome,
        )
    return Response(status_code=status.HTTP_202_ACCEPTED)


async def _body(request: Request) -> bytes:
    """The body, refused past `MAX_BODY_BYTES` without reading the rest."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "delivery too large")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "delivery too large")
        chunks.append(chunk)
    return b"".join(chunks)


async def _deliver(request: Request, workspace_id: UUID, cloud_id: str, event: IssueEvent) -> str:
    """What one workspace makes of a delivery; returns its outcome, for the log."""
    sessions = _sessions(request)
    row = await record_jira_delivery(
        sessions, workspace_id, cloud_id, event.delivery_id, event.issue_key
    )
    if row is None:
        return "duplicate"
    if not await jira_project_allowed(sessions, workspace_id, cloud_id, event.project_key):
        await set_jira_delivery_outcome(sessions, row, "project_not_allowed")
        return "project_not_allowed"
    status_to = event.status_to
    if status_to is not None and await is_jira_own_move(
        sessions, workspace_id, cloud_id, event.issue_key, status_to
    ):
        if not event.labels_added:
            await set_jira_delivery_outcome(sessions, row, "own_change")
            return "own_change"
        status_to = None  # the move was ours; a label added with it still counts
    rules = await matching_jira_triggers(
        sessions,
        workspace_id,
        cloud_id,
        event.project_key,
        status_to=status_to,
        labels_added=event.labels_added,
    )
    if not rules:
        await set_jira_delivery_outcome(sessions, row, "no_match")
        return "no_match"
    await set_jira_delivery_outcome(sessions, row, "matched")
    issue = await _issue(sessions, workspace_id, cloud_id, event.issue_key)
    outcomes: list[str] = []
    for rule in rules:
        origin = JiraOrigin(
            trigger_id=rule.id, delivery_row=row, delivery_id=event.delivery_id, issue=issue
        )
        try:
            await start_run(
                request,
                run_request(workspace_id, rule.fields, event.issue_key),
                jira_origin=origin,
            )
            outcomes.append("started")
        except TriggerRunActiveError as active:
            await record_jira_trigger_fire(
                sessions, workspace_id, origin, "already_running", run_id=active.run_id
            )
            outcomes.append("already_running")
        except (HTTPException, ValidationError) as exc:
            await record_jira_trigger_fire(
                sessions, workspace_id, origin, "start_failed", reason=refusal(exc)[:2000]
            )
            outcomes.append("start_failed")
    return ", ".join(outcomes)


async def _deliver_comment(
    request: Request, workspace_id: UUID, cloud_id: str, event: IssueEvent
) -> str:
    """What one workspace makes of a new comment (7.9): it is an answer when a run waits on the
    issue after an older comment and its author is not the connected account; then that run
    goes on. A comment never starts a run. Only ids were read from the delivery."""
    sessions = _sessions(request)
    row = await record_jira_delivery(
        sessions, workspace_id, cloud_id, event.delivery_id, event.issue_key
    )
    if row is None:
        return "duplicate"
    if not await jira_project_allowed(sessions, workspace_id, cloud_id, event.project_key):
        await set_jira_delivery_outcome(sessions, row, "project_not_allowed")
        return "project_not_allowed"
    comment_id = event.comment_id or ""
    waiting = [
        w
        for w in await waiting_runs(
            sessions, issue_key=event.issue_key, cloud_id=cloud_id, workspace_id=workspace_id
        )
        if newer(comment_id, w.after_comment_id)
    ]
    if not waiting:
        await set_jira_delivery_outcome(sessions, row, "no_waiting_run")
        return "no_waiting_run"
    jira: JiraPlatform | None = request.app.state.jira
    keys = request.app.state.keys
    try:
        if jira is None or keys is None:
            raise RuntimeError("no Jira access")
        own = await own_account_id(WorkspaceJira(sessions, keys, jira, workspace_id))
    except Exception:
        # The worker's check finds the answer within minutes; guessing could end a wait early.
        log.warning("could not tell whose comment %s is", comment_id, exc_info=True)
        await set_jira_delivery_outcome(sessions, row, "unverified")
        return "unverified"
    if event.comment_author_id is None or event.comment_author_id == own:
        await set_jira_delivery_outcome(sessions, row, "own_comment")
        return "own_comment"
    await set_jira_delivery_outcome(sessions, row, "answered")
    for run in waiting:
        if await answer_arrived(sessions, run.run_id, run.node_id):
            await enqueue_run(request.app.state.redis, run.run_id)
    return "answered"


async def _issue(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID, cloud_id: str, key: str
) -> dict[str, JsonValue]:
    """The issue as a run keeps it: `{cloud_id, site, key, url}`, from the site the connection
    stored (never from the payload)."""
    connection = await get_jira_connection(sessions, workspace_id)
    sites = connection.sites if connection else ()
    url = next((site.url for site in sites if site.cloud_id == cloud_id), "")
    host = urlsplit(url).netloc or cloud_id
    return {
        "cloud_id": cloud_id,
        "site": host,
        "key": key,
        "url": f"{url.rstrip('/')}/browse/{key}" if url else "",
    }
