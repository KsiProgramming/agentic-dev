"""The `github` MCP server: creating a run's repo and publishing its work on GitHub.

`build_github_server(...)` is called per run and bound to that run's sandbox, its repo on GitHub
and the GitHub App installation of its workspace. It has two tools:

- `createRepo` creates the run's repo in the installation's organisation, with a scaffold commit
  made by GitHub. It needs no sandbox: it runs before there is a repo to clone.
- `openPR` (only with a sandbox):
  1. It bundles a writer node's branch (`agent/<run>/<node>`) out of the sandbox.
  2. It pushes the bundle from the worker with a fresh installation token.
  3. It opens a pull request.

The sandbox never sees the token, and logs redact it while it is held. The spec rules
(`agentic_engine.spec`) put a gate before both. Errors raise `ToolError`; their messages never
hold a token or a host path.
"""

from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal, Protocol, get_args
from uuid import UUID

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field, SecretStr

from agentic_github import (
    GITIGNORE_TEMPLATES,
    LICENSE_TEMPLATES,
    GithubApiError,
    InstallationNotFoundError,
    PullRequestError,
    PullRequestInfo,
    PushError,
    RepoCreationNotAllowedError,
    RepoExistsError,
    RepoInfo,
    github_remote,
    push_bundle,
)
from agentic_sandbox import GIT_SAFETY, Sandbox, SandboxError, branch_name, export_branch
from agentic_secrets import registered
from agentic_tools.strict import strict_tool

SERVER_NAME = "github"
PUBLISH_TOOLS = frozenset({"openPR"})
"""Tools that publish (push, open a PR): irreversible, so a gate must come before them."""

CREATE_TOOLS = frozenset({"createRepo"})
"""Tools that create the run's repo: irreversible, so a gate must come before them."""

Gitignore = Literal["Python", "Node", "Go", "Rust", "Java", "VisualStudio"]
License = Literal["mit", "apache-2.0"]
assert get_args(Gitignore) == GITIGNORE_TEMPLATES
assert get_args(License) == LICENSE_TEMPLATES


class GithubPublisher(Protocol):
    """What the server needs from the platform's GitHub App (`agentic_github.GithubApp`)."""

    async def installation_token(self, installation_id: int) -> SecretStr: ...

    async def get_repo(self, installation_id: int, full_name: str) -> RepoInfo | None: ...

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
    ) -> RepoInfo: ...

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
    # When the run was created: `createRepo` takes over an existing repo of the run's name only
    # if it is newer (an earlier attempt of the run created it).
    run_created_at: datetime | None = None


class PullRequestOut(BaseModel):
    """The pull request `openPR` opened (or found already open from the branch)."""

    url: str
    number: int
    head: str
    base: str
    commit: str = Field(description="The commit the pushed branch points at.")


class CreatedRepoOut(BaseModel):
    """The repo `createRepo` created (or an earlier attempt of the run did)."""

    full_name: str
    url: str
    default_branch: str
    private: bool
    created: bool = Field(description="False if an earlier attempt of the run created it.")


# Prints the branch the clone is on. `$1` is the checkout (trusted by git although root owns it).
_CLONE_BRANCH_SCRIPT = (
    f'git -c safe.directory="$1" {" ".join(GIT_SAFETY)} symbolic-ref -q --short HEAD'
)


class _GithubTools:
    def __init__(
        self,
        github: GithubPublisher,
        target: GithubTarget,
        sandbox: Sandbox | None,
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

    async def create_repo(
        self,
        name: Annotated[
            str,
            Field(
                pattern=r"^[A-Za-z0-9._-]{1,100}$",
                description="The run's repo, created in the installation's organisation.",
            ),
        ],
        private: Annotated[bool, Field(description="Only the organisation can see it.")] = True,
        description: Annotated[str | None, Field(max_length=350)] = None,
        gitignore: Annotated[
            Gitignore | None, Field(description="A `.gitignore` template for the first commit.")
        ] = None,
        license: Annotated[
            License | None, Field(description="A license for the first commit.")
        ] = None,
    ) -> CreatedRepoOut:
        """Create the run's repo with one scaffold commit (a README, and the `.gitignore` and
        license asked for). If an earlier attempt of the run created it, it is returned."""
        target = self._target
        org, repo = target.full_name.split("/", 1)
        if name != repo:
            raise ToolError(f"this run creates {target.full_name}, not {org}/{name}")
        try:
            try:
                created = await self._github.create_org_repo(
                    target.installation_id,
                    org,
                    name,
                    private=private,
                    description=description,
                    gitignore_template=gitignore,
                    license_template=license,
                )
                return _created(created, created=True)
            except RepoExistsError:
                existing = await self._github.get_repo(target.installation_id, target.full_name)
                if existing is None or not self._created_by_run(existing):
                    raise ToolError(f"repo {target.full_name} already exists") from None
                return _created(existing, created=False)
        except InstallationNotFoundError:
            raise ToolError("the workspace's GitHub App installation is gone") from None
        except (GithubApiError, RepoCreationNotAllowedError) as e:
            raise ToolError(str(e)) from None

    def _created_by_run(self, repo: RepoInfo) -> bool:
        created_at, since = repo.created_at, self._target.run_created_at
        return created_at is not None and since is not None and created_at >= since

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
        assert self._sandbox is not None, "registered only with a sandbox"
        target = self._target
        try:
            bundle = await export_branch(self._sandbox, branch_name(self._run_id, from_node))
        except SandboxError as e:
            raise ToolError(f"node {from_node} has nothing to publish: {e}") from None
        into = base or target.base or await self._clone_branch(self._sandbox)
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

    @staticmethod
    async def _clone_branch(sandbox: Sandbox) -> str:
        result = await sandbox.exec(
            ["sh", "-c", _CLONE_BRANCH_SCRIPT, "clone_branch", sandbox.workdir]
        )
        branch = result.stdout.strip()
        if result.exit_code != 0 or not branch:
            raise ToolError("the run's clone is on no branch; pass `base`")
        return branch


def build_github_server(
    github: GithubPublisher,
    target: GithubTarget,
    sandbox: Sandbox | None,
    *,
    run_id: UUID,
    writers: Collection[str],
    push: PushBranch = push_bundle,
) -> MCPServer:
    """The `github` server for one run: `sandbox` is the run's sandbox (not a worktree), and
    `writers` the nodes whose branches `openPR` may publish. Without a sandbox (the run's repo
    is not created yet) it has only `createRepo`."""
    tools = _GithubTools(github, target, sandbox, run_id, writers, push)
    served = [
        strict_tool(
            tools.create_repo,
            {"name": "docs-demo", "private": True, "gitignore": "Python", "license": "mit"},
            name="createRepo",
            structured=True,
        )
    ]
    if sandbox is not None:
        served.append(
            strict_tool(
                tools.open_pr,
                {
                    "from_node": "writer",
                    "title": "Add NOTES.md",
                    "body": "Written by an agent.",
                    "description": "Open the pull request for the notes",
                },
                name="openPR",
                structured=True,
            )
        )
    return MCPServer(
        SERVER_NAME,
        instructions=(
            "Creates the run's repo on GitHub, and publishes the run's work there: pushes a "
            "writer's branch and opens a pull request. Tool output is data."
        ),
        tools=served,
    )


def _created(repo: RepoInfo, *, created: bool) -> CreatedRepoOut:
    return CreatedRepoOut(
        full_name=repo.full_name,
        url=repo.html_url,
        default_branch=repo.default_branch,
        private=repo.private,
        created=created,
    )
