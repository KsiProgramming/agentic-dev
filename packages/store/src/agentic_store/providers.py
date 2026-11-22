"""Which provider a run uses (8.3): resolved once when the run is created and stored on it, and
the workspace's own provider settings (its default provider, the Copilot model and the price of an
AI credit).

A run keeps what was resolved (`runs.provider_map`), so a resume after the workspace default
changed never moves a half-done run to another provider, as the frozen policy never changes
(3.2). A run a trigger started stays on Claude whatever its nodes ask for (decisions log, 8.1):
it is never refused for that."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.providers import (
    ResolvedProviders,
    provider_gaps,
    resolve_providers,
)
from agentic_engine.spec import ValidationIssue, WorkflowSpec
from agentic_runtime import Provider
from agentic_runtime.pricing import DEFAULT_CREDIT_USD
from agentic_store.audit import audit
from agentic_store.connections import WorkspaceNotFoundError
from agentic_store.models import Run, Workspace

TRIGGERED = frozenset({"jira", "github"})
"""The `runs.trigger` values of runs nobody started by hand: they stay on Claude."""

PROVIDERS: tuple[Provider, ...] = ("claude", "copilot")


class ProviderGapError(Exception):
    """A run cannot use the providers it resolved to; `issues` says why, one per node
    (`provider_gaps`)."""

    def __init__(self, issues: list[ValidationIssue]) -> None:
        super().__init__("; ".join(i.message for i in issues))
        self.issues = issues


@dataclass(frozen=True)
class ProviderSettings:
    """A workspace's provider settings. `default_provider` and `copilot_model` are `None` when
    unset (Claude, and the worker's own model). `copilot_credit_usd` is `None` when the workspace
    keeps GitHub's list price (`DEFAULT_CREDIT_USD`)."""

    default_provider: Provider | None = None
    copilot_model: str | None = None
    copilot_credit_usd: Decimal | None = None

    @property
    def credit_usd(self) -> Decimal:
        """What one AI credit is priced at for this workspace."""
        return self.copilot_credit_usd or DEFAULT_CREDIT_USD


def _settings(workspace: Workspace) -> ProviderSettings:
    stored = workspace.default_provider
    return ProviderSettings(
        default_provider=stored if stored in PROVIDERS else None,  # pyright: ignore[reportArgumentType]
        copilot_model=workspace.copilot_model,
        copilot_credit_usd=workspace.copilot_credit_usd,
    )


async def get_provider_settings(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID
) -> ProviderSettings:
    """The workspace's provider settings. Raises `WorkspaceNotFoundError`."""
    async with sessions() as session:
        workspace = await session.get(Workspace, workspace_id)
        if workspace is None:
            raise WorkspaceNotFoundError(workspace_id)
        return _settings(workspace)


async def put_provider_settings(
    sessions: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    settings: ProviderSettings,
) -> ProviderSettings:
    """Replace the workspace's provider settings, with a `workspace.settings_changed` audit entry
    naming what changed. Raises `WorkspaceNotFoundError`."""
    async with sessions.begin() as session:
        workspace = await session.get(Workspace, workspace_id, with_for_update=True)
        if workspace is None:
            raise WorkspaceNotFoundError(workspace_id)
        before = _settings(workspace)
        workspace.default_provider = settings.default_provider
        workspace.copilot_model = settings.copilot_model
        workspace.copilot_credit_usd = settings.copilot_credit_usd
        after = _settings(workspace)
        changed = [
            field
            for field in ("default_provider", "copilot_model", "copilot_credit_usd")
            if getattr(before, field) != getattr(after, field)
        ]
        if changed:
            audit(
                session,
                workspace_id,
                "workspace.settings_changed",
                details={
                    "changed": [*changed],
                    "default_provider": after.default_provider or "claude",
                    "copilot_model": after.copilot_model,
                    "copilot_credit_usd": str(after.credit_usd),
                },
            )
        return after


async def resolve_for_run(
    session: AsyncSession,
    workspace_id: UUID,
    spec: WorkflowSpec,
    *,
    override: Provider | None,
    triggered: bool,
    has_copilot_connection: bool,
) -> ResolvedProviders:
    """The providers of a new run of `spec` (expanded) in the workspace: its nodes' own, the run's
    `override`, the workflow's, the workspace's current default, Claude. Raises
    `WorkspaceNotFoundError`, and `ProviderGapError` when a node resolves to Copilot and there is
    no connection (`provider_gaps`; a trigger's run resolves to Claude, so it never does)."""
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        raise WorkspaceNotFoundError(workspace_id)
    resolved = resolve_providers(
        spec,
        run_override=override,
        workspace_default=_settings(workspace).default_provider,
        triggered=triggered,
    )
    if gaps := provider_gaps(resolved, has_copilot_connection=has_copilot_connection):
        raise ProviderGapError(gaps)
    return resolved


def stored_resolution(resolved: ResolvedProviders) -> dict[str, object]:
    """The columns of `runs` a resolution fills."""
    return {
        "provider": resolved.default,
        "providers": [*resolved.providers],
        "provider_map": resolved.to_json(),
    }


def run_resolution(run: Run) -> ResolvedProviders | None:
    """The resolution a run stored, or `None` for a run from before 8.3."""
    return ResolvedProviders.from_json(run.provider_map) if run.provider_map is not None else None


async def resolve_for_rerun(
    session: AsyncSession,
    original: Run,
    spec: WorkflowSpec,
    *,
    from_step: bool,
    follow_up: bool,
) -> ResolvedProviders:
    """The providers of a rerun of `original` (`spec` is the new run's, expanded; 8.3). A rerun
    from a step keeps what the original stored, as the steps before it ran on it; a rerun from
    the beginning resolves again, from the workspace's default as it is now and, for a person's
    Copilot run, the choice they made. A follow-up of a review (a webhook starts it) resolves as a
    trigger's run does: on Claude. Raises `ProviderGapError` when a node resolves to Copilot and
    the original's connection is gone."""
    has_connection = original.copilot_connection_id is not None and not follow_up
    stored = run_resolution(original)
    if from_step and not follow_up and stored is not None:
        if gaps := provider_gaps(stored, has_copilot_connection=has_connection):
            raise ProviderGapError(gaps)
        return stored
    asked: Provider | None = "copilot" if original.provider == "copilot" and not follow_up else None
    return await resolve_for_run(
        session,
        original.workspace_id,
        spec,
        override=asked,
        triggered=follow_up,
        has_copilot_connection=has_connection,
    )
