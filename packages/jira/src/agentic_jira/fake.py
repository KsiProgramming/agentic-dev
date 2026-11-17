"""A stand-in for Atlassian, for local dev, tests and the end-to-end stack (`AGENTIC_JIRA=fake`).
It never calls Atlassian.

Its consent screen is skipped: the authorize URL sends the browser straight back to the API's
callback with `FAKE_CODE`. The grant reaches two sites with a few projects each. It accepts any
token it could have issued (they share a prefix), so a grant stored before the API restarted
still works. Tests switch its failures on: `refuse_refresh`, `unauthorized`, `granted_scopes`.

Issues (7.2): a few seeded issues (`FAKE_ISSUES`) on a three-status workflow (To Do, In
Progress, Done), and `DOCS-9`, an issue moved to OPS that still answers to its old key. A
search understands only the `project in (…)` clause the Jira tools put first; `leak_search`
makes it return every issue of the site, to test that the tools filter. What runs post is kept
in `posted` and `moved`, and shows on the issue afterwards."""

import itertools
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from pydantic import SecretStr

from agentic_jira.errors import (
    JiraApiError,
    JiraAuthError,
    JiraBadRequestError,
    JiraNotFoundError,
    JiraUnauthorizedError,
)
from agentic_jira.models import (
    SCOPES,
    Account,
    Grant,
    Issue,
    IssueComment,
    IssueSummary,
    Project,
    ProjectPage,
    SearchPage,
    Site,
    Transition,
)

FAKE_CODE = "fake-code"
FAKE_ACCOUNT = Account(account_id="fake-account-1", name="Ada Example")
FAKE_SITES = (
    Site("fake-cloud-acme", "https://acme.atlassian.net", "Acme"),
    Site("fake-cloud-labs", "https://acme-labs.atlassian.net", "Acme Labs"),
)
FAKE_PROJECTS: dict[str, tuple[Project, ...]] = {
    "fake-cloud-acme": (
        Project("10001", "API", "Public API"),
        Project("10002", "DOCS", "Documentation"),
        Project("10003", "OPS", "Operations"),
        Project("10004", "WEB", "Web shop"),
    ),
    "fake-cloud-labs": (
        Project("20001", "LAB", "Experiments"),
        Project("20002", "ML", "Machine learning"),
    ),
}
_ACCESS = "fake-jira-access-"
_REFRESH = "fake-jira-refresh-"
PAGE_SIZE = 50


def _issue(
    id: str,
    key: str,
    summary: str,
    status: str,
    description: str,
    *,
    type: str = "Task",
    comments: tuple[IssueComment, ...] = (),
    labels: tuple[str, ...] = (),
) -> Issue:
    return Issue(
        id=id,
        key=key,
        project_key=key.rsplit("-", 1)[0],
        summary=summary,
        status=status,
        type=type,
        priority="Medium",
        labels=labels,
        components=(),
        assignee=None,
        reporter=FAKE_ACCOUNT.name,
        created="2026-11-01T09:00:00.000+0000",
        updated="2026-11-10T09:00:00.000+0000",
        description=description,
        comments=comments,
        comment_count=len(comments),
    )


FAKE_ISSUES: dict[str, tuple[Issue, ...]] = {
    "fake-cloud-acme": (
        _issue(
            "30001",
            "API-1",
            "Rate limit the public endpoints",
            "To Do",
            "The public endpoints have no rate limit.\n\n"
            "## Acceptance criteria\n\n- A client over 100 requests a minute gets `429`.",
            type="Story",
            labels=("backend",),
            comments=(
                IssueComment(
                    "40001", FAKE_ACCOUNT.name, "2026-11-02T09:00:00.000+0000", "Per API key?"
                ),
            ),
        ),
        _issue(
            "30002",
            "API-2",
            "Document the pagination headers",
            "In Progress",
            "List endpoints return `Link` headers nobody documented.",
        ),
        _issue(
            "30003",
            "DOCS-1",
            "Explain how to run the docs site locally",
            "To Do",
            "New contributors cannot build the docs.",
        ),
        _issue(
            "30004",
            "OPS-1",
            "Rotate the staging certificates",
            "Done",
            "The staging certificates expire this month.",
        ),
        _issue(
            "30005",
            "OPS-2",
            "Archive the old docs server",
            "To Do",
            "Moved from DOCS: the server is ours to retire.",
        ),
    ),
    "fake-cloud-labs": (
        _issue("50001", "LAB-1", "Try a smaller embedding model", "To Do", "Cost is too high."),
    ),
}
FAKE_MOVED: dict[str, str] = {"DOCS-9": "OPS-2"}
"""Old keys of moved issues → their key now."""

# The fake workflow: from each status, the transitions it offers (id, name, target).
_WORKFLOW: dict[str, tuple[Transition, ...]] = {
    "To Do": (Transition("11", "Start progress", "In Progress"), Transition("31", "Done", "Done")),
    "In Progress": (
        Transition("21", "Stop progress", "To Do"),
        Transition("31", "Done", "Done"),
    ),
    "Done": (Transition("41", "Reopen", "To Do"),),
}
_PROJECT_CLAUSE = re.compile(r"^\s*project\s+in\s+\(([^)]*)\)", re.IGNORECASE)


@dataclass(frozen=True)
class PostedComment:
    cloud_id: str
    key: str
    body: str


@dataclass(frozen=True)
class MadeTransition:
    cloud_id: str
    key: str
    transition_id: str


class FakeAtlassian:
    """Has `AtlassianApp`'s interface. `api_base_url` is where the browser reaches the API,
    which the fake consent sends it back to."""

    def __init__(self, api_base_url: str) -> None:
        self._api_base_url = api_base_url.rstrip("/")
        self._numbers = itertools.count(1)
        self._comment_ids = itertools.count(41001)
        self.sites_reached: list[Site] = list(FAKE_SITES)
        self.granted_scopes: tuple[str, ...] = SCOPES
        self.expires_in_s = 3600
        self.refuse_refresh = False
        self.unauthorized = False
        self.unavailable = False
        self.leak_search = False
        self.refreshes = 0
        self.issued: list[Grant] = []
        self.issues: dict[str, dict[str, Issue]] = {
            cloud_id: {issue.key: issue for issue in issues}
            for cloud_id, issues in FAKE_ISSUES.items()
        }
        self.searches: list[str] = []
        self.posted: list[PostedComment] = []
        self.moved: list[MadeTransition] = []

    def authorize_url(self, state: str) -> str:
        return (
            f"{self._api_base_url}/jira/callback?{urlencode({'code': FAKE_CODE, 'state': state})}"
        )

    async def exchange(self, code: str) -> Grant:
        self._reachable()
        if code != FAKE_CODE:
            raise JiraAuthError("exchange")
        return self._issue()

    async def refresh(self, refresh_token: SecretStr) -> Grant:
        self._reachable()
        self.refreshes += 1
        if self.refuse_refresh or not refresh_token.get_secret_value().startswith(_REFRESH):
            raise JiraAuthError("invalid_grant")
        return self._issue()

    async def account(self, token: SecretStr) -> Account:
        self._accepted(token)
        return FAKE_ACCOUNT

    async def sites(self, token: SecretStr) -> list[Site]:
        self._accepted(token)
        return list(self.sites_reached)

    async def search_projects(
        self, token: SecretStr, cloud_id: str, *, query: str = "", start_at: int = 0
    ) -> ProjectPage:
        self._accepted(token)
        needle = query.strip().lower()
        matching = [
            project
            for project in self._site_projects(cloud_id)
            if needle in project.key.lower() or needle in project.name.lower()
        ]
        matching.sort(key=lambda project: project.name.lower())
        page = tuple(matching[start_at : start_at + PAGE_SIZE])
        end = start_at + len(page)
        return ProjectPage(projects=page, next_start_at=end if end < len(matching) else None)

    async def get_projects(
        self, token: SecretStr, cloud_id: str, ids: Sequence[str]
    ) -> list[Project]:
        self._accepted(token)
        wanted = set(ids)
        return [project for project in self._site_projects(cloud_id) if project.id in wanted]

    async def get_issue(self, token: SecretStr, cloud_id: str, key: str) -> Issue:
        self._accepted(token)
        return self._find(cloud_id, key)

    async def search(
        self,
        token: SecretStr,
        cloud_id: str,
        jql: str,
        *,
        limit: int,
        page_token: str | None = None,
    ) -> SearchPage:
        self._accepted(token)
        self._site_projects(cloud_id)
        self.searches.append(jql)
        if "!!" in jql:
            raise JiraBadRequestError("Atlassian answered 400")
        issues = list(self.issues.get(cloud_id, {}).values())
        clause = _PROJECT_CLAUSE.match(jql)
        if clause and not self.leak_search:
            keys = {part.strip().strip('"') for part in clause.group(1).split(",")}
            issues = [issue for issue in issues if issue.project_key in keys]
        summaries = tuple(
            IssueSummary(
                key=issue.key,
                project_key=issue.project_key,
                summary=issue.summary,
                status=issue.status,
                type=issue.type,
                assignee=issue.assignee,
                updated=issue.updated,
            )
            for issue in issues[:limit]
        )
        return SearchPage(issues=summaries, next_page_token=None)

    async def transitions(self, token: SecretStr, cloud_id: str, key: str) -> list[Transition]:
        self._accepted(token)
        return list(_WORKFLOW.get(self._find(cloud_id, key).status, ()))

    async def add_comment(self, token: SecretStr, cloud_id: str, key: str, body: str) -> str:
        self._accepted(token)
        issue = self._find(cloud_id, key)
        comment_id = str(next(self._comment_ids))
        comment = IssueComment(comment_id, FAKE_ACCOUNT.name, datetime.now(UTC).isoformat(), body)
        self.issues[cloud_id][issue.key] = replace(
            issue, comments=(*issue.comments, comment), comment_count=issue.comment_count + 1
        )
        self.posted.append(PostedComment(cloud_id, issue.key, body))
        return comment_id

    async def transition(
        self, token: SecretStr, cloud_id: str, key: str, transition_id: str
    ) -> None:
        self._accepted(token)
        issue = self._find(cloud_id, key)
        offered = {t.id: t for t in _WORKFLOW.get(issue.status, ())}
        if transition_id not in offered:
            raise JiraBadRequestError("Atlassian answered 400")
        self.issues[cloud_id][issue.key] = replace(issue, status=offered[transition_id].to_status)
        self.moved.append(MadeTransition(cloud_id, issue.key, transition_id))

    async def aclose(self) -> None:
        return None

    def _find(self, cloud_id: str, key: str) -> Issue:
        self._site_projects(cloud_id)
        issues = self.issues.get(cloud_id, {})
        found = issues.get(FAKE_MOVED.get(key, key))
        if found is None:
            raise JiraNotFoundError("Atlassian answered 404")
        return found

    def _site_projects(self, cloud_id: str) -> tuple[Project, ...]:
        if cloud_id not in {site.cloud_id for site in self.sites_reached}:
            raise JiraApiError("Atlassian answered 404")
        return FAKE_PROJECTS.get(cloud_id, ())

    def _issue(self) -> Grant:
        number = next(self._numbers)
        grant = Grant(
            access_token=SecretStr(f"{_ACCESS}{number:04d}"),
            refresh_token=SecretStr(f"{_REFRESH}{number:04d}"),
            expires_at=datetime.now(UTC) + timedelta(seconds=self.expires_in_s),
            scopes=self.granted_scopes,
        )
        self.issued.append(grant)
        return grant

    def _reachable(self) -> None:
        if self.unavailable:
            raise JiraApiError("Atlassian could not be reached: ConnectError")

    def _accepted(self, token: SecretStr) -> None:
        self._reachable()
        if self.unauthorized or not token.get_secret_value().startswith(_ACCESS):
            raise JiraUnauthorizedError("Atlassian did not accept the access token")
