"""Model prices and the USD estimate of a usage record.

Prices are list prices in USD per million tokens. `DEFAULT_PRICES` is checked by hand against
Anthropic's pricing page (https://platform.claude.com/docs/en/about-claude/pricing) on
`PRICES_AS_OF`; a workspace may override any model (`PriceTable.with_overrides`). The adapter
prices each API call when it emits its `usage` event, so a logged cost never changes afterwards.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

PRICES_AS_OF = date(2026, 10, 23)

_MILLION = Decimal(1_000_000)
# Estimates are kept to 1e-8 USD: a Haiku cache read of a few tokens is still non-zero.
_QUANTUM = Decimal("0.00000001")

UsdPerMTok = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=4)]


class ModelPrice(BaseModel):
    """USD per million tokens for each kind of token a call is billed for."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input: UsdPerMTok
    output: UsdPerMTok
    cache_write_5m: UsdPerMTok
    cache_write_1h: UsdPerMTok
    cache_read: UsdPerMTok


@dataclass(frozen=True)
class ModelPricing:
    """A model's prices. Some models charge `long_context` prices for a call whose prompt (input,
    cache reads and cache writes) is over `long_context_above` tokens."""

    base: ModelPrice
    long_context: ModelPrice | None = None
    long_context_above: int | None = None

    def for_prompt(self, prompt_tokens: int) -> ModelPrice:
        if (
            self.long_context is not None
            and self.long_context_above is not None
            and prompt_tokens > self.long_context_above
        ):
            return self.long_context
        return self.base


@dataclass(frozen=True)
class CallTokens:
    """The tokens of one API call, split the way they are billed. `input` is uncached input."""

    input: int
    output: int
    cache_read: int = 0
    cache_write_5m: int = 0
    cache_write_1h: int = 0

    @property
    def prompt(self) -> int:
        return self.input + self.cache_read + self.cache_write_5m + self.cache_write_1h


def _price(
    input: str, output: str, cache_write_5m: str, cache_write_1h: str, cache_read: str
) -> ModelPrice:
    return ModelPrice(
        input=Decimal(input),
        output=Decimal(output),
        cache_write_5m=Decimal(cache_write_5m),
        cache_write_1h=Decimal(cache_write_1h),
        cache_read=Decimal(cache_read),
    )


class PriceTable(Mapping[str, ModelPricing]):
    """Prices by model id. Immutable; `with_overrides` returns a new table."""

    def __init__(self, prices: Mapping[str, ModelPricing]) -> None:
        self._prices = dict(prices)

    def __getitem__(self, model: str) -> ModelPricing:
        return self._prices[model]

    def __iter__(self) -> Iterator[str]:
        return iter(self._prices)

    def __len__(self) -> int:
        return len(self._prices)

    def with_overrides(self, overrides: Mapping[str, ModelPrice]) -> "PriceTable":
        """Replace (or add) a model's prices. An override is one flat price: it replaces long
        context prices too."""
        prices = dict(self._prices)
        prices.update({model: ModelPricing(base=price) for model, price in overrides.items()})
        return PriceTable(prices)

    def estimate_usd(self, model: str | None, tokens: CallTokens) -> Decimal | None:
        """The USD cost of one call, or `None` if the model has no price."""
        pricing = self._prices.get(model) if model else None
        if pricing is None:
            return None
        price = pricing.for_prompt(tokens.prompt)
        total = (
            tokens.input * price.input
            + tokens.output * price.output
            + tokens.cache_read * price.cache_read
            + tokens.cache_write_5m * price.cache_write_5m
            + tokens.cache_write_1h * price.cache_write_1h
        )
        return (total / _MILLION).quantize(_QUANTUM)


_OPUS_4X = _price("5", "25", "6.25", "10", "0.50")
_SONNET_4X = _price("3", "15", "3.75", "6", "0.30")

DEFAULT_PRICES = PriceTable(
    {
        "claude-fable-5-1": ModelPricing(_price("10", "50", "12.50", "20", "0.25")),
        "claude-fable-5": ModelPricing(_price("10", "50", "12.50", "20", "1")),
        "claude-opus-5-5": ModelPricing(_price("4", "20", "5", "8", "0.20")),
        "claude-opus-5": ModelPricing(_OPUS_4X),
        "claude-opus-4-8": ModelPricing(_OPUS_4X),
        "claude-opus-4-7": ModelPricing(_OPUS_4X),
        "claude-opus-4-6": ModelPricing(_OPUS_4X),
        "claude-sonnet-5-5": ModelPricing(_price("2", "10", "2.50", "4", "0.10")),
        "claude-sonnet-5": ModelPricing(_price("2", "10", "2.50", "4", "0.20")),
        "claude-sonnet-4-6": ModelPricing(_SONNET_4X),
        "claude-sonnet-4-5": ModelPricing(_SONNET_4X),
        "claude-haiku-5-5": ModelPricing(
            base=_price("0.10", "0.50", "0.125", "0.20", "0.01"),
            long_context=_price("0.50", "2.50", "0.625", "1", "0.05"),
            long_context_above=100_000,
        ),
        "claude-haiku-4-5": ModelPricing(_price("1", "5", "1.25", "2", "0.10")),
    }
)
