"""PR review feedback (7.6) on a worker: a review comment on an SDD run's pull request starts a
follow-up that runs the review loop again on the pull request's code, with the review in its
agents' context, and after its gate pushes to the same pull request."""

import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import JsonValue
from redis.asyncio import Redis
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.gate import GateDecision
from agentic_engine.templates import SddParams, build_sdd_spec
from agentic_github import branch_sha
from agentic_jira import FakeAtlassian
from agentic_runtime import AgentRuntime, ToolExecutor
from agentic_sandbox import FakeSandboxManager, RepoSource
from agentic_sandbox.testing import make_repo
from agentic_store import (
    FollowUp,
    RerunFromStep,
    create_rerun,
    create_run,
    enqueue_run,
    get_run,
    latest_pr_run,
    list_run_events,
    put_github_connection,
    record_approval,
)
from agentic_store.models import Run
from agentic_tools.testing import FakeGithub, bare_remote

from .test_worker import (
    GITHUB_TOKEN,
    GITHUB_URL,
    MirroredSandboxes,
    jira_workspace,
    master_key,
    remote_files,
    sdd_team,
    wait_for_gate,
    wait_for_status,
    worker,
)

pytestmark = pytest.mark.integration

_ = master_key  # the fixture

REPO = "acme/hello"
PR_URL = f"https://github.com/{REPO}/pull/1"
ISSUE: dict[str, JsonValue] = {
    "cloud_id": "fake-cloud-acme",
    "site": "acme.atlassian.net",
    "key": "API-1",
    "url": "https://acme.atlassian.net/browse/API-1",
}


def git(cwd: Path, *args: str) -> tuple[int, str]:
    done = subprocess.run(["git", *args], cwd=cwd, check=False, capture_output=True, text=True)
    return done.returncode, done.stdout


async def queue(redis_url: str, run_id: UUID) -> None:
    redis = Redis.from_url(redis_url)  # pyright: ignore[reportUnknownMemberType]
    try:
        await enqueue_run(redis, run_id)
    finally:
        await redis.aclose()


async def through_gates(
    sessions: async_sessionmaker[AsyncSession], redis_url: str, run_id: UUID, *gates: str
) -> None:
    for gate in gates:
        await wait_for_gate(sessions, run_id, gate)
        await record_approval(sessions, run_id, gate, GateDecision(decision="approve"))
        await queue(redis_url, run_id)


async def follow_up(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID, comment_id: int
) -> UUID:
    """The follow-up `POST /github/webhooks` creates for `@agentic-dev fix this` (comment
    `comment_id`) from alice, a writer: a rerun of the latest run on the pull request from its
    `on_review.from`."""
    latest = await latest_pr_run(sessions, [workspace_id], PR_URL)
    assert latest is not None and latest.spec.on_review is not None
    assert latest.head_branch is not None and latest.head_sha is not None
    assert latest.pushed_at is not None
    return await create_rerun(
        sessions,
        latest.id,
        from_step=RerunFromStep(node_id=latest.spec.on_review.from_),
        follow_up=FollowUp(
            pr_review={
                "pr_url": PR_URL,
                "full_name": REPO,
                "number": 1,
                "head_branch": latest.head_branch,
                "after_sha": latest.head_sha,
                "after_at": latest.pushed_at.isoformat(),
                "kind": "review_comment",
                "comment_id": comment_id,
                "comment_url": f"{PR_URL}#discussion_r{comment_id}",
                "author": "alice",
                "delivery_id": f"delivery-{comment_id}",
            },
            review_rounds=3,
        ),
    )


@pytest.mark.parametrize("checks", [False, True])
async def test_done_when_a_review_comment_starts_a_follow_up_on_the_same_pr(
    sessions: async_sessionmaker[AsyncSession],
    postgres_url: str,
    redis_url: str,
    tmp_path: Path,
    master_key: Path,
    checks: bool,
) -> None:
    """7.6 on fakes: an SDD run opens PR #1; `@agentic-dev fix this` on it starts a follow-up
    that runs the review loop on the PR's code with the review as its context, waits at
    `approve_pr`, and once approved pushes a fast-forward to the same PR, replies on it once and
    comments the links on the Jira issue. A second follow-up, after someone else pushed to the
    PR, fails `pr_head_moved` before doing anything."""
    async with sessions() as session:
        # The database outlives a test and the fake GitHub numbers its pull requests from 1 again:
        # without this the second variant would find the first one's follow-ups on "pull/1".
        await session.execute(update(Run).where(Run.pr_review.is_not(None)).values(pr_review=None))
        await session.commit()
    repos = tmp_path / "repos"
    make_repo(repos / "hello")
    remote = bare_remote(repos / "hello", tmp_path / "remote.git")
    bare = tmp_path / "remote.git"
    github = FakeGithub(GITHUB_TOKEN)
    github.head_of = lambda _full_name, branch: branch_sha(bare, branch)
    github.permissions["mallory"] = "read"
    sandboxes = MirroredSandboxes(
        FakeSandboxManager(local_root=repos), {GITHUB_URL: str(repos / "hello")}
    )
    atlassian = FakeAtlassian("")
    workspace_id = await jira_workspace(sessions, atlassian, master_key)
    await put_github_connection(sessions, workspace_id, 42, "acme")
    limit = {"value": 100}
    middle = ("checks",) if checks else ()

    def team(tools: ToolExecutor | None) -> AgentRuntime:
        return sdd_team(tools, limit["value"])

    async with worker(
        postgres_url,
        redis_url,
        make_runtime=team,
        sandboxes=sandboxes,
        github=github,
        github_remote=lambda _full_name: remote,
        master_key_file=master_key,
        jira=atlassian,
        web_base_url="https://agentic.example",
    ):
        original = await create_run(
            sessions,
            build_sdd_spec(SddParams(move_to="In Progress", checks=checks)),
            "API-1",
            RepoSource(url=GITHUB_URL),
            workspace_id=workspace_id,
            jira_issue=ISSUE,
        )
        await queue(redis_url, original)
        await through_gates(sessions, redis_url, original, "approve_spec", *middle, "approve_pr")
        await wait_for_status(sessions, original, "completed")
        branch = f"agent/{original}/implement"
        opened_at = branch_sha(bare, branch)
        assert opened_at is not None

        # A writer comments inline and asks; a reader's comment does not count.
        asked = github.add_item(
            REPO, 1, "review_comment", "alice", "@agentic-dev fix this: the limit is 50.",
            path="gateway/limits.py", line=1, diff_hunk="@@ -0,0 +1 @@\n+LIMIT = 100",
        )  # fmt: skip
        github.add_item(REPO, 1, "issue_comment", "bob", "And keep it in one place.")
        github.add_item(REPO, 1, "issue_comment", "mallory", "Drop the limit entirely.")
        limit["value"] = 50
        first = await follow_up(sessions, workspace_id, asked.id)
        await queue(redis_url, first)
        if checks:  # the fake sandbox cannot build, so a person is asked at `checks` (13.4)
            await through_gates(sessions, redis_url, first, "checks")
        await wait_for_gate(sessions, first, "approve_pr")
        assert branch_sha(bare, branch) == opened_at  # nothing pushed before the gate
        await through_gates(sessions, redis_url, first, "approve_pr")
        await wait_for_status(sessions, first, "completed")

        # Someone else pushes to the PR; the next follow-up must not overwrite it.
        pushed = branch_sha(bare, branch)
        assert pushed is not None
        git(bare, "update-ref", f"refs/heads/{branch}", opened_at, pushed)
        again = github.add_item(REPO, 1, "issue_comment", "alice", "@agentic-dev fix this")
        second = await follow_up(sessions, workspace_id, again.id)
        await queue(redis_url, second)
        await wait_for_status(sessions, second, "failed")

    # The first follow-up ran the loop again on the PR's code and pushed on top of it.
    assert len(github.opened) == 1  # one pull request, ever
    assert git(bare, "show", f"{pushed}:gateway/limits.py") == (0, "LIMIT = 50\n")
    ancestry, _ = git(bare, "merge-base", "--is-ancestor", opened_at, pushed)
    assert ancestry == 0, "the push was not a fast-forward"
    assert "specs/API-1-rate-limit-the-public-endpoints/spec.md" in remote_files(bare, pushed)
    [reply] = github.posted
    assert reply == (
        REPO,
        1,
        f"Pushed `{pushed[:7]}` for @alice's review, run "
        f"[{str(first)[:8]}](https://agentic.example/runs/{first}).",
    )
    stored = await get_run(sessions, first)
    assert stored is not None and stored.pr_review_brief is not None
    brief: dict[str, Any] = stored.pr_review_brief
    assert brief["request"]["body"] == "@agentic-dev fix this: the limit is 50."
    assert brief["request"]["path"] == "gateway/limits.py"
    assert [c["author"] for c in brief["comments"]] == ["bob"]  # not mallory, not the bot
    events = await list_run_events(sessions, first)
    started = next(e for e in events if e.type == "run_started")
    origin: dict[str, Any] = (started.payload or {})["rerun_from"]  # type: ignore[assignment]
    assert origin["node_id"] == "review_loop"
    ran = {e.node_id for e in events if e.type == "node_started"}
    assert {"spec_writer", "planner", "tasker"}.isdisjoint(ran)
    assert {"implement", "synthesizer", "reviewer", "publish", "jira_update"} <= ran
    opened = next(e for e in events if e.type == "pr_opened")
    assert opened.payload["url"] == PR_URL and opened.payload["updated"] is True
    # Jira: the follow-up commented the links again; the issue was already where it moves to.
    linked, relinked = atlassian.posted
    assert relinked.key == "API-1" and f"- Pull request: {PR_URL}" in relinked.body
    assert linked.body.split("\n")[0] == relinked.body.split("\n")[0]
    # The second follow-up failed before its first step, and pushed nothing.
    failed = await get_run(sessions, second)
    assert failed is not None and failed.pr_review_brief is None
    [*_, end] = await list_run_events(sessions, second)
    assert end.type == "run_failed"
    assert str((end.payload or {})["error"]).startswith("pr_head_moved:")
    assert branch_sha(bare, branch) == opened_at
    assert len(github.posted) == 1
