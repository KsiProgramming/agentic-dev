from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from agentic_api.workspaces.models import RunLimits, budget_field
from agentic_engine.spec import ValidationIssue


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
        "The budget a run would set. Unset: the workspace's default budget."
    )


class ValidateWorkflowResponse(BaseModel):
    """Whether the workflow could run in the workspace now; `issues` names every problem."""

    valid: bool
    issues: list[ValidationIssue] = Field(
        description="Each problem with its code, path, node and what to change, in run order. "
        "While the spec does not match the schema, only `schema` issues are listed."
    )
    policy: RunLimits = Field(description="The limits the workflow was checked against.")
