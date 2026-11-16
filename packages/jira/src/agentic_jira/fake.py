"""A stand-in for Atlassian, for local dev, tests and the end-to-end stack (`AGENTIC_JIRA=fake`).
It never calls Atlassian.

Its consent screen is skipped: the authorize URL sends the browser straight back to the API's
callback with `FAKE_CODE`. The grant reaches two sites with a few projects each. It accepts any
token it could have issued (they share a prefix), so a grant stored before the API restarted
still works. Tests switch its failures on: `refuse_refresh`, `unauthorized`, `granted_scopes`."""

import itertools
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from pydantic import SecretStr

from agentic_jira.errors import JiraApiError, JiraAuthError, JiraUnauthorizedError
from agentic_jira.models import SCOPES, Account, Grant, Project, ProjectPage, Site

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


class FakeAtlassian:
    """Has `AtlassianApp`'s interface. `api_base_url` is where the browser reaches the API,
    which the fake consent sends it back to."""

    def __init__(self, api_base_url: str) -> None:
        self._api_base_url = api_base_url.rstrip("/")
        self._numbers = itertools.count(1)
        self.sites_reached: list[Site] = list(FAKE_SITES)
        self.granted_scopes: tuple[str, ...] = SCOPES
        self.expires_in_s = 3600
        self.refuse_refresh = False
        self.unauthorized = False
        self.unavailable = False
        self.refreshes = 0
        self.issued: list[Grant] = []

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

    async def aclose(self) -> None:
        return None

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
