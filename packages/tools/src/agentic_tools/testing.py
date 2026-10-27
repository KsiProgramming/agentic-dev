"""Test helpers shared by the tools and worker test suites."""

import os
import subprocess
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp import Client
from pydantic import SecretStr

from agentic_github import PullRequestInfo, RepoExistsError, RepoInfo
from agentic_sandbox import Sandbox
from agentic_tools.repo import RepoLimits, build_repo_server

CallRepo = Callable[..., Awaitable[tuple[bool, str]]]
"""`await call(tool, limits=None, **arguments)` -> (is_error, text)."""


async def call_tool(
    sandbox: Sandbox,
    tool: str,
    arguments: dict[str, Any],
    limits: RepoLimits | None = None,
    *,
    writable: bool = False,
) -> tuple[bool, str]:
    """Call one `repo` tool through a fresh in-memory MCP client; returns (is_error, text). With
    `writable`, `sandbox` must be a worktree."""
    server = build_repo_server(sandbox, writable=writable, limits=limits)
    async with Client(server) as client:
        result = await client.call_tool(tool, arguments)
    text = "\n".join(c.text for c in result.content if c.type == "text")
    return result.is_error, text


class FakeGithub:
    """Implements `GithubPublisher` without GitHub: hands out `token`, records the pull requests
    it is asked to open (numbered from 1) and the repos it creates (`repos`, by full name; a test
    may add one). Set `refuse` to make it raise instead."""

    def __init__(self, token: str = "ghs_faketoken0000") -> None:
        self.token = SecretStr(token)
        self.tokens_issued = 0
        self.pulls: list[dict[str, str]] = []
        self.repos: dict[str, RepoInfo] = {}
        self.created: list[dict[str, Any]] = []
        self.refuse: Exception | None = None

    async def get_repo(self, installation_id: int, full_name: str) -> RepoInfo | None:
        if self.refuse is not None:
            raise self.refuse
        return self.repos.get(full_name)

    async def create_org_repo(
        self,
        installation_id: int,
        org: str,
        name: str,
        *,
        private: bool,
        description: str | None = None,
        gitignore_template: str | None = None,
        license_template: str | None = None,
    ) -> RepoInfo:
        if self.refuse is not None:
            raise self.refuse
        full_name = f"{org}/{name}"
        if full_name in self.repos:
            raise RepoExistsError(f"repo {full_name} already exists")
        self.created.append(
            {
                "repo": full_name,
                "private": private,
                "description": description,
                "gitignore": gitignore_template,
                "license": license_template,
            }
        )
        repo = RepoInfo(
            id=len(self.repos) + 1,
            full_name=full_name,
            name=name,
            owner=org,
            private=private,
            default_branch="main",
            html_url=f"https://github.com/{full_name}",
            created_at=datetime.now(UTC),
        )
        self.repos[full_name] = repo
        return repo

    async def installation_token(self, installation_id: int) -> SecretStr:
        self.tokens_issued += 1
        return self.token

    async def open_pull_request(
        self, installation_id: int, full_name: str, *, head: str, base: str, title: str, body: str
    ) -> PullRequestInfo:
        if self.refuse is not None:
            raise self.refuse
        self.pulls.append(
            {"repo": full_name, "head": head, "base": base, "title": title, "body": body}
        )
        number = len(self.pulls)
        return PullRequestInfo(
            number=number,
            url=f"https://github.com/{full_name}/pull/{number}",
            head=head,
            base=base,
        )


def bare_remote(origin: Path, dest: Path) -> str:
    """A bare clone of the local repo `origin` at `dest`, standing in for its GitHub remote;
    returns its `file://` URL."""
    subprocess.run(
        ["git", "clone", "-q", "--bare", str(origin), str(dest)],
        check=True,
        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull},
    )
    return dest.resolve().as_uri()
