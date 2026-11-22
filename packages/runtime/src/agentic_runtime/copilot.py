"""The Copilot adapter: an `AgentRuntime` on the GitHub Copilot SDK, on one person's own token.

The SDK runs its own agent loop; this adapter only hands it the platform's tools and turns what it
reports into `AgentEvent`s. The SDK itself sits behind `CopilotConnector` (`copilot_sdk.py` is the
real one, `copilot_fake.py` the one tests use), so the run logic needs no subscription to test.

What differs from the Claude adapter, and why:

- The SDK calls a tool's handler itself, inside its loop, so `tool_call` and `tool_result` are
  emitted from that handler, in order, through the same queue as the SDK's own events.
- Only the platform's tools are offered (principle 4): the SDK's built-in shell and file tools are
  turned off, and its permission requests are answered here from the node's tool grants: a request
  for anything that is not a granted tool is denied and logged (principle 3). `approve_all` is
  never used.
- The token belongs to the connector. It never reaches a request, an event or a log line: error
  text and tool output are scrubbed of every secret the runtime is given (`secrets`).
- A stream that ends with no `usage` event gets one with zero tokens (the contract needs one);
  Copilot has no price table here, so `estimated_usd` stays `None`.
"""

import asyncio
import contextlib
import logging
import re
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import JsonValue

from agentic_runtime.claude import api_tool_name, system_prompt, user_turn
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
from agentic_runtime.protocol import AgentRun
from agentic_runtime.request import AgentRequest
from agentic_runtime.tools import ToolDefinition, ToolExecutor

log = logging.getLogger(__name__)

DEFAULT_MODEL = "auto"
_TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")
# As for Claude: timeouts, conflicts, rate limits and server errors are worth another attempt.
_RETRYABLE_STATUS = frozenset({408, 409, 429})


# --- What a connector reports and is given: the SDK's shapes, reduced to what the run needs ---


@dataclass(frozen=True)
class TextChunk:
    text: str


@dataclass(frozen=True)
class ReasoningChunk:
    text: str


@dataclass(frozen=True)
class AssistantMessage:
    """The text of one finished assistant message (one model turn)."""

    text: str


@dataclass(frozen=True)
class UsageReport:
    """One model call's usage, as the SDK reported it."""

    model: str | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass(frozen=True)
class SessionIdle:
    """The agent finished its turn (or stopped because it was aborted)."""

    aborted: bool = False


@dataclass(frozen=True)
class SessionError:
    message: str
    status_code: int | None = None


CopilotEvent = (
    TextChunk | ReasoningChunk | AssistantMessage | UsageReport | SessionIdle | SessionError
)


@dataclass(frozen=True)
class PermissionAsk:
    """The SDK asks to do something. `kind` is the SDK's own (`custom-tool`, `shell`, `write`,
    `read`, `mcp`, `url` and so on); `tool_name` is set for a custom tool."""

    kind: str
    tool_name: str | None = None


@dataclass(frozen=True)
class ToolReply:
    text: str
    is_error: bool = False


ToolHandler = Callable[[str, dict[str, JsonValue]], Awaitable[ToolReply]]
"""`(call_id, arguments) -> reply`, bound to one tool."""


@dataclass(frozen=True)
class CopilotTool:
    """A platform tool as the SDK is offered it. `name` is what the model sees (no dots)."""

    name: str
    description: str
    parameters: dict[str, JsonValue]
    handler: ToolHandler


@dataclass(frozen=True)
class SessionSpec:
    model: str
    system_prompt: str
    tools: Sequence[CopilotTool]
    allow: Callable[[PermissionAsk], bool]
    """Answers the SDK's permission requests; the connector maps the answer to the SDK's types."""


class CopilotSession(Protocol):
    """One open SDK session. Events arrive on the callbacks given to `subscribe`, which may run
    on any thread."""

    def subscribe(self, handler: Callable[[CopilotEvent], None]) -> Callable[[], None]: ...

    async def send(self, prompt: str) -> None: ...

    async def abort(self) -> None: ...

    async def close(self) -> None: ...


class CopilotConnector(Protocol):
    """Opens sessions on one person's Copilot. It holds the token; nothing else does."""

    async def open(self, spec: SessionSpec) -> CopilotSession: ...


# --- The run ---


class _Stopped(Exception):
    """`cancel()` was called while the run was waiting."""


@dataclass
class _Turn:
    """What the run has seen so far, to build the final message and check the contract."""

    deltas: list[str] = field(default_factory=list[str])
    last_message: str | None = None
    model: str | None = None
    saw_usage: bool = False


NEEDS_ATTENTION = "copilot_needs_attention"
NO_SUBSCRIPTION = "copilot_no_subscription"
RATE_LIMITED = "copilot_rate_limited"

# The SDK's own errors carry the HTTP status in their text, for example "Failed to validate SDK
# token (401): GitHub returned: Bad credentials" (seen in the 8.2 spike).
_STATUS_IN_TEXT = re.compile(r"\((\d{3})\)")


def status_of(message: str, status_code: int | None = None) -> int | None:
    """The HTTP status of an SDK error: the one it carries, else the one its text names."""
    if status_code is not None:
        return status_code
    found = _STATUS_IN_TEXT.search(message)
    return int(found.group(1)) if found else None


def failure(error: SessionError) -> Failed:
    """Map an SDK error to `failed`, flagging the ones worth retrying. A refused token, a refused
    Copilot seat and a rate limit get a fixed code and sentence (never the SDK's words, so no
    stack trace or token reaches the console); the rest carry the SDK's message, which the caller
    scrubs of secrets."""
    status = status_of(error.message, error.status_code)
    if status == 401:
        return Failed(
            error=f"{NEEDS_ATTENTION}: GitHub refused the person's token; they must connect "
            "their GitHub account again in Settings > Integrations and rerun"
        )
    if status == 403:
        return Failed(
            error=f"{NO_SUBSCRIPTION}: GitHub refused Copilot access; the account needs an "
            "active Copilot seat"
        )
    if status == 429:
        return Failed(
            error=f"{RATE_LIMITED}: Copilot's rate limit for this account was reached; "
            "try again later",
            retryable=True,
        )
    retryable = status is not None and (status in _RETRYABLE_STATUS or status >= 500)
    where = f" {status}" if status is not None else ""
    return Failed(error=f"Copilot error{where}: {error.message}", retryable=retryable)


class CopilotRun:
    """One run on Copilot. Implements `AgentRun`."""

    def __init__(
        self,
        connector: CopilotConnector,
        request: AgentRequest,
        *,
        model: str,
        tools: ToolExecutor | None,
        secrets: Sequence[str],
    ) -> None:
        self._connector = connector
        self._request = request
        self._model = request.model or model
        self._tools = tools
        self._secrets = tuple(s for s in secrets if s)
        self._cancel = asyncio.Event()
        self._started = False
        self._queue: asyncio.Queue[CopilotEvent | AgentEvent] = asyncio.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None

    def cancel(self) -> None:
        self._cancel.set()

    def __aiter__(self) -> AsyncIterator[AgentEvent]:
        if self._started:
            raise RuntimeError("an AgentRun can only be iterated once")
        self._started = True
        return self._stream()

    def _scrub(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, "[redacted]")
        return text

    def _put(self, item: CopilotEvent | AgentEvent) -> None:
        """Queue an item from the SDK's callback, which may run on another thread."""
        assert self._loop is not None
        self._loop.call_soon_threadsafe(self._queue.put_nowait, item)

    async def _stream(self) -> AsyncIterator[AgentEvent]:
        self._loop = asyncio.get_running_loop()
        try:
            async with contextlib.aclosing(self._events()) as events:
                async for event in events:
                    yield event
        except _Stopped:
            yield Cancelled()

    async def _events(self) -> AsyncGenerator[AgentEvent]:
        if self._cancel.is_set():
            raise _Stopped
        tools = self._resolve_tools()
        if isinstance(tools, Failed):
            yield tools
            return
        offered = [self._copilot_tool(t) for t in tools]
        granted = {t.name for t in offered}

        def allow(ask: PermissionAsk) -> bool:
            if ask.kind == "custom-tool" and ask.tool_name in granted:
                return True
            log.warning("Copilot permission denied: kind=%s tool=%s", ask.kind, ask.tool_name)
            return False

        spec = SessionSpec(
            model=self._model,
            system_prompt=system_prompt(self._request),
            tools=offered,
            allow=allow,
        )
        try:
            session = await self._connector.open(spec)
        except Exception as e:
            message = self._scrub(_describe(e))
            if status_of(message) in {401, 403, 429}:
                yield self._scrubbed(failure(SessionError(message)))
            else:
                yield Failed(error=f"Copilot could not start: {message}")
            return
        unsubscribe = session.subscribe(self._put)
        try:
            await session.send(user_turn(self._request.input))
            turn = _Turn()
            while True:
                try:
                    item = await self._unless_cancelled(self._queue.get())
                except _Stopped:
                    await _quietly(session.abort())
                    raise
                done = False
                for event in self._translate(item, turn):
                    yield event
                    done = done or is_terminal(event)
                if done:
                    return
        except _Stopped:
            raise
        except Exception as e:
            yield Failed(error=f"Copilot error: {self._scrub(_describe(e))}")
        finally:
            unsubscribe()
            await _quietly(session.close())

    def _translate(self, item: CopilotEvent | AgentEvent, turn: _Turn) -> list[AgentEvent]:
        match item:
            case TextChunk(text=text):
                turn.deltas.append(text)
                return [TextDelta(text=self._scrub(text))]
            case ReasoningChunk(text=text):
                return [ReasoningDelta(text=self._scrub(text))]
            case AssistantMessage(text=text):
                turn.last_message = text
                turn.deltas.clear()
                return []
            case UsageReport() as u:
                turn.saw_usage = True
                turn.model = u.model or turn.model
                return [
                    Usage(
                        model=u.model,
                        input_tokens=u.input_tokens,
                        output_tokens=u.output_tokens,
                        cache_read_tokens=u.cache_read_tokens,
                        cache_write_tokens=u.cache_write_tokens,
                    )
                ]
            case SessionError() as e:
                return [self._scrubbed(failure(e))]
            case SessionIdle(aborted=True):
                return [Cancelled()] if self._cancel.is_set() else [Failed(error="Copilot aborted")]
            case SessionIdle():
                text = turn.last_message if turn.last_message is not None else "".join(turn.deltas)
                events: list[AgentEvent] = []
                if not turn.saw_usage:
                    events.append(Usage(model=turn.model, input_tokens=0, output_tokens=0))
                return [*events, Message(text=self._scrub(text)), Completed()]
            case _:  # a ToolCall or ToolResult from a handler: already an AgentEvent
                return [item]

    def _scrubbed(self, failed: Failed) -> Failed:
        return Failed(error=self._scrub(failed.error), retryable=failed.retryable)

    def _resolve_tools(self) -> list[ToolDefinition] | Failed:
        """The requested tools, or `failed` before any session if one cannot be offered."""
        names = self._request.tools
        if not names:
            return []
        if self._tools is None:
            return Failed(error=f"tools requested but no tool executor is set: {', '.join(names)}")
        known = {t.name: t for t in self._tools.definitions()}
        missing = [n for n in names if n not in known]
        if missing:
            return Failed(error=f"unknown tools: {', '.join(missing)}")
        invalid = [n for n in names if not _TOOL_NAME.match(api_tool_name(n))]
        if invalid:
            return Failed(error=f"tool names Copilot cannot use: {', '.join(invalid)}")
        return [known[n] for n in names]

    def _copilot_tool(self, definition: ToolDefinition) -> CopilotTool:
        async def handler(call_id: str, arguments: dict[str, JsonValue]) -> ToolReply:
            self._put(ToolCall(call_id=call_id, name=definition.name, arguments=arguments))
            reply = await self._call_tool(definition.name, arguments)
            self._put(ToolResult(call_id=call_id, output=reply.text, is_error=reply.is_error))
            return reply

        return CopilotTool(
            name=api_tool_name(definition.name),
            description=definition.description,
            parameters=definition.input_schema,
            handler=handler,
        )

    async def _call_tool(self, name: str, arguments: dict[str, JsonValue]) -> ToolReply:
        assert self._tools is not None  # a tool is only offered when there is an executor
        try:
            output = await self._unless_cancelled(
                self._tools.call(name, arguments, node_id=self._request.node_id)
            )
        except _Stopped:
            return ToolReply(text="stopped: the run was cancelled", is_error=True)
        except Exception as e:
            return ToolReply(text=f"tool failed: {self._scrub(_describe(e))}", is_error=True)
        return ToolReply(text=self._scrub(output.text), is_error=output.is_error)

    async def _unless_cancelled[T](self, work: Awaitable[T]) -> T:
        """Await `work`, or raise `_Stopped` (cancelling `work`) if `cancel()` comes first."""
        if self._cancel.is_set():
            if asyncio.iscoroutine(work):
                work.close()
            raise _Stopped
        task = asyncio.ensure_future(work)
        stop = asyncio.ensure_future(self._cancel.wait())
        try:
            await asyncio.wait({task, stop}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            stop.cancel()
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        if task.cancelled():
            raise _Stopped
        return task.result()


def _describe(error: Exception) -> str:
    return str(error) or type(error).__name__


async def _quietly(work: Awaitable[None]) -> None:
    """Run cleanup that must not mask the run's own outcome."""
    with contextlib.suppress(Exception):
        await work


class CopilotRuntime:
    """Starts agent runs on Copilot. Implements `AgentRuntime`.

    `connector` opens sessions on one person's Copilot (it holds their token). `secrets` are the
    strings that must never appear in an event, normally just that token. `tools` runs the tools a
    request names; without it, a request that names tools fails.
    """

    def __init__(
        self,
        connector: CopilotConnector,
        *,
        model: str = DEFAULT_MODEL,
        tools: ToolExecutor | None = None,
        secrets: Sequence[str] = (),
    ) -> None:
        self._connector = connector
        self._model = model
        self._tools = tools
        self._secrets = tuple(secrets)

    def start(self, request: AgentRequest) -> AgentRun:
        return CopilotRun(
            self._connector, request, model=self._model, tools=self._tools, secrets=self._secrets
        )
