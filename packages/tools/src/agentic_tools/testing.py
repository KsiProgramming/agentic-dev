"""Test helpers shared by the tools and worker test suites."""

import os
import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from mcp import Client
from pydantic import SecretStr

from agentic_github import PullRequestInfo
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
    """Implements `GithubPublisher` without GitHub: hands out `token` and records the pull
    requests it is asked to open (numbered from 1). Set `refuse` to make it raise instead."""

    def __init__(self, token: str = "ghs_faketoken0000") -> None:
        self.token = SecretStr(token)
        self.tokens_issued = 0
        self.pulls: list[dict[str, str]] = []
        self.refuse: Exception | None = None

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
