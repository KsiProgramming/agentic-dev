from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from agentic_github import installation_settings_url
from agentic_runtime import ModelPrice
from agentic_store import ConnectionInfo, WorkspaceInfo

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
