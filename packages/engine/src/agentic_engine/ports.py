"""Typed ports (4.2): the JSON Schemas an agent or tool node may declare for its input and its
output, and how a value is checked against them at each edge.

A schema is JSON Schema 2020-12 whose root is an object, with only local `$ref`s (`#/...`), so
checking a value never reaches the network. A node's output is checked once it completes, and its
input before it starts; a value that does not match fails the node with one readable line and the
JSON pointers of what is wrong (`PortFailure`).
"""

import json
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from functools import lru_cache
from typing import Literal, cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError, relevance
from pydantic import BaseModel, ConfigDict, JsonValue
from referencing import Registry

MAX_SCHEMA_BYTES = 16 * 1024
"""The largest schema a port takes, as compact JSON."""

MAX_PORT_ERRORS = 10
"""How many errors a `PortFailure` keeps; the first is the most relevant."""

MAX_ERROR_TEXT = 500
"""The longest one-line error a port failure gives its node."""

_MAX_MESSAGE = 200
_DIALECT = "https://json-schema.org/draft/2020-12/schema"
_FENCED = re.compile(r"```[a-zA-Z]*[ \t]*\r?\n(.*?)```", re.DOTALL)

type PortSide = Literal["input", "output"]


class PortError(BaseModel):
    """One way a value does not match a schema: where (`pointer`, a JSON pointer, empty for the
    value itself) and what (`message`)."""

    model_config = ConfigDict(frozen=True)

    pointer: str
    message: str


class PortFailure(BaseModel):
    """Why a value did not pass a node's port: its `side`, the node, the node the value came from
    (input side, when it is the previous step), the errors and the one-line `error`."""

    model_config = ConfigDict(frozen=True)

    side: PortSide
    node_id: str
    from_node_id: str | None
    errors: list[PortError]
    error: str

    def payload(self) -> dict[str, JsonValue]:
        """The `port` of the node's `node_failed` event."""
        return {
            "side": self.side,
            "node_id": self.node_id,
            "from_node_id": self.from_node_id,
            "errors": [{"pointer": e.pointer, "message": e.message} for e in self.errors],
        }


def schema_problem(schema: Mapping[str, JsonValue]) -> str | None:
    """Why `schema` cannot be a port's schema; `None` if it can."""
    text = json.dumps(schema, separators=(",", ":"), sort_keys=True)
    if len(text) > MAX_SCHEMA_BYTES:
        return f"it is larger than {MAX_SCHEMA_BYTES // 1024} KB"
    return _schema_problem(text)


@lru_cache(maxsize=256)
def _schema_problem(text: str) -> str | None:
    """`schema_problem` for a schema as JSON text. Checking a schema against the meta-schema is
    slow, and the same schema (the findings report's) is on many nodes, so the answer is kept."""
    schema = cast(dict[str, JsonValue], json.loads(text))
    dialect = schema.get("$schema")
    if dialect is not None and dialect != _DIALECT:
        return f"only JSON Schema 2020-12 is supported (`$schema` {_DIALECT!r})"
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as e:
        where = _pointer(e.absolute_path) or "the top level"
        return f"it is not a valid JSON Schema at {where}: {_short(e.message)}"
    if schema.get("type") != "object":
        return 'its root must be `"type": "object"`'
    if ref := next((r for r in _refs(schema) if not r.startswith("#")), None):
        return f"`$ref` {ref!r} is not local; only `#/...` references are allowed"
    return None


def check_value(schema: Mapping[str, JsonValue], value: JsonValue) -> list[PortError]:
    """How `value` does not match `schema`, the most relevant first (as `jsonschema`'s
    `best_match` ranks them), at most `MAX_PORT_ERRORS`; empty if it matches. `schema` must have
    passed `schema_problem`."""
    validator = Draft202012Validator(schema, registry=Registry())
    # The stubs leave `iter_errors` untyped; it yields `ValidationError`s.
    iter_errors = cast(
        Callable[[object], Iterator[ValidationError]],
        validator.iter_errors,  # pyright: ignore[reportUnknownMemberType]
    )
    errors = sorted(iter_errors(value), key=relevance, reverse=True)
    return [_port_error(e) for e in errors[:MAX_PORT_ERRORS]]


def parse_value(text: str) -> JsonValue:
    """`text` as JSON, or the one fenced code block it holds as JSON (agents often fence their
    answer). Raises `json.JSONDecodeError` for the text itself when neither parses."""
    try:
        return cast(JsonValue, json.loads(text))
    except json.JSONDecodeError as e:
        blocks: list[str] = _FENCED.findall(text)
        if len(blocks) == 1:
            try:
                return cast(JsonValue, json.loads(blocks[0]))
            except json.JSONDecodeError:
                pass
        raise e


def check_port(
    side: PortSide,
    node_id: str,
    schema: Mapping[str, JsonValue],
    value: str | Mapping[str, JsonValue],
    from_node_id: str | None = None,
) -> dict[str, JsonValue] | PortFailure:
    """Check `value` (text to parse, or structured data) against `node_id`'s `side` schema: the
    matching object, or why it does not match."""
    if isinstance(value, str):
        try:
            parsed = parse_value(value)
        except json.JSONDecodeError as e:
            why = f"not JSON: {e.msg}: line {e.lineno} column {e.colno}"
            return _failure(side, node_id, from_node_id, [PortError(pointer="", message=why)])
    else:
        parsed = dict(value)
    if errors := check_value(schema, parsed):
        return _failure(side, node_id, from_node_id, errors)
    return cast(dict[str, JsonValue], parsed)


def _failure(
    side: PortSide, node_id: str, from_node_id: str | None, errors: list[PortError]
) -> PortFailure:
    subject = f"{side} of {node_id!r}"
    if from_node_id is not None:
        subject += f" (from {from_node_id!r})"
    first = errors[0]
    if first.message.startswith("not JSON: "):
        text = f"{subject} is {first.message}"
    else:
        where = first.pointer or "the top level"
        text = f"{subject} does not match its {side}_schema at {where}: {first.message}"
        if len(errors) > 1:
            text += f" (and {len(errors) - 1} more)"
    if len(text) > MAX_ERROR_TEXT:
        text = text[: MAX_ERROR_TEXT - 1] + "…"
    return PortFailure(
        side=side, node_id=node_id, from_node_id=from_node_id, errors=errors, error=text
    )


def _port_error(error: ValidationError) -> PortError:
    return PortError(pointer=_pointer(error.absolute_path), message=_short(error.message))


def _pointer(path: Iterable[str | int]) -> str:
    """A JSON pointer (`/findings/0/severity`); empty for the value itself."""
    return "".join(f"/{str(part).replace('~', '~0').replace('/', '~1')}" for part in path)


def _short(message: str) -> str:
    return message if len(message) <= _MAX_MESSAGE else message[: _MAX_MESSAGE - 1] + "…"


def _refs(value: object) -> Iterator[str]:
    """Every `$ref` string in a schema, depth first."""
    if isinstance(value, Mapping):
        for key, inner in cast(Mapping[str, object], value).items():
            if key == "$ref" and isinstance(inner, str):
                yield inner
            else:
                yield from _refs(inner)
    elif isinstance(value, Sequence) and not isinstance(value, str):
        for inner in cast(Sequence[object], value):
            yield from _refs(inner)
