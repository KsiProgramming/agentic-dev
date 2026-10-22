from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    computed_field,
    model_validator,
)

from agentic_engine.spec import WorkflowSpec, iter_nodes, node_tools
from agentic_engine.templates import get_template
from agentic_github import repo_full_name
from agentic_sandbox import RepoSource

# Tools that work on the run's repo, so the run needs one: `repo.*` in its sandbox, and
# `github.*` on its GitHub remote.
_REPO_TOOL_PREFIXES = ("repo.", "github.")


class TemplateRun(BaseModel):
    """A run of a template (`GET /templates`) with its options."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="The template's id, e.g. `generate-docs`.")
    parameters: dict[str, JsonValue] = Field(
        default_factory=dict[str, JsonValue],
        description="The template's options, as its `parameters` schema describes.",
    )

    def build_spec(self) -> WorkflowSpec:
        template = get_template(self.id)
        if template is None:
            raise ValueError(f"unknown template {self.id!r}")
        try:
            return template.build_spec(self.parameters)
        except ValidationError as e:
            reasons = [
                f"parameters.{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
                for err in e.errors()
            ]
            raise ValueError("; ".join(reasons)) from None


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow: WorkflowSpec | None = Field(
        default=None, description="The workflow to run. Give this or `template`, not both."
    )
    template: TemplateRun | None = Field(
        default=None,
        description="A template to build the workflow from. Give this or `workflow`, not both.",
    )
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
    def _one_workflow(self) -> Self:
        if (self.workflow is None) == (self.template is None):
            raise ValueError("give either `workflow` or `template`")
        if self.template is not None:
            self.workflow = self.template.build_spec()
        return self

    @model_validator(mode="after")
    def _repo_for_repo_tools(self) -> Self:
        for _, node in iter_nodes(self.spec().root):
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

    def spec(self) -> WorkflowSpec:
        """The workflow to run: `workflow`, or the one built from `template`."""
        assert self.workflow is not None, "validated: built from the template if not given"
        return self.workflow

    def uses_github(self) -> bool:
        return any(
            tool.startswith("github.")
            for _, node in iter_nodes(self.spec().root)
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


type RunStatus = Literal["queued", "running", "waiting", "completed", "failed", "cancelled"]


class WorkflowRef(BaseModel):
    id: str
    name: str


class WaitingGate(BaseModel):
    node_id: str = Field(description="The gate node the run is paused at.")
    title: str | None = None


class RunSummary(BaseModel):
    """A run as the runs list shows it. Status, timings, PR URL and the waiting gate come from
    the run's events."""

    id: UUID
    workspace_id: UUID
    status: RunStatus
    workflow: WorkflowRef
    template_id: str | None = Field(description="The template the workflow was built from.")
    repo: RepoSource | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    pr_url: str | None = Field(description="The last pull request the run opened.")
    waiting_gate: WaitingGate | None = Field(description="Set while the run waits at a gate.")
    rerun_of: UUID | None = Field(description="The run this one repeats.")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def duration_ms(self) -> int | None:
        """From start to end; `null` until the run has ended."""
        if self.started_at is None or self.finished_at is None:
            return None
        return round((self.finished_at - self.started_at).total_seconds() * 1000)


class RunDetail(RunSummary):
    input: str
    failure_reason: str | None = Field(description="Why the run failed, if it did.")


class RunSummaryPage(BaseModel):
    items: list[RunSummary]
    next_cursor: str | None = Field(description="Pass as `cursor` for the next page.")
