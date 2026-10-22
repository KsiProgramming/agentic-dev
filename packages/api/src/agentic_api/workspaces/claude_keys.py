"""Checking a Claude API key before it is stored, so a bad key fails on the Settings page and not
in the middle of a run. The key is never logged: errors name what went wrong, not the key."""

import logging
from collections.abc import Callable
from typing import Literal, Protocol

import anthropic
from pydantic import SecretStr

log = logging.getLogger(__name__)

FAKE_KEY_PREFIX = "sk-ant-test-"
VERIFY_TIMEOUT_S = 10.0

type KeyCheck = Literal["valid", "invalid", "unavailable"]


class ClaudeKeyVerifier(Protocol):
    async def verify(self, key: SecretStr) -> KeyCheck: ...


def _client(key: SecretStr) -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(
        api_key=key.get_secret_value(), timeout=VERIFY_TIMEOUT_S, max_retries=1
    )


class AnthropicKeyVerifier:
    """Lists one model with the key: the cheapest call that needs a valid key. Tests pass
    `make_client`."""

    def __init__(
        self, make_client: Callable[[SecretStr], anthropic.AsyncAnthropic] = _client
    ) -> None:
        self._make_client = make_client

    async def verify(self, key: SecretStr) -> KeyCheck:
        client = self._make_client(key)
        try:
            await client.models.list(limit=1)
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
            return "invalid"
        except anthropic.APIError as e:
            # The type only: the error's request carries the key in its headers.
            log.warning("could not verify a Claude key: %s", type(e).__name__)
            return "unavailable"
        finally:
            await client.close()
        return "valid"


class FakeKeyVerifier:
    """For dev and e2e tests: keys starting `sk-ant-test-` are valid, others are not."""

    async def verify(self, key: SecretStr) -> KeyCheck:
        return "valid" if key.get_secret_value().startswith(FAKE_KEY_PREFIX) else "invalid"
