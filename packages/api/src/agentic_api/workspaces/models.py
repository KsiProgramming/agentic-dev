from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, SecretStr, field_validator

from agentic_engine.policy import (
    BUDGET_MAX_USD,
    BUDGET_MIN_USD,
    CEILINGS,
    PLATFORM_POLICY,
    Policy,
    PolicyOverrides,
    ceiling,
)
from agentic_github import installation_settings_url
from agentic_runtime import ModelPrice
from agentic_runtime import Provider as AgentProvider
from agentic_runtime.pricing import DEFAULT_CREDIT_USD
from agentic_store import AuditAction, AuditEventRow, ConnectionInfo, WorkspaceInfo

Provider = Literal["claude", "github", "jira"]


class NewWorkspace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=128)]


class WorkspaceOut(BaseModel):
    id: UUID
    name: str
    created_at: datetime

    @classmethod
    def of(cls, info: WorkspaceInfo) -> "WorkspaceOut":
        return cls(id=info.id, name=info.name, created_at=info.created_at)


class ConnectionOut(BaseModel):
    """A stored connection. Its secret is never returned; `key_hint` is its last 4 characters.

    A GitHub connection has no secret: it shows the account the App is installed on instead.
    A Jira connection shows the Atlassian account that consented; its sites and projects are
    in `GET /workspaces/{id}/jira`."""

    id: UUID
    provider: Provider
    key_hint: str | None = None
    account_login: str | None = None
    manage_url: str | None = Field(
        default=None,
        description="GitHub: the installation's settings page, where its owner picks the repos "
        "it reaches. Unset for connections made before the account type was recorded.",
    )
    needs_attention: str | None = Field(
        default=None,
        description="Jira: why the connection cannot be used until its account connects again "
        "(`invalid_grant`, `unauthorized`, `scopes`).",
    )
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, info: ConnectionInfo) -> "ConnectionOut":
        manage_url = (
            installation_settings_url(info.installation_id, info.account_login, info.account_type)
            if info.installation_id is not None
            and info.account_login is not None
            and info.account_type is not None
            else None
        )
        return cls(
            id=info.id,
            provider=cast(Provider, info.provider),
            needs_attention=info.needs_attention,
            key_hint=info.key_hint,
            account_login=info.account_login,
            manage_url=manage_url,
            created_at=info.created_at,
            updated_at=info.updated_at,
        )


class PutClaudeConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: SecretStr = Field(
        min_length=8,
        max_length=512,
        description="The Anthropic API key. Stored encrypted; it is never returned.",
        json_schema_extra={"writeOnly": True, "format": "password"},
    )


class ConnectionErrorDetail(BaseModel):
    """The `detail` of a refused connection: `code` says what went wrong (`invalid_key`,
    `verify_unavailable`), `message` says it for people."""

    code: str
    message: str


# Prices are USD per million tokens, stored to 4 decimal places.
UsdPerMTok = Annotated[float, Field(ge=0, le=100_000)]
ModelId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")]


class Price(BaseModel):
    """USD per million tokens."""

    model_config = ConfigDict(extra="forbid")

    input: UsdPerMTok
    output: UsdPerMTok
    cache_write_5m: UsdPerMTok = Field(description="Writing to the 5 minute prompt cache.")
    cache_write_1h: UsdPerMTok = Field(description="Writing to the 1 hour prompt cache.")
    cache_read: UsdPerMTok = Field(description="Reading from the prompt cache.")

    @classmethod
    def of(cls, price: ModelPrice) -> "Price":
        return cls.model_validate({k: float(v) for k, v in price.model_dump().items()})

    def to_model_price(self) -> ModelPrice:
        return ModelPrice.model_validate(
            {k: Decimal(str(v)).quantize(_PRICE_QUANTUM) for k, v in self.model_dump().items()}
        )


_PRICE_QUANTUM = Decimal("0.0001")


class LongContextPrice(BaseModel):
    above_tokens: int = Field(description="Applies to a call whose prompt is over this size.")
    price: Price


class ModelPricingOut(BaseModel):
    model: str
    default: Price | None = Field(description="The list price; unset for a model with none.")
    long_context: LongContextPrice | None = Field(
        description="The list price for long prompts, if the model has one."
    )
    override: Price | None = Field(
        description="The workspace's price. It replaces the list price, long prompts included."
    )


class WorkspacePricing(BaseModel):
    """The prices the workspace's runs are priced with: each model's `override`, else its
    `default`. A run keeps the cost it was priced with when its usage was logged."""

    as_of: date = Field(description="When the list prices were last checked.")
    models: list[ModelPricingOut]


class PriceOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: ModelId
    price: Price


class PutPricing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overrides: list[PriceOverride] = Field(
        max_length=200,
        description="The workspace's overrides, replacing all stored ones; `[]` resets every "
        "model to its list price.",
    )

    @field_validator("overrides")
    @classmethod
    def _one_per_model(cls, overrides: list[PriceOverride]) -> list[PriceOverride]:
        models = [o.model for o in overrides]
        if dupes := sorted({m for m in models if models.count(m) > 1}):
            raise ValueError(f"one override per model: {', '.join(dupes)} given twice")
        return overrides


class ProviderSettings(BaseModel):
    """The workspace's provider settings (8.3): where a run's agents run when nothing narrower
    says, and what Copilot usage costs."""

    default_provider: AgentProvider = Field(
        description="The provider of every agent that names none and whose run and workflow set "
        "none: `claude` unless the workspace chose `copilot`."
    )
    copilot_model: str | None = Field(
        description="The model a Copilot agent with no model of its own runs on; `null`: the "
        "worker's `COPILOT_MODEL` (`auto` lets Copilot choose). Model names are per person, so "
        "none is checked."
    )
    copilot_credit_usd: float = Field(
        description="USD one Copilot AI credit is priced at, for the cost of Copilot usage: the "
        "list-price value of the credits, not what a person's plan charged."
    )
    default_copilot_credit_usd: float = Field(
        description=f"GitHub's price of an AI credit (${DEFAULT_CREDIT_USD}): what "
        "`copilot_credit_usd` is unless the workspace changed it."
    )


class PutProviderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_provider: AgentProvider = "claude"
    copilot_model: ModelId | None = Field(
        default=None, description="Unset: the worker's own model."
    )
    copilot_credit_usd: float | None = Field(
        default=None,
        gt=0,
        le=100,
        description="USD per AI credit, to at most 6 decimals. Unset: GitHub's price.",
    )


class RunLimits(BaseModel):
    """The limits a run executes under."""

    agents_alive: int = Field(description="Agents running at once.")
    agents_spawned: int = Field(description="Agents a run may start in all.")
    max_depth: int = Field(description="How deep loops and maps may nest.")
    loop_iterations: int = Field(description="The highest `max_iterations` a loop may have.")
    wall_time_s: int = Field(
        description="Seconds a run may spend executing; time waiting at a gate does not count."
    )
    approval_ttl_s: int = Field(
        description="Seconds a gate waits for a decision before its run is cancelled "
        '("Approval expired"); a gate may set a shorter time of its own.'
    )
    budget_usd: float | None = Field(
        default=None,
        description="USD a run may spend, a hard stop once reached; unset is no cost cap.",
    )
    sandbox_ttl_s: int = Field(
        description="Seconds a failed or cancelled run's sandbox is kept before it is removed."
    )
    branch_retention_days: int = Field(
        description="Days a finished run's saved commits are kept; the files they changed stay."
    )
    review_rounds: int = Field(
        description="Follow-up runs that review comments (`@<app> fix this`) on one pull "
        "request may start (7.6)."
    )

    @classmethod
    def of(cls, policy: Policy) -> "RunLimits":
        return cls.model_validate(policy.model_dump())

    @classmethod
    def ceilings(cls) -> "RunLimits":
        """The most a workspace may set each limit to: the platform's limit, except where a
        limit's default is below its ceiling (`CEILINGS`)."""
        return cls.model_validate(PLATFORM_POLICY.model_dump() | CEILINGS)


def budget_field(what: str) -> Any:
    return Field(
        default=None,
        ge=BUDGET_MIN_USD,
        le=BUDGET_MAX_USD,
        description=f"{what} From ${BUDGET_MIN_USD} to ${BUDGET_MAX_USD:,}; unset is no budget.",
    )


def to_usd(amount: float | None) -> Decimal | None:
    """An API amount as the policy keeps it, to 8 decimals."""
    return None if amount is None else Decimal(str(round(amount, 8)))


def _lower_limit(most: int, what: str) -> Any:
    return Field(
        default=None,
        ge=1,
        le=most,
        description=f"{what} At most {most}, the platform's limit; unset keeps it.",
    )


def _limit(most: int, what: str) -> Any:
    """A limit a workspace may also raise above the platform's default, up to `most`."""
    return Field(
        default=None,
        ge=1,
        le=most,
        description=f"{what} At most {most}; unset keeps the platform's default.",
    )


class RunLimitOverrides(BaseModel):
    """The workspace's own limits, each at or below the platform's; unset keeps the platform's."""

    model_config = ConfigDict(extra="forbid")

    agents_alive: int | None = _lower_limit(PLATFORM_POLICY.agents_alive, "Agents running at once.")
    agents_spawned: int | None = _lower_limit(
        PLATFORM_POLICY.agents_spawned, "Agents a run may start in all."
    )
    max_depth: int | None = _lower_limit(
        PLATFORM_POLICY.max_depth, "How deep loops and maps may nest."
    )
    loop_iterations: int | None = _lower_limit(
        PLATFORM_POLICY.loop_iterations, "The highest `max_iterations` a loop may have."
    )
    wall_time_s: int | None = _lower_limit(
        PLATFORM_POLICY.wall_time_s, "Seconds a run may spend executing, gates aside."
    )
    approval_ttl_s: int | None = _lower_limit(
        PLATFORM_POLICY.approval_ttl_s, "Seconds a gate waits for a decision before it expires."
    )
    sandbox_ttl_s: int | None = _limit(
        ceiling("sandbox_ttl_s"),
        "Seconds a failed or cancelled run's sandbox is kept before it is removed.",
    )
    branch_retention_days: int | None = _limit(
        ceiling("branch_retention_days"),
        "Days a finished run's saved commits are kept; the files they changed stay.",
    )
    review_rounds: int | None = _limit(
        ceiling("review_rounds"),
        "Follow-up runs that review comments (`@<app> fix this`) on one pull request may start "
        "(7.6).",
    )
    budget_usd: float | None = budget_field(
        "The default budget of the workspace's runs, which a run may replace. It has no "
        "platform ceiling."
    )

    @classmethod
    def of(cls, overrides: PolicyOverrides) -> "RunLimitOverrides":
        return cls.model_validate(overrides.model_dump())

    def to_overrides(self) -> PolicyOverrides:
        return PolicyOverrides.model_validate(
            {**self.model_dump(), "budget_usd": to_usd(self.budget_usd)}
        )


class WorkspacePolicyOut(BaseModel):
    """The limits the workspace's new runs get: each of its `overrides`, else the platform's
    `defaults`. A run keeps the limits it was created with."""

    defaults: RunLimits = Field(description="The platform's limits.")
    ceilings: RunLimits = Field(
        description="The most a workspace may set each limit to: the platform's limit, except "
        "`sandbox_ttl_s`, `branch_retention_days` and `review_rounds`, which may go above "
        "their default."
    )
    overrides: RunLimitOverrides
    effective: RunLimits


class AuditActor(BaseModel):
    """Who acted: `system` is the platform (a run ending); `user` has no `id` until sign-in."""

    type: Literal["user", "system"]
    id: str | None = None


class AuditRunRef(BaseModel):
    """The entry's run as it is now."""

    template_id: str | None
    repo_url: str | None
    status: str


class AuditEventOut(BaseModel):
    """One action in the workspace. `details` depends on `action` (see the audit log contract);
    it never holds file contents or secrets, and USD amounts are decimal strings."""

    id: int
    at: datetime
    action: AuditAction
    actor: AuditActor
    run_id: UUID | None = None
    node_id: str | None = None
    details: dict[str, JsonValue]
    run: AuditRunRef | None = None

    @classmethod
    def of(cls, row: AuditEventRow) -> "AuditEventOut":
        return cls(
            id=row.id,
            at=row.at,
            action=cast(AuditAction, row.action),
            actor=AuditActor(type=cast(Literal["user", "system"], row.actor_type), id=row.actor_id),
            run_id=row.run_id,
            node_id=row.node_id,
            details=row.details,
            run=AuditRunRef.model_validate(row.run, from_attributes=True) if row.run else None,
        )


class AuditPage(BaseModel):
    items: list[AuditEventOut]
    next_cursor: str | None = Field(
        default=None, description="Pass as `cursor` for the next page; unset on the last page."
    )
