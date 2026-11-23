"""Test-only scripts for the stack's fake agents (13.7, e2e).

An agent whose instructions start with `[fake:repeat-failing-call]` reads a file that does not
exist, again and again, until a circuit breaker stops it. Once a person resumed the run, the
agent has been told why it was paused ("# Paused before" in its context), and it answers instead:
that is what the e2e test checks the resumed agent received. Any other agent is the wrapped
runtime's.
"""

from typing import Final

from agentic_runtime import AgentRequest, AgentRun, AgentRuntime, Completed, Message
from agentic_runtime.fake import ECHO_USAGE, CallTool, FakeRun, Step
from agentic_runtime.tools import ToolExecutor

REPEAT_FAILING_CALL: Final = "[fake:repeat-failing-call]"
MISSING_PATH: Final = "docs/does-not-exist.md"


class RepeatingFakeRuntime:
    """`inner`, except for agents that ask for `REPEAT_FAILING_CALL`."""

    def __init__(self, inner: AgentRuntime, tools: ToolExecutor | None) -> None:
        self._inner = inner
        self._tools = tools

    def start(self, request: AgentRequest) -> AgentRun:
        if not request.instructions.startswith(REPEAT_FAILING_CALL):
            return self._inner.start(request)
        if "# Paused before" in request.context:
            steps: list[Step] = [
                Message(text=f"{MISSING_PATH} does not exist, so I stop reading it."),
                ECHO_USAGE,
                Completed(),
            ]
        else:
            steps = [
                *(CallTool("repo.read_file", {"path": MISSING_PATH}) for _ in range(30)),
                ECHO_USAGE,
                Completed(),
            ]
        return FakeRun(steps, self._tools, node_id=request.node_id)
