from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentic_engine.spec import AgentNode, WorkflowSpec, iter_nodes
from agentic_sandbox import RepoSource


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow: WorkflowSpec
    input: str = ""
    repo: RepoSource | None = Field(
        default=None,
        description="The repo the run works on, cloned into its sandbox. Needed by `repo.*` tools.",
    )

    @model_validator(mode="after")
    def _repo_for_repo_tools(self) -> Self:
        if self.repo is not None:
            return self
        for _, node in iter_nodes(self.workflow.root):
            if isinstance(node, AgentNode):
                repo_tools = [t for t in node.tools if t.startswith("repo.")]
                if repo_tools:
                    raise ValueError(
                        f"node {node.id!r} uses {', '.join(repo_tools)}, which need a `repo`"
                    )
        return self


class CreateRunResponse(BaseModel):
    run_id: UUID
    status: Literal["queued"] = "queued"
    events_url: str
