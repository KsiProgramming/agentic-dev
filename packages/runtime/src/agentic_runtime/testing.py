"""Test helpers shared by the runtime and engine test suites."""

import asyncio
import ipaddress
import json
import socket
from collections.abc import AsyncIterator, Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, cast

import anthropic
import httpx2
from pydantic import JsonValue

from agentic_runtime.contract import check_events
from agentic_runtime.events import AgentEvent
from agentic_runtime.protocol import AgentRuntime
from agentic_runtime.request import AgentRequest
from agentic_runtime.tools import ToolDefinition, ToolOutput


class NetworkBlockedError(RuntimeError):
    """A test tried to reach the network while `block_network()` was active."""


def _is_local(host: object) -> bool:
    if host is None or host == "localhost":
        return True
    if isinstance(host, bytes):
        host = host.decode()
    try:
        return ipaddress.ip_address(str(host).split("%")[0]).is_loopback
    except ValueError:
        return False


@contextmanager
def block_network() -> Generator[None]:
    """Fail any DNS lookup or connection that leaves this machine.

    Loopback and Unix sockets stay allowed: asyncio needs them internally (e.g. socketpair on
    Windows). `NetworkBlockedError` is not an `OSError`, so client retry logic cannot swallow it.
    """
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo
    unix = getattr(socket, "AF_UNIX", None)

    def check(sock: socket.socket, address: Any) -> None:
        if sock.family == unix or not isinstance(address, tuple):
            return
        host = cast(tuple[object, ...], address)[0]
        if not _is_local(host):
            raise NetworkBlockedError(f"network access blocked in tests: connect to {address!r}")

    def connect(self: socket.socket, address: Any) -> None:
        check(self, address)
        real_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        check(self, address)
        return real_connect_ex(self, address)

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if not _is_local(host):
            raise NetworkBlockedError(f"network access blocked in tests: resolve {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    setattr(socket.socket, "connect", connect)  # noqa: B010
    setattr(socket.socket, "connect_ex", connect_ex)  # noqa: B010
    setattr(socket, "getaddrinfo", getaddrinfo)  # noqa: B010
    try:
        yield
    finally:
        setattr(socket.socket, "connect", real_connect)  # noqa: B010
        setattr(socket.socket, "connect_ex", real_connect_ex)  # noqa: B010
        setattr(socket, "getaddrinfo", real_getaddrinfo)  # noqa: B010


async def collect_and_check(runtime: AgentRuntime, request: AgentRequest) -> list[AgentEvent]:
    """Run `request` to its end and check the stream against the `AgentRuntime` contract.

    Every adapter's tests use this, so they are all held to the same contract."""
    events = [event async for event in runtime.start(request)]
    check_events(events)
    return events


class ScriptedToolExecutor:
    """A `ToolExecutor` whose tools return fixed outputs (or raise a fixed exception).
    `examples` gives some tools an example call in their input schema."""

    def __init__(
        self,
        tools: Mapping[str, str | ToolOutput | Exception],
        *,
        examples: Mapping[str, dict[str, JsonValue]] | None = None,
    ) -> None:
        self._tools = dict(tools)
        self._examples = dict(examples or {})
        self.calls: list[tuple[str, dict[str, JsonValue]]] = []
        self.node_ids: list[str | None] = []
        """The `node_id` of each call, in order."""
        self.gate: asyncio.Event | None = None
        """If set, each call waits for it first (to test cancelling a call in flight)."""

    def definitions(self) -> Sequence[ToolDefinition]:
        return [
            ToolDefinition(
                name=name,
                description=f"Test tool {name}",
                input_schema={"type": "object", "examples": [self._examples[name]]}
                if name in self._examples
                else {"type": "object", "properties": {}},
            )
            for name in self._tools
        ]

    async def call(
        self, name: str, arguments: dict[str, JsonValue], *, node_id: str | None = None
    ) -> ToolOutput:
        self.calls.append((name, arguments))
        self.node_ids.append(node_id)
        if self.gate is not None:
            await self.gate.wait()
        result = self._tools[name]
        if isinstance(result, Exception):
            raise result
        return result if isinstance(result, ToolOutput) else ToolOutput(text=result)


MOCK_API_KEY = "sk-ant-test-0000-do-not-log"


@dataclass(frozen=True)
class MockReply:
    """One scripted Messages API response: SSE `events`, an error `status`, or a transport
    `error` to raise. With `hang`, the stream stalls after its first two events."""

    events: Sequence[dict[str, Any]] = ()
    status: int = 200
    body: dict[str, Any] | None = None
    error: Exception | None = None
    hang: bool = False


def _message_start(input_tokens: int) -> dict[str, Any]:
    return {
        "type": "message_start",
        "message": {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-test",
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": input_tokens, "output_tokens": 1},
        },
    }


def _text_block(index: int, chunks: Sequence[str]) -> list[dict[str, Any]]:
    start = {
        "type": "content_block_start",
        "index": index,
        "content_block": {"type": "text", "text": ""},
    }
    deltas = [
        {"type": "content_block_delta", "index": index, "delta": {"type": "text_delta", "text": c}}
        for c in chunks
    ]
    return [start, *deltas, {"type": "content_block_stop", "index": index}]


def _end(stop_reason: str, output_tokens: int) -> list[dict[str, Any]]:
    return [
        {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": {"output_tokens": output_tokens},
        },
        {"type": "message_stop"},
    ]


def text_reply(
    *chunks: str,
    stop_reason: str = "end_turn",
    input_tokens: int = 12,
    output_tokens: int = 5,
    hang: bool = False,
) -> MockReply:
    """A streamed text answer, one delta per chunk."""
    events = [
        _message_start(input_tokens),
        *_text_block(0, chunks),
        *_end(stop_reason, output_tokens),
    ]
    return MockReply(events=events, hang=hang)


def tool_use_reply(
    *calls: tuple[str, str, dict[str, Any]],
    text: str = "",
    input_tokens: int = 20,
    output_tokens: int = 8,
) -> MockReply:
    """Claude asks for tools: `calls` are `(tool_use_id, api_tool_name, input)`."""
    events = [_message_start(input_tokens)]
    index = 0
    if text:
        events += _text_block(0, [text])
        index = 1
    for i, (call_id, name, args) in enumerate(calls, start=index):
        events += [
            {
                "type": "content_block_start",
                "index": i,
                "content_block": {"type": "tool_use", "id": call_id, "name": name, "input": {}},
            },
            {
                "type": "content_block_delta",
                "index": i,
                "delta": {"type": "input_json_delta", "partial_json": json.dumps(args)},
            },
            {"type": "content_block_stop", "index": i},
        ]
    return MockReply(events=[*events, *_end("tool_use", output_tokens)])


def error_reply(status: int, message: str = "test error", kind: str = "api_error") -> MockReply:
    return MockReply(
        status=status, body={"type": "error", "error": {"type": kind, "message": message}}
    )


class MockClaude:
    """A real `AsyncAnthropic` on an in-memory transport that answers each Messages API call
    with the next scripted reply, and records the request bodies. No network is used."""

    def __init__(self, replies: Sequence[MockReply]) -> None:
        self._replies = list(replies)
        self.requests: list[dict[str, Any]] = []
        self.api_keys: list[str] = []
        """The `x-api-key` header of each call, in order."""
        self.clients: list[anthropic.AsyncAnthropic] = []
        """Every client made by `make_client`."""
        self.closed = asyncio.Event()
        """Set when a hanging stream's response is closed (the run stopped reading it)."""
        self.client = self.make_client(MOCK_API_KEY)

    def make_client(self, api_key: str) -> anthropic.AsyncAnthropic:
        """Another client on the same script, sending `api_key`."""
        client = anthropic.AsyncAnthropic(
            api_key=api_key,
            max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(self._handle)),
        )
        self.clients.append(client)
        return client

    async def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        self.api_keys.append(request.headers.get("x-api-key", ""))
        if not self._replies:
            raise AssertionError(f"unexpected API call #{len(self.requests)}")
        reply = self._replies.pop(0)
        if reply.error is not None:
            raise reply.error
        if reply.status != 200:
            return httpx2.Response(reply.status, json=reply.body)
        frames = [f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode() for e in reply.events]
        if not reply.hang:
            return httpx2.Response(
                200, headers={"content-type": "text/event-stream"}, content=b"".join(frames)
            )
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, content=self._hang(frames[:3])
        )

    async def _hang(self, frames: Sequence[bytes]) -> AsyncIterator[bytes]:
        try:
            for frame in frames:
                yield frame
            await asyncio.Event().wait()
        finally:
            self.closed.set()
