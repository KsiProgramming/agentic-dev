"""Checking workflow specs before they run, and storing them as versions changed by graph
operations (5.1), restored from an older version (5.7)."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from agentic_api.runs.models import TemplateRun
from agentic_api.workspaces.models import RunLimits, budget_field
from agentic_engine.nodes import Provider, blank_spec
from agentic_engine.spec import MAX_OPS, GraphOp, NodeId, OpErrorCode, ValidationIssue


class ValidateWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow: dict[str, JsonValue] = Field(
        description="The workflow spec to check, as `POST /runs` takes it. It is not parsed "
        "first, so a spec that does not match the schema is answered with its issues."
    )
    workspace_id: UUID | None = Field(
        default=None,
        description="The workspace whose run limits and prices apply. Default: the default "
        "workspace.",
    )
    budget_usd: float | None = budget_field(
        "The budget a run would set. Unset: the workflow's own `budget_usd`, else the workspace's "
        "default budget."
    )


class ValidateWorkflowResponse(BaseModel):
    """Whether the workflow could run in the workspace now; `issues` names every problem."""

    valid: bool
    issues: list[ValidationIssue] = Field(
        description="Each problem with its code, path, node and what to change, in run order. "
        "While the spec does not match the schema, only `schema` issues are listed."
    )
    policy: RunLimits = Field(description="The limits the workflow was checked against.")


class BlankWorkflow(BaseModel):
    """A new workflow with one starter agent, for the builder to grow (5.8)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    id: NodeId | None = Field(
        default=None, description="Default: the name as a slug (`release-notes`)."
    )
    description: str | None = Field(default=None, max_length=2000)
    provider: Provider | None = Field(
        default=None,
        description="The provider the starter agent runs on. Unset means the workspace default.",
    )


class CreateWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: dict[str, JsonValue] | None = Field(
        default=None,
        description="The workflow spec, stored as version 1 under its `id`. It must match the "
        "schema; other issues are returned with it.",
    )
    template: TemplateRun | None = Field(
        default=None,
        description="Instead of `spec`: a template (`GET /templates`) whose spec, built from "
        "`parameters` (its defaults when unset), is stored as version 1 (5.2).",
    )
    blank: BlankWorkflow | None = Field(
        default=None,
        description="Instead of `spec`: a new workflow whose root is a sequence with one "
        "starter agent (5.8).",
    )

    @model_validator(mode="after")
    def _one_spec(self) -> Self:
        given = [b for b in (self.spec, self.template, self.blank) if b is not None]
        if len(given) != 1:
            raise ValueError("give one of `spec`, `template` or `blank`")
        if self.template is not None:
            self.spec = self.template.build_spec().model_dump(mode="json", exclude_none=True)
        if self.blank is not None:
            b = self.blank
            spec = blank_spec(b.name, id=b.id, description=b.description, provider=b.provider)
            self.spec = spec.model_dump(mode="json", exclude_defaults=True)
        return self


class UpdateWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_version: int = Field(
        ge=1, description="The version the ops were made against; it must be the latest."
    )
    ops: list[GraphOp] = Field(
        min_length=1,
        max_length=MAX_OPS,
        description="Graph operations, applied in order, all or nothing.",
    )


class RestoreWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_version: int = Field(ge=1, description="The latest version, as the client knows it.")
    version: int = Field(ge=1, description="The older version whose spec becomes the latest.")


class WorkflowVersionResponse(BaseModel):
    """One version of a stored workflow, with what keeps it from running now."""

    workflow_id: str
    version: int
    base_version: int | None = Field(description="The version it was made from; unset for 1.")
    created_at: datetime
    spec: dict[str, JsonValue]
    ops: list[JsonValue] | None = Field(
        description="The graph operations that made it from `base_version`; unset for 1 and "
        "for a restore."
    )
    restored_from: int | None = Field(
        description="The version a restore copied; unset unless a restore made it."
    )
    valid: bool = Field(description="Whether it could run in the workspace now.")
    issues: list[ValidationIssue] = Field(
        description="Why it could not run now, as `POST /workflows/{id}/validate` gives them. "
        "A version is stored with its issues; a run of it is refused until they are fixed."
    )


class WorkflowVersionItem(BaseModel):
    version: int
    base_version: int | None
    created_at: datetime
    op_count: int = Field(
        description="Graph operations that made it; 0 for version 1 and a restore."
    )
    restored_from: int | None = Field(description="The version a restore copied, if one did.")


class WorkflowVersionsResponse(BaseModel):
    """Every version of a workflow, newest first."""

    items: list[WorkflowVersionItem]


class WorkflowSummary(BaseModel):
    workflow_id: str
    name: str = Field(description="The latest version's name.")
    description: str | None = Field(description="The latest version's description.")
    latest_version: int
    created_at: datetime
    updated_at: datetime = Field(description="When the latest version was made.")


class WorkflowsResponse(BaseModel):
    """The workspace's workflows, the most recently changed first (5.8)."""

    items: list[WorkflowSummary]


class OpErrorDetail(BaseModel):
    """The `detail` of a batch of graph operations that cannot apply: the op at `op_index` (unset
    when it is the batch's result: a node left detached, an empty slot, a spec off the schema)
    and the node it is about. Nothing was stored."""

    code: OpErrorCode
    message: str
    op_index: int | None
    node_id: str | None


class WorkflowErrorDetail(BaseModel):
    """The `detail` of a refused create or update: `workflow_exists` (create), `version_conflict`
    (`base_version` is not the latest, which `latest_version` names), `schema` (a spec that does
    not match the schema, with its `issues`), `already_latest` (a restore of the latest
    version)."""

    code: Literal["workflow_exists", "version_conflict", "schema", "already_latest"]
    message: str
    workflow_id: str | None = Field(
        default=None, description="With `workflow_exists`: the workflow that already exists."
    )
    latest_version: int | None = None
    issues: list[ValidationIssue] = Field(default_factory=list[ValidationIssue])
