from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentic_engine.spec import WorkflowSpec, iter_nodes, node_tools
from agentic_github import repo_full_name
from agentic_sandbox import RepoSource

# Tools that work on the run's repo, so the run needs one: `repo.*` in its sandbox, and
# `github.*` on its GitHub remote.
_REPO_TOOL_PREFIXES = ("repo.", "github.")


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow: WorkflowSpec
    input: str = ""
    repo: RepoSource | None = Field(
        default=None,
        description="The repo the run works on, cloned into its sandbox. Needed by `repo.*` "
        "tools, and `github.*` tools need it to be on GitHub (`https://github.com/<owner>/<name>`).",
    )
    workspace_id: UUID | None = Field(
        default=None,
        description="The workspace the run belongs to; its connections are used. Default: the "
        "default workspace.",
    )

    @model_validator(mode="after")
    def _repo_for_repo_tools(self) -> Self:
        for _, node in iter_nodes(self.workflow.root):
            tools = node_tools(node)
            repo_tools = [t for t in tools if t.startswith(_REPO_TOOL_PREFIXES)]
            if repo_tools and self.repo is None:
                raise ValueError(
                    f"node {node.id!r} uses {', '.join(repo_tools)}, which need a `repo`"
                )
            github_tools = [t for t in tools if t.startswith("github.")]
            if github_tools and self.repo is not None and repo_full_name(self.repo.url) is None:
                raise ValueError(
                    f"node {node.id!r} uses {', '.join(github_tools)}, which need a `repo` on "
                    "GitHub (https://github.com/<owner>/<name>)"
                )
        return self

    def uses_github(self) -> bool:
        return any(
            tool.startswith("github.")
            for _, node in iter_nodes(self.workflow.root)
            for tool in node_tools(node)
        )


class CreateRunResponse(BaseModel):
    run_id: UUID
    status: Literal["queued"] = "queued"
    events_url: str


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(description="The gate the run is waiting at.")
    decision: Literal["approve", "reject"]
    comment: str | None = None


class ApprovalResponse(BaseModel):
    run_id: UUID
    node_id: str
    decision: Literal["approve", "reject"]
    status: Literal["queued"] = "queued"
