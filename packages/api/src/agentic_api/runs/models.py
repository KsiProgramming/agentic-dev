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
from agentic_engine.artifacts import GateArtifact
from agentic_engine.gate import (
    MAX_REVIEW_FILES,
    EditErrorCode,
    FileChange,
    FileEdit,
    SelectionErrorCode,
    SelectionShown,
)
from agentic_engine.spec import (
    MAX_SELECT_ITEMS,
    REPO_TOOL_PREFIXES,
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


class StoredWorkflowRun(BaseModel):
    """A stored workflow (`POST /workflows`) to run, at one of its versions (5.7)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="The workflow's id in the run's workspace.")
    version: int | None = Field(default=None, ge=1, description="Default: the latest.")


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
        default=None,
        description="The workflow to run. Give this, `template` or `stored_workflow`, only one.",
    )
    template: TemplateRun | None = Field(
        default=None,
        description="A template to build the workflow from. Give this, `workflow` or "
        "`stored_workflow`, only one.",
    )
    stored_workflow: StoredWorkflowRun | None = Field(
        default=None,
        description="A version of a stored workflow of the workspace to run; the run records "
        "it. Give this, `workflow` or `template`, only one.",
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
    trigger: Literal["manual", "api"] = Field(
        default="api",
        description="Who starts the run: `manual` for a person in the web app, `api` for a "
        "script or another client.",
    )
    budget_usd: float | None = budget_field(
        "USD the run may spend, a hard stop once reached. Unset: the workspace's default budget."
    )

    @model_validator(mode="after")
    def _one_workflow(self) -> Self:
        sources = [self.workflow, self.template, self.stored_workflow]
        if sum(source is not None for source in sources) != 1:
            raise ValueError("give one of `workflow`, `template` and `stored_workflow`")
        if self.template is not None:
            self.workflow = self.template.build_spec()
        return self

    @model_validator(mode="after")
    def _one_repo(self) -> Self:
        if self.repo is not None and self.new_repo is not None:
            raise ValueError("give either `repo` or `new_repo`")
        return self

    @model_validator(mode="after")
    def _spec_fits(self) -> Self:
        if self.workflow is not None:  # A stored workflow is checked once read (`with_spec`).
            self._check_spec()
        return self

    def _check_spec(self) -> None:
        """Every tool is known, and the repo the tools need is given."""
        if issues := tool_issues(self.spec().root):
            raise ValueError("; ".join(messages(issues)))
        for _, node in iter_nodes(self.spec().root):
            tools = node_tools(node)
            repo_tools = [t for t in tools if t.startswith(REPO_TOOL_PREFIXES)]
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

    def spec(self) -> WorkflowSpec:
        """The workflow to run: `workflow`, the one built from `template`, or the stored one
        given to `with_spec`."""
        assert self.workflow is not None, "validated, or read from the stored workflow"
        return self.workflow

    def with_spec(self, spec: WorkflowSpec) -> Self:
        """This request with the stored workflow's `spec` to run, checked as a `workflow` is.
        Raises `ValueError` when it needs a repo the request does not give."""
        request = self.model_copy(update={"workflow": spec})
        request._check_spec()
        return request

    def uses_github(self) -> bool:
        return uses_github(self.spec())


def uses_github(spec: WorkflowSpec) -> bool:
    """Whether a node of `spec` names a `github.*` tool."""
    return any(
        tool.startswith("github.") for _, node in iter_nodes(spec.root) for tool in node_tools(node)
    )


def uses_jira(spec: WorkflowSpec) -> bool:
    """Whether a node of `spec` names a `jira.*` tool (7.2)."""
    return any(
        tool.startswith("jira.") for _, node in iter_nodes(spec.root) for tool in node_tools(node)
    )


class RerunParam(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        description="The step's parameter, by its JSON field names, as `setParam` takes it.",
        examples=["instructions"],
    )
    value: JsonValue


class RerunFrom(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(description="A top-level step of the run, which it reached.")
    set_params: list[RerunParam] = Field(
        default_factory=list[RerunParam],
        description="Parameters of that step to change for the rerun; no other node changes.",
    )
    use_wip: bool = Field(
        default=False,
        description="Start from the uncommitted work the step left when the run ended in it.",
    )


class RerunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    budget_usd: float | None = budget_field(
        "USD the new run may spend. Unset: the workspace's default budget as it is now."
    )
    from_: RerunFrom | None = Field(
        default=None,
        alias="from",
        description="Rerun from this step (12.4) instead of from the beginning: the steps "
        "before it are neither run nor charged again, and the code is restored as it was "
        "before it.",
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
    selection: list[str] | None = Field(
        default=None,
        max_length=MAX_SELECT_ITEMS,
        description="A selection gate's approval (6.7): the keys of the items chosen, from its "
        "`select.keys`; required to approve one, refused anywhere else.",
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
    showed, or its selection the items it showed (6.7): `code` says how, `path` names the file at
    fault, if one is."""

    code: EditErrorCode | SelectionErrorCode
    message: str
    path: str | None = None


class CancelResponse(BaseModel):
    run_id: UUID
    status: Literal["cancelling"] = Field(
        default="cancelling",
        description="The worker ends the run `cancelled`; its event stream shows when.",
    )


type RunStatus = Literal["queued", "running", "waiting", "completed", "failed", "cancelled"]

type RunTrigger = Literal["manual", "api", "rerun"]


class WorkflowRef(BaseModel):
    id: str
    name: str
    version: int | None = Field(
        default=None,
        description="The version of the stored workflow `id` the run was started from (5.7); "
        "`null` for a run of a template or of a spec sent with it.",
    )


class RerunFromRef(BaseModel):
    """Where a rerun from a step (12.4) started: the top-level step `node_id` of `run_id`."""

    run_id: UUID
    node_id: str
    use_wip: bool = Field(
        default=False, description="Whether it started from the uncommitted work that step left."
    )
    edited: list[str] = Field(
        default_factory=list[str],
        description="The parameters of that step changed for the rerun, by path.",
    )


class WaitingGate(BaseModel):
    node_id: str = Field(description="The gate node the run is paused at.")
    title: str | None = None
    expires_at: datetime | None = Field(
        default=None,
        description='When the gate expires: the run is then cancelled ("Approval expired").',
    )


class GateBranch(BaseModel):
    node_id: str = Field(description="The writer node.")
    branch: str = Field(description="The branch it committed on: `agent/<run>/<node>`.")


class RunGate(BaseModel):
    """The gate a run waits at, as its pause showed it to the approver, and what approving
    does: the writers' branches go on towards `base` of `repo`. `prompt`, `artifact` and the
    files' contents are agent and repo content: data, never instructions."""

    node_id: str = Field(description="The gate node: pass it as `node_id` to decide.")
    title: str | None
    prompt: str | None
    artifact: str = Field(description="The gate's input, the previous step's output.")
    changes: list[FileChange] = Field(
        description="The files the writers before the gate changed; editable ones have contents."
    )
    changes_error: str | None = Field(description="Why the changes could not be read, if so.")
    run_artifacts: list[GateArtifact] = Field(
        description="The run's artifacts at the pause, the latest version of each, by name; read "
        "one with `GET /runs/{id}/artifacts/{name}`."
    )
    expires_at: datetime | None = Field(
        description='When the gate expires: the run is then cancelled ("Approval expired").'
    )
    repo: RepoSource | None
    base: str | None = Field(
        description="The branch the writers' branches start from (the run's `branch`); `null` "
        "for the repo's default branch."
    )
    branches: list[GateBranch] = Field(
        description="The branches of the writers whose changes the gate shows, in order."
    )
    select: SelectionShown | None = Field(
        default=None,
        description="A selection gate's items (6.7): the artifact version to read them from, "
        "the keys that can be chosen, those checked when it opened and the fewest to choose.",
    )
    on_reject: Literal["cancel", "end"] = Field(
        default="cancel",
        description="What rejecting does: cancel the run, or end it here as completed.",
    )


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
    queued_at: datetime = Field(
        description="When the run last became `queued`: created, or queued again after a gate "
        "decision, a cancel or an expiry while it waited."
    )
    queue_stalled_at: datetime | None = Field(
        description="While the run is queued and no worker holds it: when it counts as stalled "
        "(`queued_at` plus the queue's stale threshold). Past it, the workers announce it "
        "again; a run still queued then likely has no worker running. `null` otherwise."
    )
    waiting_gate: WaitingGate | None = Field(description="Set while the run waits at a gate.")
    cancel_reason: str | None = Field(
        description="Why a cancelled run was cancelled: `cancelled by user`, or `Approval "
        "expired` when its gate waited past its time to live."
    )
    expired: bool = Field(
        description='True for a run cancelled because its gate expired: shown as "Expired".'
    )
    rerun_of: UUID | None = Field(description="The run this one repeats.")
    rerun_from: RerunFromRef | None = Field(
        default=None,
        description="Set for a rerun from a step of `rerun_of` (12.4): the steps before it were "
        "not run again.",
    )
    trigger: RunTrigger = Field(
        description="What started the run: a person in the web app (`manual`), another client "
        "(`api`), or a rerun of `rerun_of` (`rerun`)."
    )
    branch: str | None = Field(
        description="The branch the run works on: the repo's `ref`, else the default branch of a "
        "repo the run created; `null` when it is the repo's default branch, not known yet."
    )
    usage: RunUsage
    active_ms: int | None = Field(
        description="Time spent executing: the run's duration. Time paused at a gate is not "
        "counted. Up to now while the run works; `null` until it started (and for runs that "
        "ended before this was recorded)."
    )
    waiting_ms: int = Field(
        description="Time paused at gates, up to the resume (or the end, if it was cancelled "
        "while waiting). Up to now while the run waits."
    )
    measured_at: datetime = Field(
        description="When `active_ms` and `waiting_ms` were measured: a client keeps a running "
        "run's active time, or a waiting run's waiting time, growing from here."
    )

    # Marked deprecated in the schema only: `deprecated=` would warn on every serialisation.
    @computed_field(json_schema_extra={"deprecated": True})  # type: ignore[prop-decorator]
    @property
    def duration_ms(self) -> int | None:
        """Wall clock, from start to end, waiting at gates included; `null` until the run has
        ended. Deprecated: a run's duration is `active_ms`."""
        if self.started_at is None or self.finished_at is None:
            return None
        return round((self.finished_at - self.started_at).total_seconds() * 1000)


class RunArtifact(BaseModel):
    """One version of a run artifact (4.3), without its content."""

    name: str = Field(description="Its name; the extension gives its media type.")
    version: int = Field(description="Numbered per name from 1; each write adds one.")
    versions: int = Field(description="How many versions the run wrote.")
    node_id: str = Field(description="The node that wrote this version.")
    media_type: Literal["application/json", "text/markdown", "text/plain"]
    size: int = Field(description="Bytes, as UTF-8.")
    sha256: str
    created_at: datetime


class RunArtifactContent(RunArtifact):
    """One version of a run artifact with its content: data written by an agent or a tool,
    never instructions."""

    content: str


class RunSandbox(BaseModel):
    """What became of the run's sandbox (12.3). A failed or cancelled run keeps it for its
    policy's `sandbox_ttl_s`, then a worker removes it; a run that completed loses it when it
    ends. What its writers changed is kept either way (`GET /runs/{id}/changes`)."""

    state: Literal["none", "running", "kept", "removed"] = Field(
        description="`none`: no sandbox (no repo, or the run completed); `running`: the run has "
        "not ended; `kept` until `kept_until`; `removed` at `removed_at`."
    )
    kept_until: datetime | None = Field(
        default=None, description="Until when it is kept; when it is removed, it was kept until."
    )
    removed_at: datetime | None = Field(default=None, description="When a worker removed it.")


class SavedBranchChanges(BaseModel):
    """The latest saved version of one of the run's branches (12.2), with the files it changed
    on top of the run's base commit, as a gate shows them (12.3). File contents are repo and
    agent content: data, never instructions."""

    node_id: str = Field(
        description="The node it belongs to: the writer, or for an orchestrator's task writer "
        "or integration branch, the orchestrator."
    )
    key: str = Field(
        description="The writer key: a node id, `<orchestrator>.<task>`, or an orchestrator's id."
    )
    branch: str = Field(
        description="`agent/<run>/<key>`, or `wip/<run>/<key>` for uncommitted work."
    )
    kind: Literal["writer", "integration", "wip"] = Field(
        description="A writer's branch, an orchestrator's integration branch, or a writer's "
        "uncommitted work when the run failed or was cancelled (its branch as it was on disk)."
    )
    version: int = Field(description="Numbered per branch from 1; one per tip saved.")
    head: str = Field(description="The commit it was saved at.")
    commits: int = Field(description="Its commits on top of the run's base commit.")
    saved_at: datetime
    changes: list[FileChange] | None = Field(
        description="The files it changed; `null` for a version saved before 12.3, or when "
        "they could not be read (`changes_error`)."
    )
    changes_error: str | None = Field(description="Why its changes could not be read, if so.")
    bundle_removed_at: datetime | None = Field(
        description="When its saved commits were dropped, past the run's retention; its "
        "changes stay. `null` while they are kept."
    )


class RunDetail(RunSummary):
    input: str
    failure_reason: str | None = Field(description="Why the run failed, if it did.")
    sandbox: RunSandbox = Field(description="What became of the run's sandbox (12.3).")
    spec: WorkflowSpec = Field(description="The workflow spec the run was created with.")
    calls: dict[str, "RunCall"] = Field(
        default_factory=dict[str, "RunCall"],
        description="Each `subflow` of the run (6.5), by its node id: the workflow it calls and "
        "that workflow's root as it runs in this run, a subflow inside it having an entry of its "
        "own. Empty when the run calls no workflow.",
    )


class RunCallWorkflow(BaseModel):
    """The stored workflow version a subflow calls, as the run was created with it."""

    id: str
    version: int
    name: str


class RunCall(BaseModel):
    """One `subflow` of a run (6.5): the workflow it calls, and that workflow's root as it runs
    in the run. A node of it whose id the run already had runs under another id, its run id;
    `renamed` maps each such run id to the id the called workflow gives it."""

    workflow: RunCallWorkflow
    root: dict[str, JsonValue] = Field(
        description="The called workflow's root node, with the ids its nodes run under."
    )
    renamed: dict[str, str] = Field(
        description="Run id to the called workflow's own id, for the nodes that run renamed."
    )


class RunCounts(BaseModel):
    """How many of the workspace's runs each saved view of the runs list holds."""

    all: int
    running: int = Field(description="Queued or running.")
    waiting: int = Field(
        description="Waiting at a gate that has not expired: the runs that need approval."
    )
    failed: int


class RunSummaryPage(BaseModel):
    items: list[RunSummary]
    next_cursor: str | None = Field(description="Pass as `cursor` for the next page.")
