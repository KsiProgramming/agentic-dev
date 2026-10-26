from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, SecretStr, field_validator

from agentic_engine.policy import PLATFORM_POLICY, Policy, PolicyOverrides
from agentic_github import installation_settings_url
from agentic_runtime import ModelPrice
from agentic_store import AuditAction, AuditEventRow, ConnectionInfo, WorkspaceInfo

Provider = Literal["claude", "github"]


class WorkspaceOut(BaseModel):
    id: UUID
    name: str
    created_at: datetime

    @classmethod
    def of(cls, info: WorkspaceInfo) -> "WorkspaceOut":
        return cls(id=info.id, name=info.name, created_at=info.created_at)


class ConnectionOut(BaseModel):
    """A stored connection. Its secret is never returned; `key_hint` is its last 4 characters.

    A GitHub connection has no secret: it shows the account the App is installed on instead."""

    id: UUID
    provider: Provider
    key_hint: str | None = None
    account_login: str | None = None
    manage_url: str | None = Field(
        default=None,
        description="GitHub: the installation's settings page, where its owner picks the repos "
        "it reaches. Unset for connections made before the account type was recorded.",
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
            provider="github" if info.provider == "github" else "claude",
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


class RunLimits(BaseModel):
    """The limits a run executes under."""

    agents_alive: int = Field(description="Agents running at once.")
    agents_spawned: int = Field(description="Agents a run may start in all.")
    max_depth: int = Field(description="How deep loops and maps may nest.")
    loop_iterations: int = Field(description="The highest `max_iterations` a loop may have.")
    wall_time_s: int = Field(
        description="Seconds a run may spend executing; time waiting at a gate does not count."
    )
    budget_usd: float | None = Field(
        default=None,
        description="USD a run may spend, a hard stop once reached; unset is no cost cap.",
    )

    @classmethod
    def of(cls, policy: Policy) -> "RunLimits":
        return cls.model_validate(policy.model_dump())


BUDGET_MIN_USD = 0.01
BUDGET_MAX_USD = 1_000_000


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


def _lower_limit(ceiling: int, what: str) -> Any:
    return Field(
        default=None,
        ge=1,
        le=ceiling,
        description=f"{what} At most {ceiling}, the platform's limit; unset keeps it.",
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

    defaults: RunLimits = Field(description="The platform's limits, which are also the ceilings.")
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
