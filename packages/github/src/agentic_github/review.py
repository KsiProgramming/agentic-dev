"""Reading a pull request's review for a follow-up run (7.6).

The worker reads it once, before the follow-up's first step: the comment that asked for the
follow-up, and every comment, review body and inline comment posted on the pull request after the
run before it pushed, by people with write access to the repo. Bots are left out, the App's own
comments included. What people wrote is data for the run's agents, never instructions."""

from dataclasses import dataclass
from datetime import datetime

from agentic_github.models import WRITE_PERMISSIONS, ReviewItem
from agentic_github.platform import GithubReviews


@dataclass(frozen=True)
class ReviewRead:
    """The comment that asked for the follow-up (`None` if it was deleted since) and the
    other comments that count, oldest first."""

    trigger: ReviewItem | None
    items: list[ReviewItem]


async def read_review(
    github: GithubReviews,
    installation_id: int,
    full_name: str,
    number: int,
    *,
    after: datetime | None,
    trigger_kind: str,
    trigger_id: int,
) -> ReviewRead:
    """The review of pull request `number` since `after` (the run before's push; `None` takes
    every comment). Raises what `github` raises (`GithubApiError`,
    `InstallationNotFoundError`)."""
    roles: dict[str, bool] = {}

    async def may_write(login: str) -> bool:
        if login not in roles:
            role = await github.repo_permission(installation_id, full_name, login)
            roles[login] = role in WRITE_PERMISSIONS
        return roles[login]

    trigger: ReviewItem | None = None
    kept: list[ReviewItem] = []
    for item in await github.review_items(installation_id, full_name, number):
        if item.kind == trigger_kind and item.id == trigger_id:
            trigger = item
            continue
        if item.from_bot or not item.body.strip():
            continue
        if after is not None and item.created_at <= after:
            continue
        if await may_write(item.author):
            kept.append(item)
    return ReviewRead(trigger=trigger, items=kept)
