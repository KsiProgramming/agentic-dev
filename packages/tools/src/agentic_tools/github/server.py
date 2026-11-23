"""The `github` MCP server: creating a run's repo and publishing its work on GitHub.

`build_github_server(...)` is called per run and bound to that run's sandbox, its repo on GitHub
and the GitHub App installation of its workspace. It has two tools:

- `createRepo` creates the run's repo in the installation's organisation, with a scaffold commit
  made by GitHub. It needs no sandbox: it runs before there is a repo to clone.
- `openPR` (only with a sandbox):
  1. It bundles a writer node's branch (`agent/<run>/<node>`) out of the sandbox.
  2. It pushes the bundle from the worker with a fresh installation token.
  3. It opens a pull request.

  In a follow-up of a pull request review (7.6, `GithubTarget.review`) it pushes onto that pull
  request's branch instead, as a fast-forward from the commit the run before pushed, opens no pull
  request, and posts one fixed comment on it saying what was pushed for whom.

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
from pydantic import BaseModel, Field, JsonValue, SecretStr

from agentic_github import (
    GITIGNORE_TEMPLATES,
    LICENSE_TEMPLATES,
    GithubApiError,
    GithubReviews,
    InstallationNotFoundError,
    PullRequestError,
    PullRequestInfo,
    PushError,
    PushOnto,
    RepoCreationNotAllowedError,
    RepoExistsError,
    RepoInfo,
    github_remote,
    push_bundle,
)
from agentic_runtime.plans import PlanError, PlanTarget, WritePlan
from agentic_sandbox import (
    GIT_SAFETY,
    BranchBundle,
    Sandbox,
    SandboxError,
    branch_name,
    export_branch,
)
from agentic_secrets import registered
from agentic_tools.strict import planned, stale, strict_tool

SERVER_NAME = "github"
PUBLISH_TOOLS = frozenset({"openPR"})
"""Tools that publish (push, open a PR): irreversible, so a gate must come before them."""

CREATE_TOOLS = frozenset({"createRepo"})
"""Tools that create the run's repo: irreversible, so a gate must come before them."""

Gitignore = Literal["Python", "Node", "Go", "Rust", "Java", "VisualStudio"]
License = Literal["mit", "apache-2.0"]
assert get_args(Gitignore) == GITIGNORE_TEMPLATES
assert get_args(License) == LICENSE_TEMPLATES


class GithubPublisher(GithubReviews, Protocol):
    """What the server needs from the platform's GitHub App (`agentic_github.GithubApp`), with
    the review calls a follow-up's worker and `openPR` make (7.6)."""

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

    async def find_open_pull_request(
        self, installation_id: int, full_name: str, head: str
    ) -> PullRequestInfo | None: ...


type PushBranch = Callable[..., Awaitable[str]]
"""`push_bundle`'s signature; tests pass their own."""


@dataclass(frozen=True)
class PullRequestTarget:
    """The pull request a follow-up of its review publishes to (7.6): its branch, the commit the
    run before pushed there, who asked, and the run's page for the comment."""

    number: int
    url: str
    head_branch: str
    after_sha: str
    author: str
    run_url: str | None = None


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
    # A follow-up of a pull request review (7.6): `openPR` pushes onto this pull request.
    review: PullRequestTarget | None = None


class PullRequestOut(BaseModel):
    """The pull request `openPR` opened (or found already open from the branch)."""

    url: str
    number: int
    head: str
    base: str
    commit: str = Field(description="The commit the pushed branch points at.")
    repo: str = Field(default="", description="The repo's full name.")
    title: str = Field(default="", description="The title the pull request was opened with.")
    body: str = Field(default="", description="The body the pull request was opened with.")
    updated: bool = Field(
        default=False,
        description="True when a follow-up of a review pushed to an open pull request (7.6) "
        "instead of opening one.",
    )


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
        plan: bool = False,
        expect: dict[str, JsonValue] | None = None,
    ) -> CreatedRepoOut:
        """Create the run's repo with one scaffold commit (a README, and the `.gitignore` and
        license asked for). If an earlier attempt of the run created it, it is returned."""
        target = self._target
        org, repo = target.full_name.split("/", 1)
        if name != repo:
            raise ToolError(f"this run creates {target.full_name}, not {org}/{name}")
        if plan:
            return await self._plan_repo(private, description, gitignore, license)
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
                    if expect is not None:
                        raise stale(f"{target.full_name} was taken by someone else") from None
                    raise ToolError(f"repo {target.full_name} already exists") from None
                return _created(existing, created=False)
        except InstallationNotFoundError:
            raise ToolError("the workspace's GitHub App installation is gone") from None
        except (GithubApiError, RepoCreationNotAllowedError) as e:
            raise ToolError(str(e)) from None

    async def _plan_repo(
        self, private: bool, description: str | None, gitignore: str | None, license: str | None
    ) -> CreatedRepoOut:
        """What `createRepo` would do: whether the name is free, or already this run's."""
        target = self._target
        try:
            existing = await self._github.get_repo(target.installation_id, target.full_name)
        except InstallationNotFoundError:
            raise ToolError("the workspace's GitHub App installation is gone") from None
        except GithubApiError as e:
            raise ToolError(str(e)) from None
        kind = "private" if private else "public"
        taken = existing is not None
        mine = existing is not None and self._created_by_run(existing)
        extras = [x for x in (gitignore and f".gitignore {gitignore}", license) if x]
        summary = f"Create the {kind} repo {target.full_name}"
        if extras:
            summary += f" with {', '.join(extras)}"
        if mine:
            summary = f"{target.full_name} was created by this run already"
        return planned(
            WritePlan(
                tool="github.createRepo",
                action="create_repo",
                summary=summary,
                target=PlanTarget(
                    kind="repo",
                    label=target.full_name,
                    url=existing.html_url if existing else None,
                ),
                fields={
                    "full_name": target.full_name,
                    "private": existing.private if mine and existing else private,
                    "description": description,
                    "gitignore": gitignore,
                    "license": license,
                },
                expect={"name": "created_by_run" if mine else "free"},
                error=PlanError(
                    code="repo_exists",
                    message=f"repo {target.full_name} already exists and is not this run's",
                )
                if taken and not mine
                else None,
            )
        )

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
        plan: bool = False,
        expect: dict[str, JsonValue] | None = None,
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
        if expect is not None and expect.get("tip") not in (None, bundle.head_sha):
            raise stale(f"the branch of {from_node} is now at {bundle.head_sha[:7]}")
        if plan:
            return await self._plan_pr(bundle, into, title, body)
        if target.review is not None:
            return await self._update(bundle, into, target.review)
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
            url=pull.url,
            number=pull.number,
            head=pull.head,
            base=pull.base,
            commit=commit,
            repo=target.full_name,
            title=title,
            body=body,
        )

    async def _plan_pr(
        self, bundle: BranchBundle, into: str, title: str, body: str
    ) -> PullRequestOut:
        """What `openPR` would do: push the branch and open a pull request, or (a follow-up, 7.6)
        push onto the review's pull request and say so on it."""
        target = self._target
        commits = f"{bundle.commits} commit{'' if bundle.commits == 1 else 's'}"
        fields: dict[str, JsonValue] = {
            "repo": target.full_name,
            "head": bundle.branch,
            "base": into,
            "commit": bundle.head_sha,
            "commits": bundle.commits,
        }
        expect: dict[str, JsonValue] = {"tip": bundle.head_sha}
        review = target.review
        try:
            if review is not None:
                return await self._plan_push(bundle, commits, fields, expect, review)
            existing = await self._github.find_open_pull_request(
                target.installation_id, target.full_name, bundle.branch
            )
        except InstallationNotFoundError:
            raise ToolError("the workspace's GitHub App installation is gone") from None
        except GithubApiError as e:
            raise ToolError(str(e)) from None
        fields |= {
            "title": title,
            "body": body,
            "existing_pr": existing.number if existing else None,
        }
        summary = f"Push {commits} to {bundle.branch} and open a pull request into {into}"
        if existing is not None:
            summary = f"Push {commits} to {bundle.branch}; pull request #{existing.number} is open"
        return planned(
            WritePlan(
                tool="github.openPR",
                action="open_pr",
                summary=summary,
                target=PlanTarget(
                    kind="repo",
                    label=target.full_name,
                    url=existing.url if existing else f"https://github.com/{target.full_name}",
                ),
                fields=fields,
                body=body,
                expect=expect,
            )
        )

    async def _plan_push(
        self,
        bundle: BranchBundle,
        commits: str,
        fields: dict[str, JsonValue],
        expect: dict[str, JsonValue],
        review: PullRequestTarget,
    ) -> PullRequestOut:
        """The follow-up's plan: a fast-forward of the review's branch from `after_sha`."""
        target = self._target
        state = await self._github.pull_request(
            target.installation_id, target.full_name, review.number
        )
        problem: PlanError | None = None
        if state is None or not state.is_open:
            problem = PlanError(
                code="pr_not_open", message=f"pull request #{review.number} is not open"
            )
        elif state.head_sha and state.head_sha != review.after_sha:
            problem = PlanError(
                code="pr_head_moved",
                message=f"the branch of pull request #{review.number} moved since the review",
            )
        fields |= {
            "head": review.head_branch,
            "number": review.number,
            "pr_head": state.head_sha if state else None,
        }
        return planned(
            WritePlan(
                tool="github.openPR",
                action="push_to_pr",
                summary=(
                    f"Push {commits} onto {review.head_branch} "
                    f"(pull request #{review.number}) and comment on it"
                ),
                target=PlanTarget(
                    kind="pull_request",
                    label=f"{target.full_name}#{review.number}",
                    url=review.url,
                ),
                fields=fields,
                body=review_reply(bundle.head_sha, review.author, self._run_id, review.run_url),
                expect=expect,
                error=problem,
            )
        )

    async def _update(
        self, bundle: BranchBundle, into: str, review: PullRequestTarget
    ) -> PullRequestOut:
        """Push onto the follow-up's pull request and say so on it, once."""
        target = self._target
        try:
            token = await self._github.installation_token(target.installation_id)
            with registered(token):
                commit = await self._push(
                    bundle.data,
                    remote_url=target.remote_url or github_remote(target.full_name),
                    base_sha=bundle.base_sha,
                    branch=bundle.branch,
                    token=token,
                    onto=PushOnto(branch=review.head_branch, expected=review.after_sha),
                )
            await self._reply(review, commit)
        except InstallationNotFoundError:
            raise ToolError("the workspace's GitHub App installation is gone") from None
        except (GithubApiError, PushError) as e:
            raise ToolError(str(e)) from None
        return PullRequestOut(
            url=review.url,
            number=review.number,
            head=review.head_branch,
            base=into,
            commit=commit,
            repo=target.full_name,
            updated=True,
        )

    async def _reply(self, review: PullRequestTarget, commit: str) -> None:
        """The fixed comment on the pull request, unless this run posted it already (a step
        run again)."""
        target = self._target
        marker = str(self._run_id)
        posted = await self._github.review_items(
            target.installation_id, target.full_name, review.number
        )
        if any(item.from_bot and marker in item.body for item in posted):
            return
        await self._github.comment_on_pull_request(
            target.installation_id,
            target.full_name,
            review.number,
            review_reply(commit, review.author, self._run_id, review.run_url),
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
            plannable=True,
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
                plannable=True,
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


def review_reply(commit: str, author: str, run_id: UUID, run_url: str | None) -> str:
    """The one comment a follow-up posts on its pull request (7.6): platform text, never an
    agent's. It holds the run's full id, so a step run again finds it."""
    run = f"[{str(run_id)[:8]}]({run_url})" if run_url else f"`{run_id}`"
    if run_url and str(run_id) not in run_url:
        run += f" (`{run_id}`)"
    return f"Pushed `{commit[:7]}` for @{author}'s review, run {run}."


def _created(repo: RepoInfo, *, created: bool) -> CreatedRepoOut:
    return CreatedRepoOut(
        full_name=repo.full_name,
        url=repo.html_url,
        default_branch=repo.default_branch,
        private=repo.private,
        created=created,
    )
