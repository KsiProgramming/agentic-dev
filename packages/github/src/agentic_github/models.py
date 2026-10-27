from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class InstallationInfo:
    id: int
    # The user or organisation the App is installed on.
    account_login: str
    account_type: str


@dataclass(frozen=True)
class RepoInfo:
    id: int
    full_name: str
    name: str
    owner: str
    private: bool
    default_branch: str
    html_url: str
    # Set when the repo was read on its own (`get_repo`, `create_org_repo`), not in lists.
    created_at: datetime | None = None


@dataclass(frozen=True)
class PullRequestInfo:
    number: int
    url: str
    # Branch names, as GitHub reports them.
    head: str
    base: str
