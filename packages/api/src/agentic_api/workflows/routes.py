from fastapi import APIRouter, HTTPException, Request, status

from agentic_api.workflows.models import ValidateWorkflowRequest, ValidateWorkflowResponse
from agentic_api.workspaces.models import RunLimits, to_usd
from agentic_engine.spec import ValidationIssue
from agentic_store import DEFAULT_WORKSPACE_ID, WorkspaceNotFoundError, check_workflow

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post(
    "/{workflow_id}/validate",
    operation_id="validateWorkflow",
    responses={
        404: {"description": "No workspace with this id"},
        422: {"description": "The request itself is malformed (e.g. `workflow` is not an object)"},
    },
)
async def validate(
    workflow_id: str, body: ValidateWorkflowRequest, request: Request
) -> ValidateWorkflowResponse:
    """Check whether `workflow` could run in the workspace now, without running it: the schema,
    node ids, loop and map rules, references between nodes (`reduce.from`, a publisher's
    `from_node`), a gate before every publisher, tool names, and the workspace's run limits and,
    with a budget, prices. An invalid workflow is answered `200` with `valid: false` and every
    issue. `workflow_id` must be the spec's `id` (`id_mismatch` otherwise). Nothing is stored,
    and no connection is needed."""
    workspace_id = body.workspace_id or DEFAULT_WORKSPACE_ID
    try:
        policy, issues = await check_workflow(
            request.app.state.sessions, workspace_id, body.workflow, to_usd(body.budget_usd)
        )
    except WorkspaceNotFoundError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"workspace {workspace_id} not found"
        ) from None
    spec_id = body.workflow.get("id")
    if isinstance(spec_id, str) and spec_id != workflow_id:
        mismatch = ValidationIssue(
            code="id_mismatch",
            path="id",
            message=f"the workflow's id is {spec_id!r}, not {workflow_id!r} as in the URL; "
            "make them the same",
        )
        issues = [mismatch, *issues]
    return ValidateWorkflowResponse(valid=not issues, issues=issues, policy=RunLimits.of(policy))
