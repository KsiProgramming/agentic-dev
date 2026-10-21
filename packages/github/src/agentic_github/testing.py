"""GitHub REST payloads for tests, with every field githubkit requires. Only the fields we read
take arguments; the rest are fixed placeholders."""

from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_URL = "https://api.github.com/x"
_WHEN = "2026-01-01T00:00:00Z"
_REPO_URL_FIELDS = [
    "url",
    "archive_url",
    "assignees_url",
    "blobs_url",
    "branches_url",
    "collaborators_url",
    "comments_url",
    "commits_url",
    "compare_url",
    "contents_url",
    "contributors_url",
    "deployments_url",
    "downloads_url",
    "events_url",
    "forks_url",
    "git_commits_url",
    "git_refs_url",
    "git_tags_url",
    "git_url",
    "issue_comment_url",
    "issue_events_url",
    "issues_url",
    "keys_url",
    "labels_url",
    "languages_url",
    "merges_url",
    "milestones_url",
    "notifications_url",
    "pulls_url",
    "releases_url",
    "ssh_url",
    "stargazers_url",
    "statuses_url",
    "subscribers_url",
    "subscription_url",
    "tags_url",
    "teams_url",
    "trees_url",
    "clone_url",
    "hooks_url",
    "svn_url",
]
_USER_URL_FIELDS = [
    "avatar_url",
    "url",
    "html_url",
    "followers_url",
    "following_url",
    "gists_url",
    "starred_url",
    "subscriptions_url",
    "organizations_url",
    "repos_url",
    "events_url",
    "received_events_url",
]


def private_key_pem() -> str:
    """A fresh RSA key, as GitHub hands out for an App."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode("ascii")


def user_payload(login: str, *, type_: str = "Organization") -> dict[str, Any]:
    return {
        **dict.fromkeys(_USER_URL_FIELDS, _URL),
        "login": login,
        "id": 1,
        "node_id": "U_1",
        "gravatar_id": None,
        "type": type_,
        "site_admin": False,
    }


def installation_payload(
    installation_id: int, login: str, *, target_type: str = "Organization"
) -> dict[str, Any]:
    return {
        "id": installation_id,
        "account": user_payload(login, type_=target_type),
        "repository_selection": "selected",
        "access_tokens_url": _URL,
        "repositories_url": _URL,
        "html_url": _URL,
        "app_id": 1,
        "target_id": 1,
        "target_type": target_type,
        "permissions": {"metadata": "read"},
        "events": [],
        "created_at": _WHEN,
        "updated_at": _WHEN,
        "single_file_name": None,
        "app_slug": "agentic-dev",
        "suspended_by": None,
        "suspended_at": None,
    }


def repo_payload(
    repo_id: int, full_name: str, *, private: bool = False, default_branch: str = "main"
) -> dict[str, Any]:
    owner, name = full_name.split("/", 1)
    return {
        **dict.fromkeys(_REPO_URL_FIELDS, _URL),
        "id": repo_id,
        "node_id": f"R_{repo_id}",
        "name": name,
        "full_name": full_name,
        "license": None,
        "owner": user_payload(owner),
        "private": private,
        "html_url": f"https://github.com/{full_name}",
        "description": None,
        "fork": False,
        "mirror_url": None,
        "homepage": None,
        "language": None,
        "forks": 0,
        "forks_count": 0,
        "stargazers_count": 0,
        "watchers_count": 0,
        "watchers": 0,
        "size": 0,
        "open_issues": 0,
        "open_issues_count": 0,
        "default_branch": default_branch,
        "has_pages": False,
        "disabled": False,
        "pushed_at": _WHEN,
        "created_at": _WHEN,
        "updated_at": _WHEN,
    }


def repos_page(repos: list[dict[str, Any]], *, total_count: int | None = None) -> dict[str, Any]:
    return {
        "total_count": len(repos) if total_count is None else total_count,
        "repository_selection": "selected",
        "repositories": repos,
    }


def token_payload(token: str) -> dict[str, Any]:
    expires = datetime.now(UTC) + timedelta(hours=1)
    return {"token": token, "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ")}
