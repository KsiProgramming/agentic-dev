import io
import logging
from collections.abc import Iterator

import pytest
from pydantic import SecretStr

from agentic_secrets import REDACTED, install_redaction, redact, redact_json, registered

SECRET = SecretStr("sk-ant-canary-5f0c9e")


@pytest.fixture
def stream() -> Iterator[io.StringIO]:
    """A redacting handler on a child logger's parent, as the API and worker set it up."""
    out = io.StringIO()
    parent = logging.getLogger("redact-test")
    handler = logging.StreamHandler(out)
    handler.setFormatter(logging.Formatter("%(message)s"))
    parent.addHandler(handler)
    parent.setLevel(logging.DEBUG)
    parent.propagate = False
    install_redaction(parent)
    yield out
    parent.removeHandler(handler)


def test_redact_replaces_live_secrets_only_while_registered() -> None:
    text = f"key={SECRET.get_secret_value()}"
    with registered(SECRET):
        assert redact(text) == f"key={REDACTED}"
    assert redact(text) == text


def test_nested_registrations_are_counted() -> None:
    text = SECRET.get_secret_value()
    with registered(SECRET):
        with registered(SECRET):
            pass
        assert redact(text) == REDACTED
    assert redact(text) == text


def test_short_values_are_not_registered() -> None:
    with registered(SECRET.__class__("abc")):
        assert redact("abc") == "abc"


def test_redact_json_covers_nested_strings_and_keys() -> None:
    value = SECRET.get_secret_value()
    with registered(SECRET):
        out = redact_json({"a": [value, 1, {value: f"x{value}"}], "b": None})
    assert out == {"a": [REDACTED, 1, {REDACTED: f"x{REDACTED}"}], "b": None}


def test_redacting_filter(stream: io.StringIO) -> None:
    log = logging.getLogger("redact-test.child")
    value = SECRET.get_secret_value()
    with registered(SECRET):
        log.info("message %s", value)
        try:
            raise RuntimeError(f"provider said: bad key {value}")
        except RuntimeError:
            log.exception("call failed")
        log.debug("stack", stack_info=True, extra={"unused": value})
    log.info("after %s", value)

    lines = stream.getvalue()
    before, after = lines.split("after ")
    assert value not in before
    assert f"message {REDACTED}" in before
    assert f"bad key {REDACTED}" in before
    # Once unregistered, values are no longer touched.
    assert value in after
