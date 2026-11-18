"""Telling an answer from the platform's own comment (7.9): what the comment webhook and the
direct check both ask of a run waiting for an answer on an issue.

A comment answers a question when it is newer than the comment the platform posted (Jira's
comment ids only grow) and is not itself one of the platform's: those end with the footer line
`Posted by agentic-dev run …` (`PLATFORM_MARK`). The platform's comments are told apart by that
line, not by their author: the person who connected Jira is often the one who answers, and an
answer from the connected account is still an answer."""

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_jira.access import WorkspaceJira
from agentic_jira.platform import JiraPlatform
from agentic_secrets import KeyProvider
from agentic_store import WaitingRun, answer_arrived, enqueue_run

PLATFORM_MARK = "Posted by agentic-dev run"
"""The words every comment the platform posts ends with (`agentic_tools.jira`)."""


def newer(comment_id: str, after_comment_id: str) -> bool:
    """Whether `comment_id` was made after `after_comment_id`. Ids are integers; one that is not
    a number is never newer."""
    return (
        comment_id.isdigit()
        and after_comment_id.isdigit()
        and int(comment_id) > int(after_comment_id)
    )


def is_platforms(body: str) -> bool:
    """Whether `body` is a comment the platform posted: it carries the platform's footer."""
    return PLATFORM_MARK in body


async def answer_found(
    access: WorkspaceJira, cloud_id: str, issue_key: str, after_comment_id: str
) -> bool:
    """The direct check: whether the issue's latest comments (`get_issue` reads 20) hold one
    newer than `after_comment_id` that is not the platform's own. More than 20
    newer comments cannot all be seen, and at most one of them is ours (the questions), so the
    latest 20 holding none of theirs means no answer."""
    issue = await access.call(lambda token: access.platform.get_issue(token, cloud_id, issue_key))
    return any(
        newer(comment.id, after_comment_id) and not is_platforms(comment.body)
        for comment in issue.comments
    )


async def check_and_answer(
    sessions: async_sessionmaker[AsyncSession],
    keys: KeyProvider,
    platform: JiraPlatform,
    redis: Redis,
    waiting: WaitingRun,
) -> bool:
    """Look for an answer to the run `waiting` on its issue and, if one is there, continue the
    run (`answer_arrived`) and queue it. `True` when an answer was found (the run is continued
    by this call or was already). Raises what a Jira call raises: the caller decides whether a
    failed check matters (a sweep logs it; "Check now" says so)."""
    access = WorkspaceJira(sessions, keys, platform, waiting.workspace_id)
    if not await answer_found(
        access, waiting.cloud_id, waiting.issue_key, waiting.after_comment_id
    ):
        return False
    if await answer_arrived(sessions, waiting.run_id, waiting.node_id):
        await enqueue_run(redis, waiting.run_id)
    return True
