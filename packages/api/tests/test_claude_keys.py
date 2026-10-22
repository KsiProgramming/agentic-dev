import anthropic
import httpx2
import pytest
from pydantic import SecretStr

from agentic_api.workspaces.claude_keys import AnthropicKeyVerifier, FakeKeyVerifier

_REQUEST = httpx2.Request("GET", "https://api.anthropic.com/v1/models")


class _Models:
    def __init__(self, error: Exception | None) -> None:
        self.error = error
        self.limits: list[int] = []

    async def list(self, *, limit: int) -> object:
        self.limits.append(limit)
        if self.error is not None:
            raise self.error
        return object()


class _Client:
    """Stands in for `anthropic.AsyncAnthropic`: only `models.list` and `close`."""

    def __init__(self, error: Exception | None) -> None:
        self.models = _Models(error)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _status_error(status: int) -> Exception:
    response = httpx2.Response(status, request=_REQUEST)
    return {
        401: anthropic.AuthenticationError,
        403: anthropic.PermissionDeniedError,
        500: anthropic.InternalServerError,
    }[status]("refused", response=response, body=None)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (None, "valid"),
        (_status_error(401), "invalid"),
        (_status_error(403), "invalid"),
        (_status_error(500), "unavailable"),
        (anthropic.APIConnectionError(request=_REQUEST), "unavailable"),
    ],
)
async def test_a_key_is_checked_by_listing_one_model(
    error: Exception | None, expected: str
) -> None:
    client = _Client(error)
    verifier = AnthropicKeyVerifier(make_client=lambda _key: client)  # pyright: ignore[reportArgumentType, reportReturnType]

    assert await verifier.verify(SecretStr("sk-ant-key")) == expected
    assert client.models.limits == [1]
    assert client.closed


async def test_the_fake_check_accepts_test_keys_only() -> None:
    verifier = FakeKeyVerifier()

    assert await verifier.verify(SecretStr("sk-ant-test-123")) == "valid"
    assert await verifier.verify(SecretStr("sk-ant-api03-real")) == "invalid"
