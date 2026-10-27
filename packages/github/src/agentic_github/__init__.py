"""The platform's GitHub App: looking up installations, listing the repos they can reach,
creating repos in an organisation, and publishing a run's branch (push from a git bundle, then a
pull request)."""

from agentic_github.app import GITHUB_API_URL, GithubApp
from agentic_github.config import GithubAppConfig
from agentic_github.errors import (
    GithubApiError,
    GithubConfigError,
    InstallationNotFoundError,
    PullRequestError,
    PushError,
    RepoCreationNotAllowedError,
    RepoExistsError,
)
from agentic_github.fake import (
    FAKE_ACCOUNT,
    FAKE_INSTALLATION_ID,
    FAKE_REPOS,
    FakeGithubApp,
    fixture_path,
)
from agentic_github.models import (
    GITIGNORE_TEMPLATES,
    LICENSE_TEMPLATES,
    InstallationInfo,
    PullRequestInfo,
    RepoInfo,
)
from agentic_github.platform import GithubPlatform, installation_settings_url
from agentic_github.push import auth_env, github_remote, push_bundle, repo_full_name

__all__ = [
    "FAKE_ACCOUNT",
    "FAKE_INSTALLATION_ID",
    "FAKE_REPOS",
    "GITHUB_API_URL",
    "GITIGNORE_TEMPLATES",
    "LICENSE_TEMPLATES",
    "FakeGithubApp",
    "GithubApiError",
    "GithubApp",
    "GithubAppConfig",
    "GithubConfigError",
    "GithubPlatform",
    "InstallationInfo",
    "InstallationNotFoundError",
    "PullRequestError",
    "PullRequestInfo",
    "PushError",
    "RepoCreationNotAllowedError",
    "RepoExistsError",
    "RepoInfo",
    "auth_env",
    "fixture_path",
    "github_remote",
    "installation_settings_url",
    "push_bundle",
    "repo_full_name",
]
