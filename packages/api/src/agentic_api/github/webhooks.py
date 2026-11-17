"""The GitHub App's webhook deliveries (7.6): `POST /github/webhooks`, one URL for the deployment.

A delivery is trusted only once its `X-Hub-Signature-256` checks out against
`GITHUB_WEBHOOK_SECRET`; before that nothing is read or stored. It is recorded once by its
`X-GitHub-Delivery` (a redelivery is dropped). Only a comment on a pull request that is the command
`@<app slug> fix this`, from a person (not a bot) with write access to the repo, can start
anything: a follow-up run of the latest run on that pull request, from its workflow's
`on_review.from` (`agentic_store.rerun.create_rerun` with a `FollowUp`).

The comment's body is read only to match the command; it is never stored, logged or returned
(principle 5). A command that starts a follow-up gets the 👀 reaction, one refused because of the
pull request's state gets 😕 (`busy`, `limit`, `pr_closed`), and every command is audited once
(`github.review_received`, `github.review_ignored` with its reason)."""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import JsonValue, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api.settings import Settings
from agentic_engine.graph import StepNotFoundError
from agentic_engine.policy import effective_policy
from agentic_engine.spec.ops import OpError
from agentic_github import (
    DELIVERY_HEADER,
    EVENT_HEADER,
    SIGNATURE_HEADER,
    WRITE_PERMISSIONS,
    GithubApiError,
    GithubDeliveryError,
    GithubPlatform,
    InstallationNotFoundError,
    ReviewEvent,
    parse_review_event,
    verify_signature,
)
from agentic_github.webhooks import MAX_BODY_BYTES
from agentic_store import (
    FollowUp,
    IgnoreReason,
    PolicyViolationError,
    RerunFromStep,
    ReviewBusyError,
    ReviewLimitError,
    RunNotEndedError,
    StepNotRerunnableError,
    audit_review_ignored,
    create_rerun,
    enqueue_run,
    get_policy_overrides,
    github_workspaces,
    latest_pr_run,
    record_github_delivery,
    set_github_delivery_outcome,
)

router = APIRouter(tags=["github"])
log = logging.getLogger(__name__)

FAKE_APP_SLUG = "agentic-dev"
"""The slug the fake GitHub App answers to (`AGENTIC_GITHUB=fake`)."""

ACCEPTED = "eyes"
REFUSED = "confused"
_REFUSED_WITH_REACTION: frozenset[IgnoreReason] = frozenset({"busy", "limit", "pr_closed"})


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.sessions


@router.post(
    "/github/webhooks",
    operation_id="receiveGithubWebhook",
    status_code=status.HTTP_202_ACCEPTED,
    response_class=Response,
    responses={
        400: {
            "description": "A signed delivery with no delivery id, or a comment event we "
            "cannot read"
        },
        401: {"description": "`X-Hub-Signature-256` is missing or does not check out"},
        413: {"description": "The body is over 2 MB"},
        503: {"description": "No GitHub App or no `GITHUB_WEBHOOK_SECRET` is configured"},
    },
)
async def receive(request: Request) -> Response:
    """A delivery from the GitHub App. Answers `202` once it is verified, whatever came of it;
    what did is recorded (`github_deliveries`) and, for a `@<app> fix this` command, audited."""
    settings: Settings = request.app.state.settings
    github: GithubPlatform | None = request.app.state.github
    secret: SecretStr | None = settings.github_webhook_secret
    slug = app_slug(settings)
    if github is None or secret is None or slug is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "GitHub webhooks are not set up")
    body = await _body(request)
    if not verify_signature(secret.get_secret_value(), body, request.headers.get(SIGNATURE_HEADER)):
        log.info("github delivery refused: signature")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "delivery not verified")
    delivery_id = (request.headers.get(DELIVERY_HEADER) or "").strip()
    event = (request.headers.get(EVENT_HEADER) or "").strip()
    if not delivery_id or len(delivery_id) > 64:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no delivery id")
    sessions = _sessions(request)
    if not await record_github_delivery(sessions, delivery_id, event):
        log.info("github delivery %s: duplicate", delivery_id)
        return Response(status_code=status.HTTP_202_ACCEPTED)
    try:
        parsed = parse_review_event(event, delivery_id, body, slug)
    except GithubDeliveryError:
        await set_github_delivery_outcome(sessions, delivery_id, "unreadable")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "not a comment event") from None
    if parsed is None or parsed.from_bot or not parsed.command:
        await set_github_delivery_outcome(sessions, delivery_id, "ignored")
        return Response(status_code=status.HTTP_202_ACCEPTED)
    outcome = await _follow_up(request, github, parsed)
    await set_github_delivery_outcome(sessions, delivery_id, outcome)
    log.info("github delivery %s on %s: %s", delivery_id, parsed.pr_url, outcome)
    return Response(status_code=status.HTTP_202_ACCEPTED)


def app_slug(settings: Settings) -> str | None:
    """The slug the command names (`@<slug> fix this`)."""
    if settings.github == "fake":
        return settings.github_app_slug or FAKE_APP_SLUG
    return settings.github_app_slug


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


async def _follow_up(request: Request, github: GithubPlatform, event: ReviewEvent) -> str:
    """What a `@<app> fix this` command came to: `started`, or why it started nothing."""
    sessions = _sessions(request)
    workspaces = await github_workspaces(sessions, event.installation_id)
    if not workspaces:
        return "no_workspace"  # no workspace to audit it in
    details: dict[str, JsonValue] = {
        "delivery_id": event.delivery_id,
        "pr_url": event.pr_url,
        "author": event.sender_login,
        "comment_url": event.comment_url,
    }

    async def ignored(
        reason: IgnoreReason, in_workspaces: list[UUID], run_id: UUID | None = None
    ) -> str:
        await audit_review_ignored(sessions, in_workspaces, reason, details, run_id)
        if reason in _REFUSED_WITH_REACTION:
            await _react(github, event, REFUSED)
        return reason

    try:
        role = await github.repo_permission(
            event.installation_id, event.full_name, event.sender_login
        )
    except (GithubApiError, InstallationNotFoundError) as e:
        log.warning("github delivery %s: cannot read the sender's role (%s)", event.delivery_id, e)
        role = "none"
    if role not in WRITE_PERMISSIONS:
        return await ignored("not_allowed", workspaces)
    latest = await latest_pr_run(sessions, workspaces, event.pr_url)
    if latest is None:
        return await ignored("no_run", workspaces)
    here = [latest.workspace_id]
    on_review = latest.spec.on_review
    if on_review is None:
        return await ignored("not_enabled", here, latest.id)
    if latest.head_branch is None or latest.head_sha is None or latest.pushed_at is None:
        return await ignored("no_head", here, latest.id)
    try:
        pull = await github.pull_request(event.installation_id, event.full_name, event.pr_number)
    except (GithubApiError, InstallationNotFoundError) as e:
        log.warning("github delivery %s: cannot read the pull request (%s)", event.delivery_id, e)
        pull = None
    if pull is None or not pull.is_open:
        return await ignored("pr_closed", here, latest.id)
    policy = effective_policy(await get_policy_overrides(sessions, latest.workspace_id))
    follow_up = FollowUp(
        pr_review={
            "pr_url": event.pr_url,
            "full_name": event.full_name,
            "number": event.pr_number,
            "head_branch": latest.head_branch,
            "after_sha": latest.head_sha,
            "after_at": latest.pushed_at.isoformat(),
            "kind": event.kind,
            "comment_id": event.comment_id,
            "comment_url": event.comment_url,
            "author": event.sender_login,
            "delivery_id": event.delivery_id,
        },
        review_rounds=policy.review_rounds,
    )
    try:
        new_id = await create_rerun(
            sessions,
            latest.id,
            from_step=RerunFromStep(node_id=on_review.from_),
            follow_up=follow_up,
        )
    except (ReviewBusyError, RunNotEndedError):
        return await ignored("busy", here, latest.id)
    except ReviewLimitError:
        return await ignored("limit", here, latest.id)
    except (StepNotRerunnableError, StepNotFoundError, OpError, PolicyViolationError) as e:
        log.warning("github delivery %s: no follow-up of %s (%s)", event.delivery_id, latest.id, e)
        details["error"] = str(e)[:500]
        return await ignored("start_failed", here, latest.id)
    await enqueue_run(request.app.state.redis, new_id)
    await _react(github, event, ACCEPTED)
    return "started"


async def _react(github: GithubPlatform, event: ReviewEvent, content: str) -> None:
    """React to the command; a reaction that fails is logged, never retried."""
    try:
        await github.add_reaction(
            event.installation_id, event.full_name, event.kind, event.comment_id, content
        )
    except (GithubApiError, InstallationNotFoundError) as e:
        log.warning("github delivery %s: no reaction (%s)", event.delivery_id, e)
