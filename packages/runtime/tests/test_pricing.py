from decimal import Decimal

import pytest
from pydantic import ValidationError

from agentic_runtime.pricing import DEFAULT_PRICES, CallTokens, ModelPrice


def price(**overrides: str) -> ModelPrice:
    fields = {"input": "1", "output": "2", "cache_write_5m": "3", "cache_write_1h": "4"}
    return ModelPrice.model_validate({**fields, "cache_read": "0.5", **overrides})


def test_input_and_output_at_list_price() -> None:
    usd = DEFAULT_PRICES.estimate_usd(
        "claude-opus-5-5", CallTokens(input=1_000_000, output=100_000)
    )
    assert usd == Decimal("6")  # $4 + 0.1 x $20


def test_cache_tokens_are_priced_apart() -> None:
    tokens = CallTokens(
        input=1000, output=0, cache_read=1_000_000, cache_write_5m=1_000_000, cache_write_1h=0
    )
    # Sonnet 5.5: $2/MTok input, $0.10 cache read, $2.50 5m cache write.
    assert DEFAULT_PRICES.estimate_usd("claude-sonnet-5-5", tokens) == Decimal("2.602")


def test_one_hour_cache_writes_cost_more() -> None:
    five = DEFAULT_PRICES.estimate_usd("claude-opus-5-5", CallTokens(0, 0, cache_write_5m=10**6))
    hour = DEFAULT_PRICES.estimate_usd("claude-opus-5-5", CallTokens(0, 0, cache_write_1h=10**6))
    assert (five, hour) == (Decimal("5"), Decimal("8"))


def test_long_prompts_switch_to_long_context_prices() -> None:
    short = CallTokens(input=100_000, output=0)
    long = CallTokens(input=90_000, output=0, cache_read=10_001)
    assert DEFAULT_PRICES.estimate_usd("claude-haiku-5-5", short) == Decimal("0.01")
    # Over 100K prompt tokens: $0.50 input and $0.05 cache read.
    assert DEFAULT_PRICES.estimate_usd("claude-haiku-5-5", long) == Decimal("0.04550005")


@pytest.mark.parametrize("model", [None, "", "claude-test"])
def test_unknown_model_has_no_price(model: str | None) -> None:
    assert DEFAULT_PRICES.estimate_usd(model, CallTokens(input=10, output=10)) is None


def test_overrides_replace_a_default_and_add_a_model() -> None:
    table = DEFAULT_PRICES.with_overrides({"claude-haiku-5-5": price(), "my-proxy-model": price()})
    tokens = CallTokens(input=200_000, output=0)

    # The override is flat: no long context tier any more.
    assert table.estimate_usd("claude-haiku-5-5", tokens) == Decimal("0.2")
    assert table.estimate_usd("my-proxy-model", tokens) == Decimal("0.2")
    assert DEFAULT_PRICES.estimate_usd("my-proxy-model", tokens) is None  # unchanged


def test_many_small_calls_add_up_without_drift() -> None:
    one = DEFAULT_PRICES.estimate_usd("claude-haiku-5-5", CallTokens(input=7, output=3))
    assert one is not None
    assert sum([one] * 1000, Decimal(0)) == Decimal("0.0022")


def test_prices_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        price(output="-1")
