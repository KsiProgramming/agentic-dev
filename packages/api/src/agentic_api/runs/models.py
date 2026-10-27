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

from agentic_api.workspaces.models import budget_field
from agentic_engine.gate import MAX_REVIEW_FILES, EditErrorCode, FileEdit
from agentic_engine.spec import (
    ValidationIssue,
    WorkflowSpec,
    iter_nodes,
    messages,
    node_tools,
    tool_issues,
)
from agentic_engine.templates import NewRepo, get_template
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


class PolicyErrorDetail(BaseModel):
    """The `detail` of a run refused because its workflow is above the workspace's run limits, or
    has a budget that cannot be enforced (an agent's model has no price): `errors` names each
    problem (node, limit and value), `message` says it for people. `issues` are the same
    problems with their code, path and node, as `POST /workflows/{id}/validate` gives them."""

    code: Literal["policy_limits"] = "policy_limits"
    message: str
    errors: list[str]
    issues: list[ValidationIssue]


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
    new_repo: NewRepo | None = Field(
        default=None,
        description="A repo to create for the run, in the organisation the workspace's GitHub "
        "App is installed on, instead of `repo`. The run first waits for approval to create it "
        "(gate `approve_repo`), creates it (`create_repo`), then runs the workflow on it.",
    )
    workspace_id: UUID | None = Field(
        default=None,
        description="The workspace the run belongs to; its connections are used. Default: the "
        "default workspace.",
    )
    budget_usd: float | None = budget_field(
        "USD the run may spend, a hard stop once reached. Unset: the workspace's default budget."
    )

    @model_validator(mode="after")
    def _one_workflow(self) -> Self:
        if (self.workflow is None) == (self.template is None):
            raise ValueError("give either `workflow` or `template`")
        if self.template is not None:
            self.workflow = self.template.build_spec()
        return self

    @model_validator(mode="after")
    def _one_repo(self) -> Self:
        if self.repo is not None and self.new_repo is not None:
            raise ValueError("give either `repo` or `new_repo`")
        return self

    @model_validator(mode="after")
    def _known_tools(self) -> Self:
        if issues := tool_issues(self.spec().root):
            raise ValueError("; ".join(messages(issues)))
        return self

    @model_validator(mode="after")
    def _repo_for_repo_tools(self) -> Self:
        for _, node in iter_nodes(self.spec().root):
            tools = node_tools(node)
            repo_tools = [t for t in tools if t.startswith(_REPO_TOOL_PREFIXES)]
            if repo_tools and self.repo is None and self.new_repo is None:
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
        return uses_github(self.spec())


def uses_github(spec: WorkflowSpec) -> bool:
    """Whether a node of `spec` names a `github.*` tool."""
    return any(
        tool.startswith("github.") for _, node in iter_nodes(spec.root) for tool in node_tools(node)
    )


class RerunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    budget_usd: float | None = budget_field(
        "USD the new run may spend. Unset: the workspace's default budget as it is now."
    )


class CreateRunResponse(BaseModel):
    run_id: UUID
    status: Literal["queued"] = "queued"
    events_url: str


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(description="The gate the run is waiting at.")
    decision: Literal["approve", "reject"]
    comment: str | None = Field(
        default=None,
        max_length=2000,
        description="Why, recorded with the decision; a rejection's becomes the run's reason.",
    )
    edits: list[FileEdit] = Field(
        default_factory=list[FileEdit],
        max_length=MAX_REVIEW_FILES,
        description="An approval's new text for files of the gate's `changes` (editable ones "
        "only); the gate commits them on the writers' branches before the run goes on.",
    )


class ApprovalResponse(BaseModel):
    run_id: UUID
    node_id: str
    decision: Literal["approve", "reject"]
    status: Literal["queued"] = "queued"
    edited_files: int = Field(
        default=0, description="Files the approval changes: its edits that change a file."
    )


class EditErrorDetail(BaseModel):
    """The `detail` of an approval refused because its edits do not fit the files the gate
    showed: `code` says how, `path` names the file at fault, if one is."""

    code: EditErrorCode
    message: str
    path: str | None = None


class CancelResponse(BaseModel):
    run_id: UUID
    status: Literal["cancelling"] = Field(
        default="cancelling",
        description="The worker ends the run `cancelled`; its event stream shows when.",
    )


type RunStatus = Literal["queued", "running", "waiting", "completed", "failed", "cancelled"]


class WorkflowRef(BaseModel):
    id: str
    name: str


class WaitingGate(BaseModel):
    node_id: str = Field(description="The gate node the run is paused at.")
    title: str | None = None


class RunUsage(BaseModel):
    """Totals of the run's usage events, priced when each was logged."""

    input_tokens: int = Field(description="Uncached input tokens.")
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    estimated_usd: float = Field(description="Estimated cost in USD of the priced usage.")
    cost_complete: bool = Field(
        description="False if some usage had no price (an unknown model): `estimated_usd` is "
        "then a lower bound."
    )
    budget_usd: float | None = Field(
        default=None,
        description="The run's budget: it stops once `estimated_usd` reaches it. Unset: no cap.",
    )


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
    usage: RunUsage

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
    spec: WorkflowSpec = Field(description="The workflow spec the run was created with.")


class RunSummaryPage(BaseModel):
    items: list[RunSummary]
    next_cursor: str | None = Field(description="Pass as `cursor` for the next page.")
