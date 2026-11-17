import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from pydantic import SecretStr

# Asked for once, for all of Milestone 7 (7.1): reading issues and projects, commenting and
# transitioning (7.2, behind gates), registering webhooks (7.3), reading users (7.4), the
# connecting account's name, and a refresh token.
SCOPES: tuple[str, ...] = (
    "read:jira-work",
    "write:jira-work",
    "manage:jira-webhook",
    "read:jira-user",
    "read:me",
    "offline_access",
)


def missing_scopes(granted: Iterable[str]) -> tuple[str, ...]:
    """The scopes of `SCOPES` a grant does not hold, in `SCOPES` order."""
    held = set(granted)
    return tuple(scope for scope in SCOPES if scope not in held)


@dataclass(frozen=True)
class Grant:
    """What Atlassian issued: an access token (about an hour), the refresh token that replaces
    both (it rotates: each use returns a new one), and the scopes held."""

    access_token: SecretStr
    refresh_token: SecretStr
    expires_at: datetime
    scopes: tuple[str, ...]

    def to_secret(self) -> SecretStr:
        """The grant as the one secret the store encrypts."""
        return SecretStr(
            json.dumps(
                {
                    "access_token": self.access_token.get_secret_value(),
                    "refresh_token": self.refresh_token.get_secret_value(),
                    "expires_at": self.expires_at.astimezone(UTC).isoformat(),
                    "scopes": list(self.scopes),
                }
            )
        )

    @classmethod
    def from_secret(cls, secret: SecretStr) -> "Grant":
        data = cast(dict[str, Any], json.loads(secret.get_secret_value()))
        return cls(
            access_token=SecretStr(str(data["access_token"])),
            refresh_token=SecretStr(str(data["refresh_token"])),
            expires_at=datetime.fromisoformat(str(data["expires_at"])),
            scopes=tuple(str(scope) for scope in data["scopes"]),
        )


@dataclass(frozen=True)
class Account:
    """The Atlassian account that consented. Jira acts as this person."""

    account_id: str
    name: str


@dataclass(frozen=True)
class Site:
    """A Jira Cloud site the grant reaches; `cloud_id` addresses its API."""

    cloud_id: str
    url: str
    name: str


@dataclass(frozen=True)
class Project:
    id: str
    key: str
    name: str


@dataclass(frozen=True)
class ProjectPage:
    """A page of a project search; `next_start_at` is where the next one starts, if any."""

    projects: tuple[Project, ...]
    next_start_at: int | None


@dataclass(frozen=True)
class IssueComment:
    """A comment on an issue, its body as Markdown (`agentic_jira.adf`)."""

    id: str
    author: str
    created: str
    body: str


@dataclass(frozen=True)
class Issue:
    """The standard fields of an issue (7.2; custom fields are mapped in 7.4). Text is Markdown;
    names are display names. `project_key` is the project the issue is in now, which an issue
    moved from another project does not show in its key. `comments` are the latest, oldest
    first; `comment_count` is how many the issue has."""

    id: str
    key: str
    project_key: str
    summary: str
    status: str
    type: str
    priority: str | None
    labels: tuple[str, ...]
    components: tuple[str, ...]
    assignee: str | None
    reporter: str | None
    created: str
    updated: str
    description: str
    comments: tuple[IssueComment, ...]
    comment_count: int


@dataclass(frozen=True)
class IssueSummary:
    """An issue as a search lists it."""

    key: str
    project_key: str
    summary: str
    status: str
    type: str
    assignee: str | None
    updated: str


@dataclass(frozen=True)
class SearchPage:
    """A page of a JQL search; `next_page_token` fetches the next one, if any."""

    issues: tuple[IssueSummary, ...]
    next_page_token: str | None


@dataclass(frozen=True)
class Transition:
    """A move the issue's workflow offers from its current status."""

    id: str
    name: str
    to_status: str
