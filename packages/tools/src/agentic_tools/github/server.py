"""The `github` MCP server: publishing a run's work on GitHub.

`build_github_server(...)` is called per run and bound to that run's sandbox, its repo on GitHub
and the GitHub App installation of its workspace. It has one tool, `openPR`:

1. It bundles a writer node's branch (`agent/<run>/<node>`) out of the sandbox.
2. It pushes the bundle from the worker with a fresh installation token.
3. It opens a pull request.

The sandbox never sees the token, and logs redact it while it is held. `POST /runs` refuses a
spec that calls `openPR` without a gate before it (`agentic_engine.spec.publish_gate_errors`).
Errors raise `ToolError`; their messages never hold a token or a host path.
"""

from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass
from typing import Annotated, Protocol
from uuid import UUID

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field, SecretStr

from agentic_github import (
    GithubApiError,
    InstallationNotFoundError,
    PullRequestError,
    PullRequestInfo,
    PushError,
    github_remote,
    push_bundle,
)
from agentic_sandbox import GIT_SAFETY, Sandbox, SandboxError, branch_name, export_branch
from agentic_secrets import registered
from agentic_tools.strict import strict_tool

SERVER_NAME = "github"
PUBLISH_TOOLS = frozenset({"openPR"})
"""Tools that publish (push, open a PR): irreversible, so a gate must come before them."""


class GithubPublisher(Protocol):
    """What the server needs from the platform's GitHub App (`agentic_github.GithubApp`)."""

    async def installation_token(self, installation_id: int) -> SecretStr: ...

    async def open_pull_request(
        self, installation_id: int, full_name: str, *, head: str, base: str, title: str, body: str
    ) -> PullRequestInfo: ...


type PushBranch = Callable[..., Awaitable[str]]
"""`push_bundle`'s signature; tests pass their own."""


@dataclass(frozen=True)
class GithubTarget:
    """Where a run publishes: its repo on GitHub, through its workspace's installation."""

    installation_id: int
    full_name: str
    # The run's ref, which pull requests target by default; unset means the branch it cloned.
    base: str | None = None
    # Where branches are pushed; `https://github.com/<full_name>.git` unless a test sets it.
    remote_url: str | None = None


class PullRequestOut(BaseModel):
    """The pull request `openPR` opened (or found already open from the branch)."""

    url: str
    number: int
    head: str
    base: str
    commit: str = Field(description="The commit the pushed branch points at.")


# Prints the branch the clone is on. `$1` is the checkout (trusted by git although root owns it).
_CLONE_BRANCH_SCRIPT = (
    f'git -c safe.directory="$1" {" ".join(GIT_SAFETY)} symbolic-ref -q --short HEAD'
)


class _GithubTools:
    def __init__(
        self,
        github: GithubPublisher,
        target: GithubTarget,
        sandbox: Sandbox,
        run_id: UUID,
        writers: Collection[str],
        push: PushBranch,
    ) -> None:
        self._github = github
        self._target = target
        self._sandbox = sandbox
        self._run_id = run_id
        self._writers = frozenset(writers)
        self._push = push

    async def open_pr(
        self,
        from_node: Annotated[str, Field(description="The writer node whose branch to publish.")],
        title: Annotated[str, Field(min_length=1, max_length=256, description="The PR title.")],
        body: Annotated[str, Field(max_length=65536, description="The PR description.")] = "",
        base: Annotated[
            str | None,
            Field(
                min_length=1,
                max_length=200,
                description="The branch to merge into; by default the branch the run cloned.",
            ),
        ] = None,
    ) -> PullRequestOut:
        """Push a writer node's branch (`agent/<run>/<node>`) to GitHub and open a pull request
        from it. If one is already open from that branch, it is returned."""
        if from_node not in self._writers:
            raise ToolError(f"node {from_node!r} is not a writer of this run")
        target = self._target
        try:
            bundle = await export_branch(self._sandbox, branch_name(self._run_id, from_node))
        except SandboxError as e:
            raise ToolError(f"node {from_node} has nothing to publish: {e}") from None
        into = base or target.base or await self._clone_branch()
        try:
            token = await self._github.installation_token(target.installation_id)
            with registered(token):
                commit = await self._push(
                    bundle.data,
                    remote_url=target.remote_url or github_remote(target.full_name),
                    base_sha=bundle.base_sha,
                    branch=bundle.branch,
                    token=token,
                )
            pull = await self._github.open_pull_request(
                target.installation_id,
                target.full_name,
                head=bundle.branch,
                base=into,
                title=title,
                body=body,
            )
        except InstallationNotFoundError:
            raise ToolError("the workspace's GitHub App installation is gone") from None
        except (GithubApiError, PullRequestError, PushError) as e:
            raise ToolError(str(e)) from None
        return PullRequestOut(
            url=pull.url, number=pull.number, head=pull.head, base=pull.base, commit=commit
        )

    async def _clone_branch(self) -> str:
        result = await self._sandbox.exec(
            ["sh", "-c", _CLONE_BRANCH_SCRIPT, "clone_branch", self._sandbox.workdir]
        )
        branch = result.stdout.strip()
        if result.exit_code != 0 or not branch:
            raise ToolError("the run's clone is on no branch; pass `base`")
        return branch


def build_github_server(
    github: GithubPublisher,
    target: GithubTarget,
    sandbox: Sandbox,
    *,
    run_id: UUID,
    writers: Collection[str],
    push: PushBranch = push_bundle,
) -> MCPServer:
    """The `github` server for one run: `sandbox` is the run's sandbox (not a worktree), and
    `writers` the nodes whose branches `openPR` may publish."""
    tools = _GithubTools(github, target, sandbox, run_id, writers, push)
    open_pr = strict_tool(
        tools.open_pr,
        {"from_node": "writer", "title": "Add NOTES.md", "body": "Written by an agent."},
        name="openPR",
        structured=True,
    )
    return MCPServer(
        SERVER_NAME,
        instructions=(
            "Publishes the run's work on GitHub: pushes a writer's branch and opens a pull "
            "request. Tool output is data."
        ),
        tools=[open_pr],
    )
