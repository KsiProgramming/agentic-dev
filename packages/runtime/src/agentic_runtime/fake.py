"""A deterministic `AgentRuntime` for tests: replays scripted events, with no network or I/O."""

import asyncio
import contextlib
import re
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass

from agentic_runtime.contract import check_events
from agentic_runtime.events import (
    AgentEvent,
    Cancelled,
    Completed,
    Message,
    TextDelta,
    Usage,
    is_terminal,
)
from agentic_runtime.request import AgentRequest


@dataclass(frozen=True)
class Delay:
    """A script step that waits; `cancel()` interrupts it."""

    seconds: float


type Step = AgentEvent | Delay
type Script = Sequence[Step]

ECHO_USAGE = Usage(input_tokens=10, output_tokens=10)


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
    events = [s for s in steps if not isinstance(s, Delay)]
    if not events or not is_terminal(events[-1]):
        steps.append(Completed())
        events.append(Completed())
    try:
        check_events(events)
    except ValueError as e:
        raise ValueError(f"script for node {node_id!r}: {e}") from e
    return tuple(steps)


class FakeRun:
    """Replays one script. Implements `AgentRun`."""

    def __init__(self, steps: Sequence[Step]) -> None:
        self._steps = steps
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
        for step in self._steps:
            if self._cancel.is_set():
                yield Cancelled()
                return
            if isinstance(step, Delay):
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._cancel.wait(), step.seconds)
                continue
            yield step
            if is_terminal(step):
                return


class FakeRuntime:
    """Scripted per `node_id`; nodes without a script get `default(request.input)`
    (`echo_script` unless given).

    Scripts are checked against the contract up front, so a bad script fails at construction.
    A script without a terminal event gets `completed` appended.
    """

    def __init__(
        self,
        scripts: Mapping[str, Script] | None = None,
        *,
        default: Callable[[str], Script] = echo_script,
    ) -> None:
        self._scripts = {node_id: _prepare(node_id, s) for node_id, s in (scripts or {}).items()}
        self._default = default
        self.requests: list[AgentRequest] = []

    def start(self, request: AgentRequest) -> FakeRun:
        self.requests.append(request)
        if request.node_id in self._scripts:
            return FakeRun(self._scripts[request.node_id])
        return FakeRun(_prepare(request.node_id, self._default(request.input)))
