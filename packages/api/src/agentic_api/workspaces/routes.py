from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api.workspaces.claude_keys import ClaudeKeyVerifier
from agentic_api.workspaces.models import (
    AuditEventOut,
    AuditPage,
    ConnectionErrorDetail,
    ConnectionOut,
    LongContextPrice,
    ModelPricingOut,
    NewWorkspace,
    Price,
    PutClaudeConnection,
    PutPricing,
    RunLimitOverrides,
    RunLimits,
    WorkspaceOut,
    WorkspacePolicyOut,
    WorkspacePricing,
)
from agentic_engine.policy import PLATFORM_POLICY, effective_policy
from agentic_runtime import DEFAULT_PRICES, PRICES_AS_OF
from agentic_secrets import KeyProvider
from agentic_store import (
    AuditAction,
    InvalidCursorError,
    WorkspaceNotFoundError,
    create_workspace,
    delete_connection,
    get_policy_overrides,
    get_workspace,
    list_audit_events,
    list_connections,
    list_price_overrides,
    list_workspaces,
    put_connection,
    replace_policy_overrides,
    replace_price_overrides,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

_NOT_FOUND: dict[int | str, dict[str, str]] = {404: {"description": "No workspace with this id"}}


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.sessions


def _keys(request: Request) -> KeyProvider:
    keys: KeyProvider | None = request.app.state.keys
    if keys is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "secrets are not configured: set MASTER_KEY_FILE on the API to store keys",
        )
    return keys


def _key_verifier(request: Request) -> ClaudeKeyVerifier:
    return request.app.state.claude_keys


def _not_found(workspace_id: UUID) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"workspace {workspace_id} not found")


def _refused(status_code: int, code: str, message: str) -> HTTPException:
    detail = ConnectionErrorDetail(code=code, message=message)
    return HTTPException(status_code, detail.model_dump())


@router.get("", operation_id="listWorkspaces")
async def workspaces(request: Request) -> list[WorkspaceOut]:
    return [WorkspaceOut.of(w) for w in await list_workspaces(_sessions(request))]


@router.post("", operation_id="createWorkspace", status_code=status.HTTP_201_CREATED)
async def new_workspace(body: NewWorkspace, request: Request) -> WorkspaceOut:
    """A new workspace, with no connections and the platform's run limits. The e2e tests and
    demos run in their own, so their runs never mix with real ones."""
    return WorkspaceOut.of(await create_workspace(_sessions(request), body.name))


@router.get("/{workspace_id}/connections", operation_id="listConnections", responses=_NOT_FOUND)
async def connections(workspace_id: UUID, request: Request) -> list[ConnectionOut]:
    """The workspace's connections, without their secrets."""
    try:
        found = await list_connections(_sessions(request), workspace_id)
    except WorkspaceNotFoundError:
        raise _not_found(workspace_id) from None
    return [ConnectionOut.of(c) for c in found]


@router.put(
    "/{workspace_id}/connections/claude",
    operation_id="putClaudeConnection",
    responses={
        **_NOT_FOUND,
        422: {
            "description": "`invalid_key`: Anthropic refused the key. (Or the body is invalid.)",
            "model": ConnectionErrorDetail,
        },
        502: {
            "description": "`verify_unavailable`: Anthropic could not be reached to check the "
            "key; nothing was stored",
            "model": ConnectionErrorDetail,
        },
        503: {"description": "No master key is configured"},
    },
)
async def put_claude(
    workspace_id: UUID,
    body: PutClaudeConnection,
    request: Request,
    keys: Annotated[KeyProvider, Depends(_keys)],
    verifier: Annotated[ClaudeKeyVerifier, Depends(_key_verifier)],
) -> ConnectionOut:
    """Check the workspace's Claude API key with Anthropic, then store it, encrypted, replacing
    any stored one. The workspace's runs on Claude use it."""
    secret = SecretStr(body.api_key.get_secret_value().strip())
    if await get_workspace(_sessions(request), workspace_id) is None:
        raise _not_found(workspace_id)
    match await verifier.verify(secret):
        case "invalid":
            raise _refused(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "invalid_key",
                "Anthropic did not accept this key. Check that it is complete and active.",
            )
        case "unavailable":
            raise _refused(
                status.HTTP_502_BAD_GATEWAY,
                "verify_unavailable",
                "Anthropic could not be reached to check the key. Try again in a moment.",
            )
        case "valid":
            pass
    try:
        info = await put_connection(_sessions(request), keys, workspace_id, "claude", secret)
    except WorkspaceNotFoundError:
        raise _not_found(workspace_id) from None
    return ConnectionOut.of(info)


@router.delete(
    "/{workspace_id}/connections/claude",
    operation_id="deleteClaudeConnection",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={404: {"description": "No such workspace, or it has no Claude connection"}},
)
async def delete_claude(workspace_id: UUID, request: Request) -> None:
    try:
        deleted = await delete_connection(_sessions(request), workspace_id, "claude")
    except WorkspaceNotFoundError:
        raise _not_found(workspace_id) from None
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "the workspace has no Claude connection")


async def _pricing(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID
) -> WorkspacePricing:
    try:
        overrides = await list_price_overrides(sessions, workspace_id)
    except WorkspaceNotFoundError:
        raise _not_found(workspace_id) from None
    # List-priced models in list order, then the workspace's own models.
    models = [*DEFAULT_PRICES, *sorted(m for m in overrides if m not in DEFAULT_PRICES)]
    out: list[ModelPricingOut] = []
    for model in models:
        pricing = DEFAULT_PRICES.get(model)
        long_context = (
            LongContextPrice(
                above_tokens=pricing.long_context_above, price=Price.of(pricing.long_context)
            )
            if pricing is not None
            and pricing.long_context is not None
            and pricing.long_context_above is not None
            else None
        )
        override = overrides.get(model)
        out.append(
            ModelPricingOut(
                model=model,
                default=Price.of(pricing.base) if pricing is not None else None,
                long_context=long_context,
                override=Price.of(override) if override is not None else None,
            )
        )
    return WorkspacePricing(as_of=PRICES_AS_OF, models=out)


@router.get("/{workspace_id}/pricing", operation_id="getPricing", responses=_NOT_FOUND)
async def get_pricing(workspace_id: UUID, request: Request) -> WorkspacePricing:
    """The model prices the workspace's runs are priced with."""
    return await _pricing(_sessions(request), workspace_id)


@router.put(
    "/{workspace_id}/pricing",
    operation_id="putPricing",
    responses={
        **_NOT_FOUND,
        422: {"description": "A negative price, a bad model id or a model given twice"},
    },
)
async def put_pricing(workspace_id: UUID, body: PutPricing, request: Request) -> WorkspacePricing:
    """Replace the workspace's price overrides. New usage is priced with them; runs already
    logged keep their cost."""
    sessions = _sessions(request)
    overrides = {o.model: o.price.to_model_price() for o in body.overrides}
    try:
        await replace_price_overrides(sessions, workspace_id, overrides)
    except WorkspaceNotFoundError:
        raise _not_found(workspace_id) from None
    return await _pricing(sessions, workspace_id)


async def _policy(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID
) -> WorkspacePolicyOut:
    try:
        overrides = await get_policy_overrides(sessions, workspace_id)
    except WorkspaceNotFoundError:
        raise _not_found(workspace_id) from None
    return WorkspacePolicyOut(
        defaults=RunLimits.of(PLATFORM_POLICY),
        overrides=RunLimitOverrides.of(overrides),
        effective=RunLimits.of(effective_policy(overrides)),
    )


@router.get("/{workspace_id}/policy", operation_id="getPolicy", responses=_NOT_FOUND)
async def get_policy(workspace_id: UUID, request: Request) -> WorkspacePolicyOut:
    """The run limits the workspace's new runs get."""
    return await _policy(_sessions(request), workspace_id)


@router.put(
    "/{workspace_id}/policy",
    operation_id="putPolicy",
    responses={
        **_NOT_FOUND,
        422: {"description": "A limit below 1 or above the platform's, or a budget out of range"},
    },
)
async def put_policy(
    workspace_id: UUID, body: RunLimitOverrides, request: Request
) -> WorkspacePolicyOut:
    """Replace the workspace's own run limits; leave one unset to keep the platform's, and all of
    them to reset. `budget_usd` is the default budget of new runs (unset: no budget), which a run
    may replace. New runs get them; a run keeps the limits it was created with."""
    sessions = _sessions(request)
    try:
        await replace_policy_overrides(sessions, workspace_id, body.to_overrides())
    except WorkspaceNotFoundError:
        raise _not_found(workspace_id) from None
    return await _policy(sessions, workspace_id)


@router.get(
    "/{workspace_id}/audit",
    operation_id="listAuditEvents",
    responses={**_NOT_FOUND, 422: {"description": "Invalid filter, `limit` or `cursor`"}},
)
async def audit_log(
    workspace_id: UUID,
    request: Request,
    action: Annotated[
        list[AuditAction] | None,
        Query(description="Only these actions; may be given several times."),
    ] = None,
    run_id: Annotated[UUID | None, Query(description="Only entries about this run.")] = None,
    since: Annotated[datetime | None, Query(description="Entries at or after this time.")] = None,
    until: Annotated[datetime | None, Query(description="Entries before this time.")] = None,
    cursor: Annotated[str | None, Query(description="`next_cursor` of the previous page.")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AuditPage:
    """The workspace's audit log, newest first, one page at a time: runs started, rerun,
    cancelled and ended, gate decisions, and changes to connections, run limits and prices.
    Filters combine. Entries are never changed or removed."""
    try:
        rows, next_cursor = await list_audit_events(
            _sessions(request),
            workspace_id,
            limit=limit,
            cursor=cursor,
            actions=action or (),
            run_id=run_id,
            since=since,
            until=until,
        )
    except WorkspaceNotFoundError:
        raise _not_found(workspace_id) from None
    except InvalidCursorError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    return AuditPage(items=[AuditEventOut.of(row) for row in rows], next_cursor=next_cursor)
