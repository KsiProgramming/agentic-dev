"""Mapping a picked project's Jira fields to fixed roles (7.4): which field holds its acceptance
criteria and which its story points.

The fields to pick from are read live from Jira (`GET /rest/api/3/field`) and filtered by what
can hold the role. A saved mapping is checked against that list again, so a field id that is
not on the site, belongs to another team-managed project, or cannot hold its role is refused.
The mapping is stored with the picked project and removed with it (`agentic_store`)."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import SecretStr

from agentic_api.jira.models import (
    CloudId,
    JiraErrorDetail,
    JiraFieldList,
    JiraFieldOut,
    JiraProjectFieldsOut,
    PutJiraProjectFields,
)
from agentic_api.jira.routes import (
    workspace_not_found,
    refused,
    sessions_of,
    from_jira,
    jira_app,
    known_site,
    master_keys,
)
from agentic_api.jira.trigger_models import ProjectKey
from agentic_jira import ROLES, FieldRole, JiraField, JiraPlatform
from agentic_secrets import KeyProvider
from agentic_store import (
    JiraMappedField,
    JiraProjectRef,
    WorkspaceNotFoundError,
    get_jira_connection,
    set_jira_project_fields,
)

router = APIRouter(tags=["jira"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"description": "No such workspace, or its Jira connection has no such site"},
    409: {
        "description": "`no_connection`: the workspace has no Jira connection. "
        "`needs_attention`: Atlassian no longer accepts it; connect again.",
        "model": JiraErrorDetail,
    },
    502: {"description": "Atlassian answered with an error or could not be reached"},
    503: {"description": "No Atlassian OAuth app, or no master key, is configured on the API"},
}


async def _picked(
    request: Request, workspace_id: UUID, cloud_id: str, key: str
) -> JiraProjectRef | None:
    """The picked project `key` of the site, if the workspace picked it."""
    try:
        info = await get_jira_connection(sessions_of(request), workspace_id)
    except WorkspaceNotFoundError:
        raise workspace_not_found(workspace_id) from None
    for site in info.sites if info else ():
        if site.cloud_id == cloud_id:
            return next((p for p in site.projects if p.key == key.upper()), None)
    return None


def _not_allowed(key: str) -> HTTPException:
    return refused(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "project_not_allowed",
        f"{key.upper()} is not a project this workspace picked on the site",
    )


async def _site_fields(
    request: Request, workspace_id: UUID, cloud_id: str, jira: JiraPlatform, keys: KeyProvider
) -> list[JiraField]:
    async def fetch(token: SecretStr) -> list[JiraField]:
        return await jira.list_fields(token, cloud_id)

    return await from_jira(request, workspace_id, jira, keys, fetch)


@router.get(
    "/workspaces/{workspace_id}/jira/sites/{cloud_id}/fields",
    operation_id="listJiraFields",
    responses={
        **_ERRORS,
        422: {
            "description": "`project_not_allowed`: `project` is not picked on the site.",
            "model": JiraErrorDetail,
        },
    },
)
async def list_fields(
    workspace_id: UUID,
    cloud_id: CloudId,
    role: FieldRole,
    request: Request,
    jira: Annotated[JiraPlatform, Depends(jira_app)],
    keys: Annotated[KeyProvider, Depends(master_keys)],
    project: Annotated[ProjectKey | None, Query()] = None,
) -> JiraFieldList:
    """The site's fields that can hold `role`, read live from Jira: a custom paragraph or short
    text for acceptance criteria, a custom number for story points. With `project` (a picked
    project's key), that team-managed project's own fields are listed too. Fields named as the
    role usually is come first."""
    await known_site(request, workspace_id, cloud_id)
    project_id: str | None = None
    if project is not None:
        picked = await _picked(request, workspace_id, cloud_id, project)
        if picked is None:
            raise _not_allowed(project)
        project_id = picked.project_id
    fields = [
        f
        for f in await _site_fields(request, workspace_id, cloud_id, jira, keys)
        if f.fits(role) and (f.project_id is None or f.project_id == project_id)
    ]
    fields.sort(key=lambda f: (not f.suggested(role), f.name.lower(), f.id))
    return JiraFieldList(fields=[JiraFieldOut.of(f, role) for f in fields])


@router.get(
    "/workspaces/{workspace_id}/jira/sites/{cloud_id}/projects/{project_key}/fields",
    operation_id="getJiraProjectFields",
    responses={
        404: {"description": "No such workspace, or no such picked project on the site"},
    },
)
async def get_project_fields(
    workspace_id: UUID, cloud_id: CloudId, project_key: ProjectKey, request: Request
) -> JiraProjectFieldsOut:
    """The project's mapped fields, as stored."""
    picked = await _picked(request, workspace_id, cloud_id, project_key)
    if picked is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"no picked project {project_key.upper()} on this site"
        )
    return JiraProjectFieldsOut.of(picked.fields)


@router.put(
    "/workspaces/{workspace_id}/jira/sites/{cloud_id}/projects/{project_key}/fields",
    operation_id="putJiraProjectFields",
    responses={
        **_ERRORS,
        422: {
            "description": "`project_not_allowed`: the project is not picked on the site. "
            "`unknown_field`: a field id is not one of the site's fields the project can use. "
            "`field_type_mismatch`: a field cannot hold its role. Nothing was stored.",
            "model": JiraErrorDetail,
        },
    },
)
async def put_project_fields(
    workspace_id: UUID,
    cloud_id: CloudId,
    project_key: ProjectKey,
    body: PutJiraProjectFields,
    request: Request,
    jira: Annotated[JiraPlatform, Depends(jira_app)],
    keys: Annotated[KeyProvider, Depends(master_keys)],
) -> JiraProjectFieldsOut:
    """Replace the project's mapping. Each field is checked with Jira, and its name is stored
    as Jira gives it."""
    await known_site(request, workspace_id, cloud_id)
    picked = await _picked(request, workspace_id, cloud_id, project_key)
    if picked is None:
        raise _not_allowed(project_key)
    wanted: dict[FieldRole, str] = {
        role: field_id for role in ROLES if (field_id := getattr(body, role)) is not None
    }
    mapped: list[JiraMappedField] = []
    if wanted:
        site_fields = {
            f.id: f
            for f in await _site_fields(request, workspace_id, cloud_id, jira, keys)
            if f.in_project(picked.project_id)
        }
        for role, field_id in wanted.items():
            found = site_fields.get(field_id)
            if found is None:
                raise refused(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "unknown_field",
                    f"{field_id} is not a field {picked.key} can use on this site",
                )
            if not found.fits(role):
                raise refused(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "field_type_mismatch",
                    f"{found.name} ({found.label}) cannot hold {role.replace('_', ' ')}",
                )
            mapped.append(JiraMappedField(role=role, field_id=found.id, field_name=found.name))
    saved = await set_jira_project_fields(
        sessions_of(request), workspace_id, cloud_id, picked.key, mapped
    )
    if saved is None:  # unpicked meanwhile
        raise _not_allowed(project_key)
    return JiraProjectFieldsOut.of(saved.fields)
