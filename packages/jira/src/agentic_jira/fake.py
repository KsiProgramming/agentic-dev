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
in `posted` and `moved`, and shows on the issue afterwards.

Fields (7.4): each site has a few (`FAKE_FIELDS`): an "Acceptance criteria" paragraph
(`FAKE_AC_FIELD`), a short-text one, a "Story point estimate" number (`FAKE_POINTS_FIELD`), one
field of the wrong type for each role, and a team-managed project's own paragraph. `API-1` and
`OPS-2` carry values in them.

Webhooks (7.3): registrations are kept per site with a 30-day expiry, and refused as Jira
refuses them (one URL per account, `WEBHOOK_LIMIT` per site; `refuse_webhooks` forces a kind).
A refresh answers for unknown ids too, as Jira does. `delivery` builds a delivery signed with
`FAKE_CLIENT_SECRET`, shaped as Jira sends it, for tests."""

import itertools
import json
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import jwt
from pydantic import SecretStr

from agentic_jira.errors import (
    JiraApiError,
    JiraAuthError,
    JiraBadRequestError,
    JiraNotFoundError,
    JiraUnauthorizedError,
    JiraWebhookError,
)
from agentic_jira.models import (
    SCOPES,
    Account,
    DeliveryClaims,
    Grant,
    Issue,
    IssueComment,
    IssueSummary,
    JiraField,
    Project,
    ProjectPage,
    SearchPage,
    Site,
    Transition,
    Webhook,
)
from agentic_jira.webhooks import ALGORITHM, DELIVERY_HEADER, verify_delivery

FAKE_CODE = "fake-code"
FAKE_CLIENT_ID = "fake-atlassian-client"
FAKE_CLIENT_SECRET = "fake-atlassian-client-secret-for-local-dev-only"
"""The fake app's credentials: deliveries it signs verify with them."""
WEBHOOK_LIMIT = 5
"""Webhooks Jira lets one account's app register on a site."""
WEBHOOK_LIFE = timedelta(days=30)
_WEBHOOK_IDS = itertools.count(1)
"""Webhook ids, unique across fakes as Jira's are on a site, so tests sharing a database
never see another test's webhook match."""
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
    components: tuple[str, ...] = (),
    extra: dict[str, object] | None = None,
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
        components=components,
        assignee=None,
        reporter=FAKE_ACCOUNT.name,
        created="2026-11-01T09:00:00.000+0000",
        updated="2026-11-10T09:00:00.000+0000",
        description=description,
        comments=comments,
        comment_count=len(comments),
        extra=extra or {},
    )


FAKE_AC_FIELD = "customfield_10100"
"""The fake sites' "Acceptance criteria" paragraph field."""
FAKE_AC_TEXT_FIELD = "customfield_10101"
FAKE_POINTS_FIELD = "customfield_10016"
"""The fake sites' "Story point estimate" field."""


def _custom(id: str, name: str, type: str, kind: str, project_id: str | None = None) -> JiraField:
    return JiraField(id=id, name=name, type=type, kind=kind, custom=True, project_id=project_id)


_SYSTEM_FIELDS = (
    JiraField("summary", "Summary", "string", "", False),
    JiraField("description", "Description", "string", "", False),
    JiraField("timeestimate", "Remaining Estimate", "number", "", False),
)
FAKE_FIELDS: dict[str, tuple[JiraField, ...]] = {
    "fake-cloud-acme": (
        *_SYSTEM_FIELDS,
        _custom(FAKE_AC_FIELD, "Acceptance criteria", "string", "textarea"),
        _custom(FAKE_AC_TEXT_FIELD, "Acceptance notes", "string", "textfield"),
        _custom(FAKE_POINTS_FIELD, "Story point estimate", "number", "jsw-story-points"),
        _custom("customfield_10200", "Story points", "option", "select"),
        _custom("customfield_10201", "Acceptance date", "date", "datepicker"),
        _custom("customfield_10300", "Definition of done", "string", "textarea", "10004"),
    ),
    "fake-cloud-labs": (
        *_SYSTEM_FIELDS,
        _custom("customfield_20100", "Acceptance criteria", "string", "textarea"),
    ),
}
_STRONG = {"type": "strong"}
_AC_DOC: dict[str, object] = {
    "type": "doc",
    "version": 1,
    "content": [
        {
            "type": "bulletList",
            "content": [
                {
                    "type": "listItem",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "A client over 100 requests a minute "},
                                {"type": "text", "text": "gets 429.", "marks": [_STRONG]},
                            ],
                        }
                    ],
                },
                {
                    "type": "listItem",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "The limit is per API key."},
                            ],
                        }
                    ],
                },
            ],
        }
    ],
}


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
            components=("gateway",),
            extra={FAKE_AC_FIELD: _AC_DOC, FAKE_POINTS_FIELD: 5, FAKE_AC_TEXT_FIELD: "  "},
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
            extra={FAKE_AC_TEXT_FIELD: "The old server answers 410.", FAKE_POINTS_FIELD: 2},
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
class FakeDelivery:
    """A delivery as Jira sends it: its headers and its JSON body."""

    headers: dict[str, str]
    body: bytes


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
        self.issue_reads: list[tuple[str, str]] = []
        """Each `get_issue` call's site and key."""
        self.fields: dict[str, tuple[JiraField, ...]] = dict(FAKE_FIELDS)
        """The sites' fields; tests remove one to see a mapping outlive it."""
        self.posted: list[PostedComment] = []
        self.moved: list[MadeTransition] = []
        self.webhooks: dict[str, dict[int, Webhook]] = {}
        """Registered webhooks by site, then id."""
        self.refuse_webhooks: str | None = None
        """A `JiraWebhookError` kind every registration fails with."""
        self.refreshed: list[tuple[str, tuple[int, ...]]] = []

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

    async def get_issue(
        self, token: SecretStr, cloud_id: str, key: str, *, extra_fields: Sequence[str] = ()
    ) -> Issue:
        self._accepted(token)
        found = self._find(cloud_id, key)
        self.issue_reads.append((cloud_id, key))
        wanted = set(extra_fields)
        return replace(found, extra={k: v for k, v in found.extra.items() if k in wanted})

    async def list_fields(self, token: SecretStr, cloud_id: str) -> list[JiraField]:
        self._accepted(token)
        self._site_projects(cloud_id)
        fields = self.fields.get(cloud_id, ())
        return sorted(fields, key=lambda f: (f.name.lower(), f.id))

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
        comment = IssueComment(
            comment_id,
            FAKE_ACCOUNT.name,
            datetime.now(UTC).isoformat(),
            body,
            FAKE_ACCOUNT.account_id,
        )
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

    def verify_delivery(self, authorization: str | None) -> DeliveryClaims:
        return verify_delivery(
            authorization, client_id=FAKE_CLIENT_ID, client_secret=FAKE_CLIENT_SECRET
        )

    async def register_webhook(
        self, token: SecretStr, cloud_id: str, url: str, project_keys: Sequence[str]
    ) -> int:
        self._accepted(token)
        self._site_projects(cloud_id)
        if self.refuse_webhooks:
            raise JiraWebhookError(self.refuse_webhooks)
        everywhere = [hook for hooks in self.webhooks.values() for hook in hooks.values()]
        if any(hook.url != url for hook in everywhere):
            raise JiraWebhookError("url_conflict")
        site = self.webhooks.setdefault(cloud_id, {})
        if len(site) >= WEBHOOK_LIMIT:
            raise JiraWebhookError("limit")
        keys = ", ".join(f'"{key}"' for key in sorted(set(project_keys)))
        webhook = Webhook(
            id=next(_WEBHOOK_IDS),
            url=url,
            jql_filter=f"project in ({keys})",
            expires_at=datetime.now(UTC) + WEBHOOK_LIFE,
        )
        site[webhook.id] = webhook
        return webhook.id

    async def list_webhooks(self, token: SecretStr, cloud_id: str) -> list[Webhook]:
        self._accepted(token)
        self._site_projects(cloud_id)
        return list(self.webhooks.get(cloud_id, {}).values())

    async def refresh_webhooks(
        self, token: SecretStr, cloud_id: str, ids: Sequence[int]
    ) -> datetime | None:
        self._accepted(token)
        self._site_projects(cloud_id)
        expires_at = datetime.now(UTC) + WEBHOOK_LIFE
        site = self.webhooks.get(cloud_id, {})
        for webhook_id in ids:
            if webhook_id in site:  # an unknown id is not an error, as on Jira
                site[webhook_id] = replace(site[webhook_id], expires_at=expires_at)
        self.refreshed.append((cloud_id, tuple(ids)))
        return expires_at

    async def delete_webhooks(self, token: SecretStr, cloud_id: str, ids: Sequence[int]) -> None:
        self._accepted(token)
        self._site_projects(cloud_id)
        site = self.webhooks.get(cloud_id, {})
        for webhook_id in ids:
            site.pop(webhook_id, None)

    async def project_statuses(self, token: SecretStr, cloud_id: str, key: str) -> list[str]:
        self._accepted(token)
        if key not in {project.key for project in self._site_projects(cloud_id)}:
            raise JiraNotFoundError("Atlassian answered 404")
        return list(_WORKFLOW)

    def reply(self, cloud_id: str, key: str, body: str, *, author_id: str = "someone-else") -> str:
        """Someone else comments on the seeded issue `key` (7.9: an answer); the comment's id."""
        issue = self._find(cloud_id, key)
        comment_id = str(next(self._comment_ids))
        comment = IssueComment(
            comment_id, "Grace Other", datetime.now(UTC).isoformat(), body, author_id
        )
        self.issues[cloud_id][issue.key] = replace(
            issue, comments=(*issue.comments, comment), comment_count=issue.comment_count + 1
        )
        return comment_id

    def comment_delivery(
        self,
        cloud_id: str,
        key: str,
        comment_id: str,
        *,
        author_id: str = "someone-else",
        delivery_id: str | None = None,
    ) -> FakeDelivery:
        """A signed `comment_created` delivery for comment `comment_id` of issue `key`."""
        issue = self._find(cloud_id, key)
        payload = {
            "timestamp": int(datetime.now(UTC).timestamp() * 1000),
            "webhookEvent": "comment_created",
            "comment": {"id": comment_id, "author": {"accountId": author_id}, "body": "x"},
            "issue": {"id": issue.id, "key": issue.key, "fields": {}},
            "matchedWebhookIds": list(self.webhooks.get(cloud_id, {})),
        }
        return FakeDelivery(
            headers={
                "Authorization": f"Bearer {sign_delivery(cloud_id)}",
                "Content-Type": "application/json; charset=UTF-8",
                DELIVERY_HEADER: delivery_id or str(uuid.uuid4().int)[:19],
            },
            body=json.dumps(payload).encode(),
        )

    def delivery(
        self,
        cloud_id: str,
        key: str,
        *,
        status_to: str | None = None,
        labels: tuple[str, str] | None = None,
        created: bool = False,
        account_id: str = FAKE_ACCOUNT.account_id,
        delivery_id: str | None = None,
        webhook_ids: Sequence[int] | None = None,
    ) -> FakeDelivery:
        """A signed delivery about the seeded issue `key` on `cloud_id`: a status move to
        `status_to`, a label change `labels` (`fromString`, `toString`), or with `created` the
        issue's creation. Matched to every webhook of the site unless `webhook_ids` says."""
        issue = self._find(cloud_id, key)
        items: list[dict[str, Any]] = []
        if status_to is not None:
            items.append(
                {
                    "field": "status",
                    "fieldId": "status",
                    "fromString": issue.status,
                    "toString": status_to,
                }
            )
        if labels is not None:
            items.append(
                {
                    "field": "labels",
                    "fieldId": "labels",
                    "fromString": labels[0],
                    "toString": labels[1],
                }
            )
        matched = (
            list(webhook_ids) if webhook_ids is not None else list(self.webhooks.get(cloud_id, {}))
        )
        payload = {
            "timestamp": int(datetime.now(UTC).timestamp() * 1000),
            "webhookEvent": "jira:issue_created" if created else "jira:issue_updated",
            "issue_event_type_name": "issue_created" if created else "issue_generic",
            "user": {"accountId": account_id, "displayName": FAKE_ACCOUNT.name},
            "issue": {
                "id": issue.id,
                "key": issue.key,
                "fields": {
                    "summary": issue.summary,
                    "description": None,
                    "project": {"key": issue.project_key},
                    "status": {"name": status_to or issue.status},
                    "labels": list(issue.labels),
                },
            },
            "changelog": {"id": str(next(self._comment_ids)), "items": items},
            "matchedWebhookIds": matched,
        }
        return FakeDelivery(
            headers={
                "Authorization": f"Bearer {sign_delivery(cloud_id)}",
                "Content-Type": "application/json; charset=UTF-8",
                DELIVERY_HEADER: delivery_id or str(uuid.uuid4().int)[:19],
            },
            body=json.dumps(payload).encode(),
        )

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


def sign_delivery(
    cloud_id: str,
    *,
    secret: str = FAKE_CLIENT_SECRET,
    issuer: str = FAKE_CLIENT_ID,
    expires_in_s: int = 900,
    algorithm: str = ALGORITHM,
) -> str:
    """A delivery JWT shaped as Atlassian's (`iss`, `sub`, `context`, `iat`, `exp`, `jti`).
    Tests pass another secret, issuer, a negative expiry or another algorithm to see it
    refused."""
    now = datetime.now(UTC)
    claims = {
        "iss": issuer,
        "sub": FAKE_ACCOUNT.account_id,
        "context": {"resourceType": "site", "resourceId": cloud_id, "cloudId": cloud_id},
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in_s)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, secret, algorithm=algorithm)
