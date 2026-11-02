from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api.runs.routes import existing_workspace
from agentic_api.workflows.models import (
    CreateWorkflowRequest,
    OpErrorDetail,
    RestoreWorkflowRequest,
    UpdateWorkflowRequest,
    ValidateWorkflowRequest,
    ValidateWorkflowResponse,
    WorkflowErrorDetail,
    WorkflowsResponse,
    WorkflowSummary,
    WorkflowVersionItem,
    WorkflowVersionResponse,
    WorkflowVersionsResponse,
)
from agentic_api.workspaces.models import RunLimits, to_usd
from agentic_engine.spec import OpError, ValidationIssue, schema_issues
from agentic_store import (
    DEFAULT_WORKSPACE_ID,
    AlreadyLatestError,
    StoredWorkflowVersion,
    VersionConflictError,
    WorkflowExistsError,
    WorkflowNotFoundError,
    WorkspaceNotFoundError,
    check_workflow,
    create_workflow,
    get_workflow_version,
    list_workflow_versions,
    list_workflows,
    restore_workflow,
    update_workflow,
)

router = APIRouter(prefix="/workflows", tags=["workflows"])

Workspace = Annotated[UUID, Depends(existing_workspace)]


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.sessions


@router.post(
    "",
    operation_id="createWorkflow",
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"description": "No workspace with this id"},
        409: {"model": WorkflowErrorDetail, "description": "`workflow_exists`"},
        422: {"model": WorkflowErrorDetail, "description": "`schema`: the spec is not one"},
    },
)
async def create(
    body: CreateWorkflowRequest, request: Request, workspace_id: Workspace
) -> WorkflowVersionResponse:
    """Store a workflow spec as version 1 of the workflow its `id` names, in the workspace. It
    must match the schema; its other issues (structure, run limits) are returned with it. With
    `template`, the spec is the one the template builds from its parameters; with `blank`, a
    sequence with one starter agent."""
    assert body.spec is not None, "validated: built from the template if not given"
    if issues := schema_issues(body.spec):
        detail = WorkflowErrorDetail(
            code="schema", message="the spec does not match the schema", issues=issues
        )
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail.model_dump())
    try:
        stored = await create_workflow(_sessions(request), workspace_id, body.spec)
    except WorkflowExistsError as e:
        detail = WorkflowErrorDetail(
            code="workflow_exists",
            message=f"workflow {e} already exists; change it with PATCH /workflows/{e}",
            workflow_id=str(e),
        )
        raise HTTPException(status.HTTP_409_CONFLICT, detail.model_dump()) from e
    return await _response(request, workspace_id, stored)


@router.get(
    "",
    operation_id="listWorkflows",
    responses={404: {"description": "No workspace with this id"}},
)
async def list_all(request: Request, workspace_id: Workspace) -> WorkflowsResponse:
    """The workspace's workflows, the most recently changed first, with their latest version's
    name and description."""
    stored = await list_workflows(_sessions(request), workspace_id)
    return WorkflowsResponse(items=[WorkflowSummary.model_validate(w.model_dump()) for w in stored])


@router.get(
    "/{workflow_id}",
    operation_id="getWorkflow",
    responses={404: {"description": "No such workspace, workflow or version"}},
)
async def get(
    workflow_id: str,
    request: Request,
    workspace_id: Workspace,
    version: Annotated[int | None, Query(ge=1, description="Default: the latest.")] = None,
) -> WorkflowVersionResponse:
    """One version of a workflow, the latest by default, with why it could not run now."""
    try:
        stored = await get_workflow_version(_sessions(request), workspace_id, workflow_id, version)
    except WorkflowNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _not_found(workflow_id, version)) from e
    return await _response(request, workspace_id, stored)


@router.get(
    "/{workflow_id}/versions",
    operation_id="listWorkflowVersions",
    responses={404: {"description": "No such workspace or workflow"}},
)
async def versions(
    workflow_id: str, request: Request, workspace_id: Workspace
) -> WorkflowVersionsResponse:
    """Every version of a workflow, newest first, without their specs."""
    try:
        rows = await list_workflow_versions(_sessions(request), workspace_id, workflow_id)
    except WorkflowNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _not_found(workflow_id, None)) from e
    return WorkflowVersionsResponse(
        items=[
            WorkflowVersionItem(
                version=row.version,
                base_version=row.base_version,
                created_at=row.created_at,
                op_count=len(row.ops or []),
                restored_from=row.restored_from,
            )
            for row in rows
        ]
    )


@router.patch(
    "/{workflow_id}",
    operation_id="updateWorkflow",
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"description": "No such workspace or workflow"},
        409: {"model": WorkflowErrorDetail, "description": "`version_conflict`"},
        422: {"model": OpErrorDetail, "description": "The ops cannot apply; nothing is stored"},
    },
)
async def update(
    workflow_id: str, body: UpdateWorkflowRequest, request: Request, workspace_id: Workspace
) -> WorkflowVersionResponse:
    """Apply graph operations to version `base_version`, which must be the latest, and store the
    result as the next version. Versions never change. The ops apply all or nothing: one that
    cannot apply, or a result with a node left detached, an empty slot, or off the schema,
    stores nothing. The result's other issues (structure, run limits) are returned with it."""
    try:
        stored = await update_workflow(
            _sessions(request), workspace_id, workflow_id, body.base_version, body.ops
        )
    except WorkflowNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _not_found(workflow_id, None)) from e
    except VersionConflictError as e:
        raise _conflict(body.base_version, e, "apply the ops to the latest version") from e
    except OpError as e:
        detail = OpErrorDetail(
            code=e.code, message=e.message, op_index=e.op_index, node_id=e.node_id
        )
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail.model_dump()) from e
    return await _response(request, workspace_id, stored)


@router.post(
    "/{workflow_id}/restore",
    operation_id="restoreWorkflow",
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"description": "No such workspace, workflow or version"},
        409: {"model": WorkflowErrorDetail, "description": "`version_conflict`"},
        422: {"model": WorkflowErrorDetail, "description": "`already_latest`"},
    },
)
async def restore(
    workflow_id: str, body: RestoreWorkflowRequest, request: Request, workspace_id: Workspace
) -> WorkflowVersionResponse:
    """Store the spec of the older version `version` as the next version, `restored_from` it.
    `base_version` must be the latest, as for `PATCH`; no version changes or goes. Its issues are
    returned with it."""
    try:
        stored = await restore_workflow(
            _sessions(request), workspace_id, workflow_id, body.base_version, body.version
        )
    except WorkflowNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _not_found(workflow_id, body.version)) from e
    except VersionConflictError as e:
        raise _conflict(body.base_version, e, "restore from the latest version") from e
    except AlreadyLatestError as e:
        detail = WorkflowErrorDetail(
            code="already_latest",
            message=f"version {body.version} is the latest; there is nothing to restore",
        )
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail.model_dump()) from e
    return await _response(request, workspace_id, stored)


def _conflict(base_version: int, error: VersionConflictError, then: str) -> HTTPException:
    detail = WorkflowErrorDetail(
        code="version_conflict",
        message=f"version {base_version} is not the latest ({error.latest_version}); {then}",
        latest_version=error.latest_version,
    )
    return HTTPException(status.HTTP_409_CONFLICT, detail.model_dump())


def _not_found(workflow_id: str, version: int | None) -> str:
    if version is None:
        return f"workflow {workflow_id} not found"
    return f"workflow {workflow_id} has no version {version}"


async def _response(
    request: Request, workspace_id: UUID, stored: StoredWorkflowVersion
) -> WorkflowVersionResponse:
    _, issues = await check_workflow(_sessions(request), workspace_id, stored.spec)
    ops: list[JsonValue] | None = stored.ops
    return WorkflowVersionResponse(
        workflow_id=stored.workflow_id,
        version=stored.version,
        base_version=stored.base_version,
        created_at=stored.created_at,
        spec=stored.spec,
        ops=ops,
        restored_from=stored.restored_from,
        valid=not issues,
        issues=issues,
    )


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
            _sessions(request), workspace_id, body.workflow, to_usd(body.budget_usd)
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
