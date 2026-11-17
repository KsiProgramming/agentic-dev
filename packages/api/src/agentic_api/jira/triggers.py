"""Jira trigger rules (7.3): when an issue of a picked project moves to a status or gets a label,
a run starts with the issue key as its input.

A rule is checked when it is saved with the checks `POST /runs` makes (`prepare_run`), so a rule
that could not start a run is refused then, not when an issue moves. Every change to rules
brings the workspace's webhooks on Jira in step (`agentic_jira.sync_jira_webhooks`); a failure
there is stored and shown on the connection (`GET /workspaces/{id}/jira`), never raised."""

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import SecretStr, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api.jira.models import CloudId, JiraErrorDetail
from agentic_api.jira.routes import from_jira, jira_app, known_site, master_keys
from agentic_api.jira.sync import sync_webhooks
from agentic_api.jira.trigger_models import (
    JiraStatusList,
    JiraTriggerIn,
    JiraTriggerList,
    JiraTriggerOut,
    JiraTriggerPatch,
    ProjectKey,
)
from agentic_api.runs.models import CreateRunRequest, StoredWorkflowRun, TemplateRun
from agentic_api.runs.routes import prepare_run
from agentic_jira import JiraNotFoundError, JiraPlatform
from agentic_sandbox import RepoSource
from agentic_secrets import KeyProvider
from agentic_store import (
    JiraTriggerFields,
    JiraTriggerNotFoundError,
    create_jira_trigger,
    delete_jira_trigger,
    get_jira_trigger,
    get_workspace,
    jira_project_allowed,
    list_jira_triggers,
    update_jira_trigger,
)

router = APIRouter(tags=["jira"])

_RULE_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"description": "No such workspace, or no such rule in it"},
    422: {
        "description": "The rule cannot start a run: `project_not_allowed` (the project is not "
        "picked on an enabled site of a working Jira connection), `cannot_run` (the checks "
        "`POST /runs` makes refuse it), or `no_input` (its workflow declares no required "
        "input to receive the issue key).",
        "model": JiraErrorDetail,
    },
}


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.sessions


async def _workspace(request: Request, workspace_id: UUID) -> None:
    if await get_workspace(_sessions(request), workspace_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"workspace {workspace_id} not found")


def _refused(code: str, message: str) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        JiraErrorDetail(code=code, message=message).model_dump(),
    )


def run_request(workspace_id: UUID, rule: JiraTriggerFields, issue_key: str) -> CreateRunRequest:
    """The `POST /runs` request a rule makes for an issue. `ValidationError` when the rule's
    workflow cannot run with it (an unknown template, a repo it needs and lacks)."""
    return CreateRunRequest(
        template=TemplateRun(id=rule.template_id) if rule.template_id else None,
        stored_workflow=(
            StoredWorkflowRun(id=rule.workflow_id, version=rule.workflow_version)
            if rule.workflow_id
            else None
        ),
        input=issue_key,
        repo=RepoSource(url=rule.repo_url, ref=rule.ref) if rule.repo_url else None,
        workspace_id=workspace_id,
        trigger="api",
    )


def refusal(exc: HTTPException | ValidationError) -> str:
    """What a refused run request says, for people."""
    if isinstance(exc, ValidationError):
        return "; ".join(str(err["msg"]).removeprefix("Value error, ") for err in exc.errors())
    detail: object = exc.detail
    if isinstance(detail, dict):
        message = cast(dict[str, object], detail).get("message")
        return str(message) if message else str(cast(object, detail))
    return str(detail)


async def _check(request: Request, workspace_id: UUID, rule: JiraTriggerFields) -> None:
    """Refuses a rule that could not start a run."""
    if not await jira_project_allowed(
        _sessions(request), workspace_id, rule.cloud_id, rule.project_key
    ):
        raise _refused(
            "project_not_allowed",
            f"project {rule.project_key} is not picked on an enabled Jira site of this workspace",
        )
    try:
        prepared = await prepare_run(
            request, run_request(workspace_id, rule, f"{rule.project_key}-1")
        )
    except (HTTPException, ValidationError) as exc:
        raise _refused("cannot_run", f"the workflow cannot run: {refusal(exc)}") from None
    if prepared.spec.input is None or not prepared.spec.input.required:
        raise _refused(
            "no_input",
            "the workflow must declare a required input: the run gets the issue key there",
        )


@router.get(
    "/workspaces/{workspace_id}/jira/triggers",
    operation_id="listJiraTriggers",
    responses={404: {"description": "No workspace with this id"}},
)
async def list_triggers(workspace_id: UUID, request: Request) -> JiraTriggerList:
    """The workspace's rules, oldest first, each with the last thing it did."""
    await _workspace(request, workspace_id)
    rules = await list_jira_triggers(_sessions(request), workspace_id)
    return JiraTriggerList(triggers=[JiraTriggerOut.of(rule) for rule in rules])


@router.post(
    "/workspaces/{workspace_id}/jira/triggers",
    operation_id="createJiraTrigger",
    status_code=status.HTTP_201_CREATED,
    responses=_RULE_ERRORS,
)
async def create_trigger(
    workspace_id: UUID, body: JiraTriggerIn, request: Request
) -> JiraTriggerOut:
    """Add a rule. It is checked as a run of its workflow on the project's first issue would be,
    and the site's webhook is registered (or its projects widened) on Jira."""
    await _workspace(request, workspace_id)
    fields = body.fields()
    await _check(request, workspace_id, fields)
    created = await create_jira_trigger(_sessions(request), workspace_id, fields)
    await sync_webhooks(request, workspace_id)
    return JiraTriggerOut.of(created)


@router.patch(
    "/workspaces/{workspace_id}/jira/triggers/{trigger_id}",
    operation_id="patchJiraTrigger",
    responses=_RULE_ERRORS,
)
async def patch_trigger(
    workspace_id: UUID, trigger_id: UUID, body: JiraTriggerPatch, request: Request
) -> JiraTriggerOut:
    """Change a rule; only the fields given change. Turning it off (`enabled: false`) skips the
    checks, so a rule whose workflow broke can still be paused."""
    await _workspace(request, workspace_id)
    sessions = _sessions(request)
    found = await get_jira_trigger(sessions, workspace_id, trigger_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no rule {trigger_id}")
    try:
        fields = body.applied_to(found.fields).fields()
    except ValidationError as exc:
        raise _refused("cannot_run", refusal(exc)) from None
    if fields.enabled:
        await _check(request, workspace_id, fields)
    try:
        changed = await update_jira_trigger(sessions, workspace_id, trigger_id, fields)
    except JiraTriggerNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no rule {trigger_id}") from None
    await sync_webhooks(request, workspace_id)
    return JiraTriggerOut.of(changed)


@router.delete(
    "/workspaces/{workspace_id}/jira/triggers/{trigger_id}",
    operation_id="deleteJiraTrigger",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={404: {"description": "No such workspace, or no such rule in it"}},
)
async def delete_trigger(workspace_id: UUID, trigger_id: UUID, request: Request) -> None:
    """Remove a rule. The runs it started keep their issue. A webhook no rule needs any more is
    deleted on Jira."""
    await _workspace(request, workspace_id)
    try:
        await delete_jira_trigger(_sessions(request), workspace_id, trigger_id)
    except JiraTriggerNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no rule {trigger_id}") from None
    await sync_webhooks(request, workspace_id)


@router.get(
    "/workspaces/{workspace_id}/jira/sites/{cloud_id}/projects/{project_key}/statuses",
    operation_id="listJiraProjectStatuses",
    responses={
        404: {"description": "No such workspace, site, or project the account can see"},
        409: {"description": "The workspace's Jira connection is missing or needs attention"},
        502: {"description": "Atlassian answered with an error or could not be reached"},
        503: {"description": "No Atlassian OAuth app, or no master key, is configured"},
    },
)
async def project_statuses(
    workspace_id: UUID,
    cloud_id: CloudId,
    project_key: ProjectKey,
    request: Request,
    jira: Annotated[JiraPlatform, Depends(jira_app)],
    keys: Annotated[KeyProvider, Depends(master_keys)],
) -> JiraStatusList:
    """The project's status names, read live from Jira, for a rule's "moves to" field."""
    await known_site(request, workspace_id, cloud_id)

    async def fetch(token: SecretStr) -> list[str] | None:
        try:
            return await jira.project_statuses(token, cloud_id, project_key.upper())
        except JiraNotFoundError:
            return None

    statuses = await from_jira(request, workspace_id, jira, keys, fetch)
    if statuses is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no project {project_key} on this site")
    return JiraStatusList(statuses=statuses)
