"""A scripted stand-in for the Copilot SDK, for tests and the fake stack. No network, no token use.

A script is a list of steps played when the run sends its prompt: events the SDK would report
(`TextChunk`, `UsageReport`, ...), `CallTool` (the SDK calls one of the offered tools, as it does
in its own loop), `Ask` (the SDK asks permission) and `Hang` (nothing more comes, for cancel
tests). The fake records what the run gave it, so a test can assert what an agent receives.
"""

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from pydantic import JsonValue

from agentic_runtime.copilot import (
    CopilotEvent,
    CopilotSession,
    PermissionAsk,
    SessionSpec,
    ToolReply,
)


@dataclass(frozen=True)
class CallTool:
    """The SDK calls an offered tool (by the name the model sees) with these arguments."""

    name: str
    arguments: dict[str, JsonValue] = field(default_factory=dict[str, JsonValue])
    call_id: str = "call-1"


@dataclass(frozen=True)
class Ask:
    """The SDK asks permission; the answer is recorded in `FakeCopilotSession.answers`."""

    ask: PermissionAsk


@dataclass(frozen=True)
class Hang:
    """Nothing more comes until the session is aborted."""


Step = CopilotEvent | CallTool | Ask | Hang


class FakeCopilotSession:
    """Implements `CopilotSession`."""

    def __init__(self, spec: SessionSpec, script: Sequence[Step]) -> None:
        self.spec = spec
        self.prompts: list[str] = []
        self.answers: list[tuple[PermissionAsk, bool]] = []
        self.tool_replies: list[ToolReply] = []
        self.aborted = False
        self.closed = False
        self._script = list(script)
        self._handlers: list[Callable[[CopilotEvent], None]] = []
        self._abort = asyncio.Event()
        self._player: asyncio.Task[None] | None = None

    def subscribe(self, handler: Callable[[CopilotEvent], None]) -> Callable[[], None]:
        self._handlers.append(handler)
        return lambda: self._handlers.remove(handler) if handler in self._handlers else None

    async def send(self, prompt: str) -> None:
        self.prompts.append(prompt)
        self._player = asyncio.ensure_future(self._play())

    async def abort(self) -> None:
        self.aborted = True
        self._abort.set()

    async def close(self) -> None:
        self.closed = True
        if self._player is not None and not self._player.done():
            self._player.cancel()

    def _emit(self, event: CopilotEvent) -> None:
        for handler in list(self._handlers):
            handler(event)

    async def _play(self) -> None:
        tools = {t.name: t for t in self.spec.tools}
        for step in self._script:
            await asyncio.sleep(0)  # let the run read what was emitted before the next step
            match step:
                case CallTool(name=name, arguments=arguments, call_id=call_id):
                    # The SDK asks permission before it runs a custom tool.
                    allowed = self.spec.allow(PermissionAsk(kind="custom-tool", tool_name=name))
                    self.answers.append((PermissionAsk("custom-tool", name), allowed))
                    if allowed and name in tools:
                        self.tool_replies.append(await tools[name].handler(call_id, arguments))
                case Ask(ask=ask):
                    self.answers.append((ask, self.spec.allow(ask)))
                case Hang():
                    await self._abort.wait()
                    return
                case _:
                    self._emit(step)


class FakeCopilotConnector:
    """Implements `CopilotConnector`. `sessions` lists every session opened, newest last."""

    def __init__(self, script: Sequence[Step], *, open_error: Exception | None = None) -> None:
        self._script = list(script)
        self._open_error = open_error
        self.sessions: list[FakeCopilotSession] = []

    async def open(self, spec: SessionSpec) -> CopilotSession:
        if self._open_error is not None:
            raise self._open_error
        session = FakeCopilotSession(spec, self._script)
        self.sessions.append(session)
        return session
