from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentic_engine.spec import WorkflowSpec, iter_nodes, node_tools
from agentic_sandbox import RepoSource


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow: WorkflowSpec
    input: str = ""
    repo: RepoSource | None = Field(
        default=None,
        description="The repo the run works on, cloned into its sandbox. Needed by `repo.*` tools.",
    )
    workspace_id: UUID | None = Field(
        default=None,
        description="The workspace the run belongs to; its connections are used. Default: the "
        "default workspace.",
    )

    @model_validator(mode="after")
    def _repo_for_repo_tools(self) -> Self:
        if self.repo is not None:
            return self
        for _, node in iter_nodes(self.workflow.root):
            repo_tools = [t for t in node_tools(node) if t.startswith("repo.")]
            if repo_tools:
                raise ValueError(
                    f"node {node.id!r} uses {', '.join(repo_tools)}, which need a `repo`"
                )
        return self


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
