"""Creating and loading runs."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.policy import PLATFORM_POLICY, Policy
from agentic_engine.providers import ResolvedProviders
from agentic_engine.spec import WorkflowSpec
from agentic_runtime import Provider
from agentic_sandbox import RepoSource
from agentic_store.audit import audit, usd
from agentic_store.jira_triggers import JiraOrigin, add_trigger_run, lock_trigger_issue
from agentic_store.models import DEFAULT_WORKSPACE_ID, Run
from agentic_store.policy import run_policy
from agentic_store.providers import (
    TRIGGERED,
    resolve_for_run,
    run_resolution,
    stored_resolution,
)
from agentic_store.subflows import run_spec


@dataclass(frozen=True)
class RerunFrom:
    """Where a rerun from a step (12.4) starts: the top-level step `node_id` of the run
    `run_id`, with that step's uncommitted work restored if `use_wip`."""

    run_id: UUID
    node_id: str
    use_wip: bool = False


@dataclass(frozen=True)
class StoredRun:
    id: UUID
    status: str
    spec: WorkflowSpec
    input: str
    repo: RepoSource | None = None
    # How many times a worker has claimed the run; above 1 it is being resumed.
    attempt: int = 0
    workspace_id: UUID = DEFAULT_WORKSPACE_ID
    # The limits the run got when it was created.
    policy: Policy = PLATFORM_POLICY
    # USD the run's usage has cost so far, for its budget.
    spent: Decimal = Decimal(0)
    created_at: datetime | None = None
    # The commit its first clone was at (12.2), which its later sandboxes are cloned at.
    base_sha: str | None = None
    # A rerun from a step (12.4) starts there instead of from the beginning.
    rerun_from: RerunFrom | None = None
    # The Jira issue a trigger started the run on (7.3, `{cloud_id, site, key, url}`), and the
    # issue as its agents are told it, once read (7.4).
    jira_issue: dict[str, JsonValue] | None = None
    jira_brief: dict[str, JsonValue] | None = None
    # A follow-up of a pull request review (7.6): the pull request and the comment, references
    # only, and the review as its agents are told it, once read.
    pr_review: dict[str, JsonValue] | None = None
    pr_review_brief: dict[str, JsonValue] | None = None
    # The spec file the run was given (7.7), with its text.
    spec_file: dict[str, JsonValue] | None = None
    # The person's GitHub connection whose Copilot the run uses (8.2), and their login; unset: the
    # run is on Claude.
    copilot_connection_id: UUID | None = None
    copilot_login: str | None = None
    # The provider the run was started on and the providers its agents use (8.3), and each
    # agent's provider and model as they were resolved when the run was created; `resolved` is
    # unset for a run from before 8.3, which resolves again from `provider`.
    provider: Provider = "claude"
    providers: tuple[Provider, ...] = ("claude",)
    resolved: ResolvedProviders | None = None


async def create_run(
    sessions: async_sessionmaker[AsyncSession],
    spec: WorkflowSpec,
    input: str = "",
    repo: RepoSource | None = None,
    workspace_id: UUID = DEFAULT_WORKSPACE_ID,
    template_id: str | None = None,
    template_parameters: dict[str, JsonValue] | None = None,
    budget_usd: Decimal | None = None,
    trigger: str = "api",
    workflow_version: tuple[str, int] | None = None,
    subflows: dict[str, JsonValue] | None = None,
    jira_origin: JiraOrigin | None = None,
    jira_issue: dict[str, JsonValue] | None = None,
    spec_file: dict[str, JsonValue] | None = None,
    copilot_connection: tuple[UUID, str] | None = None,
    provider: Provider | None = None,
) -> UUID:
    """Insert a `queued` run of `workspace_id` holding `spec`, `input` and `repo`, and the
    template `spec` was built from (with its options) or the stored workflow version it was read
    from (`(workflow_id, version)`), if any; returns its id. The workspace must
    exist. `trigger` says who started it (`manual` or `api`). The run gets the workspace's policy
    with `budget_usd` in place of its budget, if given (`run_policy`), which raises
    `PolicyViolationError` if the spec is above it. A spec that calls other workflows is given
    expanded (`agentic_store.subflows.resolve_workflow`) with the copies of what it calls
    (`subflows`), which the run keeps; its stored spec is the one written, without them.

    With `jira_origin` (7.3) the run is a Jira trigger's: its trigger is `jira`, it keeps the rule
    and the issue, and the rule's fire and audit entry are committed with it. It raises
    `TriggerRunActiveError` when the rule already has a run going on the issue. Without one,
    `jira_issue` (`{cloud_id, site, key, url}`, 7.5) is the issue a run started by hand works on,
    which its agents are then told as a triggered run's are. `spec_file` (7.7) is the
    Markdown spec file the run is given (`{source, name, path, ref, size, sha256, text}`).
    `copilot_connection` (8.2) is the person's GitHub connection, `(id, login)`, whose Copilot the
    run uses; the caller has checked it belongs to the workspace.

    The providers of the run's agents are resolved here, once, and stored (8.3): node, then
    `provider` (the run's own choice; with only `copilot_connection` it is Copilot, as in 8.2),
    the workflow's, the workspace's default, Claude. A run a trigger started (`trigger` `jira` or
    `github`, or `jira_origin`) stays on Claude. Raises `ProviderGapError` when a node resolves
    to Copilot and there is no `copilot_connection`."""
    run_id = uuid4()
    async with sessions.begin() as session:
        if jira_origin is not None:
            await lock_trigger_issue(session, jira_origin)
        resolved = await resolve_for_run(
            session,
            workspace_id,
            spec,
            override=provider or ("copilot" if copilot_connection else None),
            triggered=trigger in TRIGGERED or jira_origin is not None,
            has_copilot_connection=copilot_connection is not None,
        )
        policy = await run_policy(session, workspace_id, spec, budget_usd, resolved)
        run = Run(
            id=run_id,
            workspace_id=workspace_id,
            status="queued",
            spec=spec.model_dump(mode="json"),
            policy=policy.model_dump(mode="json"),
            input=input,
            repo=repo.model_dump(mode="json") if repo else None,
            repo_url=repo.url if repo else None,
            template_id=template_id,
            template_parameters=template_parameters,
            workflow_id=workflow_version[0] if workflow_version else None,
            workflow_version=workflow_version[1] if workflow_version else None,
            subflows=subflows or None,
            trigger=trigger,
            branch=repo.ref if repo else None,
            jira_issue=jira_issue,
            spec_file=spec_file,
            copilot_connection_id=copilot_connection[0] if copilot_connection else None,
            copilot_login=copilot_connection[1] if copilot_connection else None,
            **stored_resolution(resolved),
        )
        session.add(run)
        audit(
            session,
            workspace_id,
            "run.created",
            run_id=run_id,
            details={
                "template_id": template_id,
                **(
                    {"workflow_id": workflow_version[0], "workflow_version": workflow_version[1]}
                    if workflow_version
                    else {}
                ),
                "repo_url": repo.url if repo else None,
                "budget_usd": usd(policy.budget_usd),
                **({"copilot_login": copilot_connection[1]} if copilot_connection else {}),
                "providers": [*resolved.providers],
            },
        )
        if jira_origin is not None:
            await session.flush()  # the fire refers to the run; no relationship orders them
            add_trigger_run(session, workspace_id, run, jira_origin)
    return run_id


async def get_run(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> StoredRun | None:
    async with sessions() as session:
        run = await session.get(Run, run_id)
    return None if run is None else stored_run(run)


def stored_run(run: Run) -> StoredRun:
    return StoredRun(
        id=run.id,
        status=run.status,
        spec=run_spec(run.spec, run.subflows),
        input=run.input,
        repo=RepoSource.model_validate(run.repo) if run.repo is not None else None,
        attempt=run.attempt,
        workspace_id=run.workspace_id,
        policy=Policy.model_validate(run.policy),
        spent=run.estimated_usd,
        created_at=run.created_at,
        base_sha=run.base_sha,
        rerun_from=_rerun_from(run),
        jira_issue=run.jira_issue,
        jira_brief=run.jira_brief,
        pr_review=run.pr_review,
        pr_review_brief=run.pr_review_brief,
        spec_file=run.spec_file,
        copilot_connection_id=run.copilot_connection_id,
        copilot_login=run.copilot_login,
        provider=_provider(run.provider),
        providers=tuple(_provider(p) for p in run.providers),
        resolved=run_resolution(run),
    )


def _provider(value: str) -> Provider:
    return "copilot" if value == "copilot" else "claude"


async def set_run_jira_brief(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID, brief: dict[str, JsonValue]
) -> dict[str, JsonValue]:
    """Store the issue brief of a run (7.4), unless one is already stored; the stored one.
    Two attempts that both read the issue keep the first, so every agent is told the same."""
    async with sessions.begin() as session:
        run = await session.get_one(Run, run_id, with_for_update=True)
        if run.jira_brief is None:
            run.jira_brief = brief
        return run.jira_brief


def _rerun_from(run: Run) -> RerunFrom | None:
    if run.rerun_from is None or run.rerun_of is None:
        return None
    return RerunFrom(
        run_id=run.rerun_of,
        node_id=str(run.rerun_from["node_id"]),
        use_wip=run.rerun_from.get("use_wip") is True,
    )
