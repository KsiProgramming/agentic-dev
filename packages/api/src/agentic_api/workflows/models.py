"""Checking workflow specs before they run, and storing them as versions changed by graph
operations (5.1)."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from agentic_api.runs.models import TemplateRun
from agentic_api.workspaces.models import RunLimits, budget_field
from agentic_engine.spec import MAX_OPS, GraphOp, OpErrorCode, ValidationIssue


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

    @model_validator(mode="after")
    def _one_spec(self) -> Self:
        if (self.spec is None) == (self.template is None):
            raise ValueError("give either `spec` or `template`")
        if self.template is not None:
            self.spec = self.template.build_spec().model_dump(mode="json", exclude_none=True)
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


class WorkflowVersionResponse(BaseModel):
    """One version of a stored workflow, with what keeps it from running now."""

    workflow_id: str
    version: int
    base_version: int | None = Field(description="The version it was made from; unset for 1.")
    created_at: datetime
    spec: dict[str, JsonValue]
    ops: list[JsonValue] | None = Field(
        description="The graph operations that made it from `base_version`; unset for 1."
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
    op_count: int = Field(description="Graph operations that made it; 0 for version 1.")


class WorkflowVersionsResponse(BaseModel):
    """Every version of a workflow, newest first."""

    items: list[WorkflowVersionItem]


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
    not match the schema, with its `issues`)."""

    code: Literal["workflow_exists", "version_conflict", "schema"]
    message: str
    workflow_id: str | None = Field(
        default=None, description="With `workflow_exists`: the workflow that already exists."
    )
    latest_version: int | None = None
    issues: list[ValidationIssue] = Field(default_factory=list[ValidationIssue])
