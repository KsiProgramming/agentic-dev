"""`POST /github/webhooks` (7.6): a signed `@<app> fix this` comment on a run's pull request, from
someone with write access, starts a follow-up run of its review loop; anything else starts
nothing, and every command is audited once. The comment's text is never stored or logged."""

import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from itertools import count
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api.app import create_app
from agentic_api.settings import Settings
from agentic_engine.policy import PolicyOverrides
from agentic_engine.spec import WorkflowSpec
from agentic_engine.templates.sdd import SddParams, build_sdd_spec
from agentic_github import FakeGithubApp, PullRequestState, sign
from agentic_sandbox import RepoSource
from agentic_store import (
    AuditEvent,
    GithubDelivery,
    Run,
    RunEventRow,
    create_run,
    put_github_connection,
    replace_policy_overrides,
)

pytestmark = pytest.mark.integration

type Sessions = async_sessionmaker[AsyncSession]

SECRET = "whsec-test-0001"
REPO = "acme/hello"
HEAD_SHA = "c" * 40
BASE = "a" * 40
COMMAND = "Please @agentic-dev fix this: the title is wrong. SECRET-TEXT-42"
_ids = count(1)


@pytest.fixture
def github() -> FakeGithubApp:
    fake = FakeGithubApp("http://test")
    fake.default_permission = "none"
    return fake


@pytest.fixture
async def client(
    postgres_url: str, redis_url: str, sessions: Sessions, github: FakeGithubApp
) -> AsyncIterator[AsyncClient]:
    """`sessions` migrates the database first."""
    settings = Settings(
        database_url=postgres_url,
        redis_url=redis_url,
        github_webhook_secret=SECRET,  # pyright: ignore[reportArgumentType]
        github_app_slug="agentic-dev",
    )
    app = create_app(settings)
    app.state.github = github
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c


class Pr:
    """A workspace linked to its own installation, with an ended SDD run that opened a pull
    request on `acme/hello`."""

    def __init__(self, workspace_id: UUID, installation_id: int, number: int, run_id: UUID):
        self.workspace_id = workspace_id
        self.installation_id = installation_id
        self.number = number
        self.run_id = run_id

    @property
    def url(self) -> str:
        return f"https://github.com/{REPO}/pull/{self.number}"


def sdd(on_review: bool = True) -> WorkflowSpec:
    document = build_sdd_spec(SddParams()).model_dump(mode="json", by_alias=True)
    if on_review:
        document["on_review"] = {"from": "review_loop"}
    return WorkflowSpec.model_validate(document)


async def opened_pr(
    client: AsyncClient,
    sessions: Sessions,
    github: FakeGithubApp,
    *,
    on_review: bool = True,
) -> Pr:
    created = await client.post("/workspaces", json={"name": f"pr-{uuid4().hex[:8]}"})
    assert created.status_code == 201
    workspace_id = UUID(created.json()["id"])
    installation_id = 1000 + next(_ids)
    await put_github_connection(sessions, workspace_id, installation_id, "acme")
    run_id = await create_run(
        sessions,
        sdd(on_review),
        "API-1",
        RepoSource(url=f"https://github.com/{REPO}"),
        workspace_id=workspace_id,
    )
    number = next(_ids)
    url = f"https://github.com/{REPO}/pull/{number}"
    now = datetime.now(UTC)
    async with sessions.begin() as session:
        await session.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(status="completed", base_sha=BASE, pr_url=url)
        )
        session.add(
            RunEventRow(
                run_id=run_id, seq=1, type="node_started", node_id="review_loop", payload={},
                created_at=now,
            )
        )  # fmt: skip
        session.add(
            RunEventRow(
                run_id=run_id,
                seq=2,
                type="pr_opened",
                node_id="publish",
                payload={
                    "url": url,
                    "number": number,
                    "head": f"agent/{run_id}/implement",
                    "base": "main",
                    "commit": HEAD_SHA,
                },
                created_at=now,
            )
        )
    github.register_pull(REPO, number, f"agent/{run_id}/implement", "main")
    return Pr(workspace_id, installation_id, number, run_id)


def comment_event(
    pr: Pr, body: str = COMMAND, *, login: str = "alice", sender_type: str = "User"
) -> dict[str, Any]:
    comment_id = 500 + next(_ids)
    return {
        "action": "created",
        "issue": {"number": pr.number, "pull_request": {"url": "https://api.github.com/x"}},
        "comment": {
            "id": comment_id,
            "body": body,
            "html_url": f"{pr.url}#issuecomment-{comment_id}",
            "user": {"login": login, "type": sender_type},
        },
        "repository": {"full_name": REPO},
        "installation": {"id": pr.installation_id},
        "sender": {"login": login, "id": 7, "type": sender_type},
    }


async def deliver(
    client: AsyncClient,
    payload: dict[str, Any],
    *,
    event: str = "issue_comment",
    delivery: str | None = None,
    signature: str | None = None,
) -> tuple[int, str]:
    body = json.dumps(payload).encode()
    delivery = delivery or str(uuid4())
    headers = {
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery,
        "X-Hub-Signature-256": signature if signature is not None else sign(SECRET, body),
        "Content-Type": "application/json",
    }
    response = await client.post("/github/webhooks", content=body, headers=headers)
    return response.status_code, delivery


async def runs_of(sessions: Sessions, workspace_id: UUID) -> list[Run]:
    async with sessions() as session:
        rows = await session.scalars(
            select(Run).where(Run.workspace_id == workspace_id).order_by(Run.created_at)
        )
        return list(rows)


async def audits(sessions: Sessions, workspace_id: UUID) -> list[AuditEvent]:
    async with sessions() as session:
        rows = await session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.workspace_id == workspace_id,
                AuditEvent.action.in_(["github.review_received", "github.review_ignored"]),
            )
            .order_by(AuditEvent.id)
        )
        return list(rows)


async def outcome(sessions: Sessions, delivery: str) -> str | None:
    async with sessions() as session:
        row = await session.get(GithubDelivery, delivery)
    return row.outcome if row is not None else None


async def test_a_command_from_a_writer_starts_a_follow_up_of_the_review_loop(
    client: AsyncClient,
    sessions: Sessions,
    github: FakeGithubApp,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    pr = await opened_pr(client, sessions, github)
    github.permissions["alice"] = "write"
    payload = comment_event(pr)

    status, delivery = await deliver(client, payload)

    assert status == 202
    original, follow_up = await runs_of(sessions, pr.workspace_id)
    assert follow_up.rerun_of == original.id == pr.run_id
    assert follow_up.trigger == "github"
    assert follow_up.status == "queued"
    assert follow_up.rerun_from == {"node_id": "review_loop", "use_wip": False, "edited": []}
    assert follow_up.base_sha == BASE
    comment_id = payload["comment"]["id"]
    assert follow_up.pr_review == {
        "pr_url": pr.url,
        "full_name": REPO,
        "number": pr.number,
        "head_branch": f"agent/{pr.run_id}/implement",
        "after_sha": HEAD_SHA,
        "after_at": follow_up.pr_review["after_at"] if follow_up.pr_review else None,
        "kind": "issue_comment",
        "comment_id": comment_id,
        "comment_url": f"{pr.url}#issuecomment-{comment_id}",
        "author": "alice",
        "delivery_id": delivery,
    }
    assert github.reactions == [(REPO, "issue_comment", comment_id, "eyes")]
    [received] = await audits(sessions, pr.workspace_id)
    assert received.action == "github.review_received"
    assert received.run_id == follow_up.id
    assert received.details["pr_url"] == pr.url
    assert received.details["follows"] == str(pr.run_id)
    assert await outcome(sessions, delivery) == "started"
    detail = (await client.get(f"/runs/{follow_up.id}")).json()
    assert detail["trigger"] == "github"
    assert detail["rerun_of"] == str(pr.run_id)
    assert detail["pr_review"] == {
        "pr_url": pr.url,
        "number": pr.number,
        "kind": "issue_comment",
        "comment_url": f"{pr.url}#issuecomment-{comment_id}",
        "author": "alice",
    }
    assert detail["pr_review_brief"] is None  # read by the worker, before the first step
    # The comment's text is nowhere: not in the run, the audit log, the delivery or the logs.
    stored = json.dumps([follow_up.pr_review, follow_up.input, received.details])
    assert "SECRET-TEXT-42" not in stored
    assert "SECRET-TEXT-42" not in caplog.text
    assert caplog.text, "nothing was logged, so the log check proves nothing"


async def test_a_redelivery_starts_nothing_more(
    client: AsyncClient, sessions: Sessions, github: FakeGithubApp
) -> None:
    pr = await opened_pr(client, sessions, github)
    github.permissions["alice"] = "admin"
    payload = comment_event(pr)
    _, delivery = await deliver(client, payload)

    status, _ = await deliver(client, payload, delivery=delivery)

    assert status == 202
    assert len(await runs_of(sessions, pr.workspace_id)) == 2
    assert len(await audits(sessions, pr.workspace_id)) == 1


@pytest.mark.parametrize("signature", ["", "sha256=" + "0" * 64, "sha1=abc"])
async def test_a_delivery_that_is_not_signed_with_the_secret_is_refused(
    client: AsyncClient, sessions: Sessions, github: FakeGithubApp, signature: str
) -> None:
    pr = await opened_pr(client, sessions, github)
    github.permissions["alice"] = "write"

    status, delivery = await deliver(client, comment_event(pr), signature=signature)

    assert status == 401
    assert await outcome(sessions, delivery) is None
    assert len(await runs_of(sessions, pr.workspace_id)) == 1


async def test_with_no_secret_the_receiver_is_unavailable(
    postgres_url: str, redis_url: str, sessions: Sessions
) -> None:
    app = create_app(Settings(database_url=postgres_url, redis_url=redis_url))
    app.state.github = FakeGithubApp("http://test")
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        response = await c.post("/github/webhooks", content=b"{}")
    assert response.status_code == 503


@pytest.mark.parametrize(
    ("body", "login", "sender_type"),
    [
        ("Looks good, thanks!", "alice", "User"),
        ("@agentic-dev fix that later", "alice", "User"),
        ("@agentic-devs fix this", "alice", "User"),
        (COMMAND, "renovate[bot]", "Bot"),
        (COMMAND, "agentic-dev[bot]", "Bot"),
    ],
)
async def test_comments_that_are_not_a_command_from_a_person_start_nothing(
    client: AsyncClient,
    sessions: Sessions,
    github: FakeGithubApp,
    body: str,
    login: str,
    sender_type: str,
) -> None:
    pr = await opened_pr(client, sessions, github)
    github.default_permission = "admin"

    status, delivery = await deliver(
        client, comment_event(pr, body, login=login, sender_type=sender_type)
    )

    assert status == 202
    assert len(await runs_of(sessions, pr.workspace_id)) == 1
    assert await audits(sessions, pr.workspace_id) == []
    assert await outcome(sessions, delivery) == "ignored"
    assert github.reactions == []


async def test_the_command_is_case_insensitive_and_read_from_reviews_and_inline_comments(
    client: AsyncClient, sessions: Sessions, github: FakeGithubApp
) -> None:
    pr = await opened_pr(client, sessions, github)
    github.permissions["alice"] = "maintain"
    review = {
        "action": "created",
        "pull_request": {"number": pr.number},
        "comment": {
            "id": 77,
            "body": "This line is off. @Agentic-Dev FIX THIS",
            "html_url": f"{pr.url}#discussion_r77",
            "path": "app.py",
        },
        "repository": {"full_name": REPO},
        "installation": {"id": pr.installation_id},
        "sender": {"login": "alice", "id": 7, "type": "User"},
    }

    status, _ = await deliver(client, review, event="pull_request_review_comment")

    assert status == 202
    _, follow_up = await runs_of(sessions, pr.workspace_id)
    assert follow_up.pr_review is not None
    assert follow_up.pr_review["kind"] == "review_comment"
    assert follow_up.pr_review["comment_id"] == 77
    assert github.reactions == [(REPO, "review_comment", 77, "eyes")]


async def test_someone_without_write_access_is_not_allowed(
    client: AsyncClient, sessions: Sessions, github: FakeGithubApp
) -> None:
    pr = await opened_pr(client, sessions, github)
    github.permissions["mallory"] = "triage"

    _, delivery = await deliver(client, comment_event(pr, login="mallory"))

    assert len(await runs_of(sessions, pr.workspace_id)) == 1
    [ignored] = await audits(sessions, pr.workspace_id)
    assert (ignored.action, ignored.details["reason"]) == ("github.review_ignored", "not_allowed")
    assert ignored.details["author"] == "mallory"
    assert await outcome(sessions, delivery) == "not_allowed"
    assert github.reactions == []  # strangers are told nothing


async def test_a_pull_request_no_run_opened_is_no_run(
    client: AsyncClient, sessions: Sessions, github: FakeGithubApp
) -> None:
    pr = await opened_pr(client, sessions, github)
    github.permissions["alice"] = "write"
    other = Pr(pr.workspace_id, pr.installation_id, 99_999, pr.run_id)

    _, delivery = await deliver(client, comment_event(other))

    [ignored] = await audits(sessions, pr.workspace_id)
    assert ignored.details["reason"] == "no_run"
    assert await outcome(sessions, delivery) == "no_run"


async def test_a_workflow_without_on_review_is_not_enabled(
    client: AsyncClient, sessions: Sessions, github: FakeGithubApp
) -> None:
    pr = await opened_pr(client, sessions, github, on_review=False)
    github.permissions["alice"] = "write"

    await deliver(client, comment_event(pr))

    [ignored] = await audits(sessions, pr.workspace_id)
    assert ignored.details["reason"] == "not_enabled"
    assert ignored.run_id == pr.run_id
    assert github.reactions == []


async def test_a_second_command_while_the_follow_up_runs_is_busy(
    client: AsyncClient, sessions: Sessions, github: FakeGithubApp
) -> None:
    pr = await opened_pr(client, sessions, github)
    github.permissions["alice"] = "write"
    await deliver(client, comment_event(pr))
    second = comment_event(pr)

    _, delivery = await deliver(client, second)

    assert len(await runs_of(sessions, pr.workspace_id)) == 2
    _, ignored = await audits(sessions, pr.workspace_id)
    assert ignored.details["reason"] == "busy"
    assert await outcome(sessions, delivery) == "busy"
    assert github.reactions[-1] == (REPO, "issue_comment", second["comment"]["id"], "confused")


async def test_the_workspace_s_review_rounds_limit_follow_ups(
    client: AsyncClient, sessions: Sessions, github: FakeGithubApp
) -> None:
    pr = await opened_pr(client, sessions, github)
    github.permissions["alice"] = "write"
    await replace_policy_overrides(sessions, pr.workspace_id, PolicyOverrides(review_rounds=1))
    await deliver(client, comment_event(pr))
    async with sessions.begin() as session:  # the follow-up ended without pushing
        await session.execute(update(Run).where(Run.rerun_of == pr.run_id).values(status="failed"))

    _, delivery = await deliver(client, comment_event(pr))

    assert len(await runs_of(sessions, pr.workspace_id)) == 2
    assert await outcome(sessions, delivery) == "limit"
    assert github.reactions[-1][3] == "confused"


async def test_a_closed_pull_request_starts_nothing(
    client: AsyncClient, sessions: Sessions, github: FakeGithubApp
) -> None:
    pr = await opened_pr(client, sessions, github)
    github.permissions["alice"] = "write"
    key = (REPO, pr.number)
    pull = github.pulls[key]
    github.pulls[key] = PullRequestState(
        number=pull.number,
        url=pull.url,
        state="closed",
        merged=True,
        head=pull.head,
        head_sha=pull.head_sha,
        base=pull.base,
    )

    _, delivery = await deliver(client, comment_event(pr))

    assert len(await runs_of(sessions, pr.workspace_id)) == 1
    assert await outcome(sessions, delivery) == "pr_closed"
    assert github.reactions[-1][3] == "confused"
