"""A deterministic `AgentRuntime` for tests: replays scripted events, with no network or I/O of
its own. Tools it is asked to call run through the `ToolExecutor` it is given."""

import asyncio
import contextlib
import json
import re
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast

from jsonschema import Draft202012Validator
from pydantic import JsonValue

from agentic_runtime.contract import check_events
from agentic_runtime.events import (
    AgentEvent,
    Cancelled,
    Completed,
    Failed,
    Message,
    ReasoningDelta,
    TextDelta,
    ToolCall,
    ToolResult,
    Usage,
    is_terminal,
)
from agentic_runtime.request import AgentRequest
from agentic_runtime.tools import ToolExecutor


@dataclass(frozen=True)
class Delay:
    """A script step that waits; `cancel()` interrupts it."""

    seconds: float


@dataclass(frozen=True)
class CallTool:
    """A script step that calls a tool through the runtime's `ToolExecutor`: it emits
    `tool_call`, runs the tool and emits its `tool_result`."""

    name: str
    arguments: dict[str, JsonValue] = field(default_factory=dict[str, JsonValue])


type Step = AgentEvent | Delay | CallTool
type Script = Sequence[Step]

# Scripted, so it carries its own price: engine tests see costs without a price table.
ECHO_USAGE = Usage(model="fake", input_tokens=10, output_tokens=10, estimated_usd=0.0001)


FAKE_REASONING = ReasoningDelta(
    text="Look at the repository with each tool first.\nThen answer with what I was given."
)
"""What a node without a script reasons before its tool calls."""


def echo_script(text: str) -> list[Step]:
    """The default script: reply with the input."""
    return [Message(text=text), ECHO_USAGE, Completed()]


def slow_echo_script(text: str, step_delay_s: float) -> list[Step]:
    """Reply with the input as if streamed: one `text_delta` per word, then the message, waiting
    `step_delay_s` before each event. Makes a run visibly live without a real provider."""
    steps: list[Step] = []
    for chunk in re.findall(r"\S+\s*", text):
        steps += [Delay(step_delay_s), TextDelta(text=chunk)]
    for event in echo_script(text):
        steps += [Delay(step_delay_s), event]
    return steps


def _prepare(node_id: str, script: Script) -> tuple[Step, ...]:
    """Append `completed` if the script has no terminal event, then check the contract."""
    steps = list(script)
    events = _expected_events(steps)
    if not events or not is_terminal(events[-1]):
        steps.append(Completed())
        events.append(Completed())
    try:
        check_events(events)
    except ValueError as e:
        raise ValueError(f"script for node {node_id!r}: {e}") from e
    return tuple(steps)


def _expected_events(steps: Sequence[Step]) -> list[AgentEvent]:
    """The events `steps` produce, with a placeholder result for each tool call."""
    events: list[AgentEvent] = []
    for i, step in enumerate(steps):
        if isinstance(step, CallTool):
            events += [
                ToolCall(call_id=_call_id(i), name=step.name),
                ToolResult(call_id=_call_id(i), output=""),
            ]
        elif not isinstance(step, Delay):
            events.append(step)
    return events


def _first_example(schema: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    match schema.get("examples"):
        case [dict() as example, *_]:
            return example
        case _:
            return {}


def _call_id(index: int) -> str:
    return f"fake_call_{index}"


_FAKE_STRINGS = ("fake", "fake-1", "fake_1", "a", "0")
"""What a fitted string is: the first of these its `pattern` accepts."""


def schema_instance(schema: Mapping[str, JsonValue]) -> JsonValue:
    """A small value that matches `schema`, for a fake agent asked for structured output: its
    first example, else built from its `const`, `enum`, `type` and bounds (an array has one item,
    or its `minItems`; an object its required properties, or all of them if none is)."""
    match schema:
        case {"examples": [first, *_]}:
            return first
        case {"const": value}:
            return value
        case {"enum": [first, *_]}:
            return first
        case _:
            pass
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "null")
    match kind:
        case "object":
            props = _sub(schema.get("properties"))
            required = schema.get("required")
            names = required if isinstance(required, list) and required else list(props)
            return {n: schema_instance(_sub(props.get(n))) for n in names if isinstance(n, str)}
        case "array":
            low, high = schema.get("minItems"), schema.get("maxItems")
            count = max(low if isinstance(low, int) else 0, 1)
            if isinstance(high, int):
                count = min(count, high)
            return [schema_instance(_sub(schema.get("items"))) for _ in range(count)]
        case "string":
            pattern = schema.get("pattern")
            text = next(
                (c for c in _FAKE_STRINGS if not isinstance(pattern, str) or re.search(pattern, c)),
                "fake",
            )
            low = schema.get("minLength")
            return text.ljust(low, "x") if isinstance(low, int) else text
        case "integer" | "number":
            low = schema.get("minimum")
            return low if isinstance(low, int | float) else 0
        case "boolean":
            return True
        case "null":
            return None
        case _:
            return "fake"


def _sub(schema: JsonValue | None) -> Mapping[str, JsonValue]:
    return schema if isinstance(schema, dict) else {}


def fit_to_schema(text: str, schema: Mapping[str, JsonValue]) -> str:
    """`text` if it is JSON that matches `schema`, else `schema_instance(schema)` as JSON."""
    # The stubs leave `is_valid` partly untyped.
    is_valid = cast(
        Callable[[object], bool],
        Draft202012Validator(dict(schema)).is_valid,  # pyright: ignore[reportUnknownMemberType]
    )
    with contextlib.suppress(ValueError):
        if is_valid(json.loads(text)):
            return text
    return json.dumps(schema_instance(schema))


class FakeRun:
    """Replays one script. Implements `AgentRun`."""

    def __init__(
        self,
        steps: Sequence[Step],
        tools: ToolExecutor | None = None,
        *,
        node_id: str | None = None,
    ) -> None:
        self._steps = steps
        self._tools = tools
        self._node_id = node_id
        self._cancel = asyncio.Event()
        self._started = False

    def cancel(self) -> None:
        self._cancel.set()

    def __aiter__(self) -> AsyncIterator[AgentEvent]:
        if self._started:
            raise RuntimeError("an AgentRun can only be iterated once")
        self._started = True
        return self._stream()

    async def _stream(self) -> AsyncIterator[AgentEvent]:
        for i, step in enumerate(self._steps):
            if self._cancel.is_set():
                yield Cancelled()
                return
            if isinstance(step, Delay):
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._cancel.wait(), step.seconds)
                continue
            if isinstance(step, CallTool):
                if self._tools is None:
                    yield Failed(error=f"tools requested but no tool executor is set: {step.name}")
                    return
                yield ToolCall(call_id=_call_id(i), name=step.name, arguments=step.arguments)
                yield await self._call(_call_id(i), step)
                continue
            yield step
            if is_terminal(step):
                return

    async def _call(self, call_id: str, step: CallTool) -> ToolResult:
        assert self._tools is not None
        try:
            output = await self._tools.call(step.name, dict(step.arguments), node_id=self._node_id)
        except Exception as e:
            return ToolResult(call_id=call_id, output=f"tool failed: {e}", is_error=True)
        return ToolResult(call_id=call_id, output=output.text, is_error=output.is_error)


class FakeRuntime:
    """Scripted per `node_id`; nodes without a script get `default(request.input)`
    (`echo_script` unless given).

    With `tools`, `CallTool` steps run through it, and a node without a script first calls each
    tool its request names, with the first `examples` entry of the tool's input schema (or no
    arguments), after `FAKE_REASONING`, waiting `call_delay_s` before each call. That lets a demo
    exercise real tools with no provider and no script, and be watched while it works.

    Scripts are checked against the contract up front, so a bad script fails at construction.
    A script without a terminal event gets `completed` appended.

    With `fit_schemas` (a stack or a demo with no provider, 6.8), a node without a script whose
    request has an `output_schema` answers its input only if it matches, else a value built from
    the schema (`fit_to_schema`), so an orchestrator's hub plans and a typed reviewer answers.
    """

    def __init__(
        self,
        scripts: Mapping[str, Script] | None = None,
        *,
        default: Callable[[str], Script] = echo_script,
        tools: ToolExecutor | None = None,
        call_delay_s: float = 0,
        fit_schemas: bool = False,
    ) -> None:
        self._scripts = {node_id: _prepare(node_id, s) for node_id, s in (scripts or {}).items()}
        self._default = default
        self._fit = fit_schemas
        self._tools = tools
        self._call_delay = [Delay(call_delay_s)] if call_delay_s > 0 else []
        self.requests: list[AgentRequest] = []

    def start(self, request: AgentRequest) -> FakeRun:
        self.requests.append(request)
        if request.node_id in self._scripts:
            return FakeRun(self._scripts[request.node_id], self._tools, node_id=request.node_id)
        calls: list[Step] = []
        if self._tools is not None:
            examples = {d.name: _first_example(d.input_schema) for d in self._tools.definitions()}
            calls = [
                step
                for name in request.tools
                for step in [*self._call_delay, CallTool(name, examples.get(name, {}))]
            ]
        reasoning: list[Step] = [FAKE_REASONING] if calls else []
        text = request.input
        if self._fit and request.output_schema is not None:
            text = fit_to_schema(text, request.output_schema)
        script = [*reasoning, *calls, *self._default(text)]
        return FakeRun(_prepare(request.node_id, script), self._tools, node_id=request.node_id)
