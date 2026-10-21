"""Redaction of live secrets from logs and event payloads.

A process registers each secret it decrypts for as long as it holds it. Anything written to a log
handler with `RedactingFilter`, or passed through `redact`, has those values replaced. This is a
second line of defence: code should not log secrets in the first place."""

import logging
import threading
from collections import Counter
from collections.abc import Generator
from contextlib import contextmanager

from pydantic import JsonValue, SecretStr

REDACTED = "[REDACTED]"
# Shorter values would redact ordinary words; real keys are far longer.
MIN_SECRET_LENGTH = 8

_lock = threading.Lock()
_live: Counter[str] = Counter()


@contextmanager
def registered(secret: SecretStr) -> Generator[None]:
    """Redacts `secret` while the block runs. Nested registrations of one value are counted."""
    value = secret.get_secret_value()
    if len(value) < MIN_SECRET_LENGTH:
        yield
        return
    with _lock:
        _live[value] += 1
    try:
        yield
    finally:
        with _lock:
            _live[value] -= 1
            if _live[value] <= 0:
                del _live[value]


def redact(text: str) -> str:
    with _lock:
        values = sorted(_live, key=len, reverse=True)
    for value in values:
        if value in text:
            text = text.replace(value, REDACTED)
    return text


def redact_json(value: JsonValue) -> JsonValue:
    """`redact` applied to every string (keys included) of a JSON value."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [redact_json(v) for v in value]
    if isinstance(value, dict):
        return {redact(k): redact_json(v) for k, v in value.items()}
    return value


class RedactingFilter(logging.Filter):
    """Redacts live secrets from a record's message, exception and stack text.

    Attach it to handlers, not loggers: a logger's filters skip records from its children."""

    def filter(self, record: logging.LogRecord) -> bool:
        with _lock:
            live = bool(_live)
        if not live:
            return True
        record.msg = redact(record.getMessage())
        record.args = None
        if record.exc_info:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact(record.exc_text)
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        return True


def install_redaction(logger: logging.Logger | None = None) -> None:
    """Adds a `RedactingFilter` to every handler of `logger` (the root logger by default)."""
    target = logger or logging.getLogger()
    for handler in target.handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(RedactingFilter())
