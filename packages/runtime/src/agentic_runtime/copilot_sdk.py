"""The real `CopilotConnector`: the GitHub Copilot SDK (`github-copilot-sdk`, pinned) on one
person's own user token.

This is a thin layer on purpose. Everything about a run lives in `copilot.py` and is tested on a
fake; here the SDK's types are mapped to the connector's, and `translate` is tested on stand-ins
shaped like the SDK's events.

**Written from the SDK's public API and documentation, not yet run against GitHub.** Phase 8.2's
spike (`specs/2026-11-18-copilot-sdk-terms/findings.md`) must confirm with a real token: that a
client runs headless on a stored token, that `available_tools` leaves the SDK's built-in tools
off (an empty list included), that a custom tool's result reaches the model, which permission
requests arrive, whether `append` or `replace` is the right system-message mode, and what the
usage event's `cost` means. Until then this file is unproven.

The token is held here and nowhere else: it goes to the SDK's client and is never part of a
`SessionSpec`, an event or this object's `repr`.
"""

from collections.abc import Callable
from typing import Any, cast

from copilot import CopilotClient, Tool
from copilot.generated.rpc import PermissionDecisionApproveOnce, PermissionDecisionReject
from copilot.tools import ToolInvocation, ToolResult

from agentic_runtime.copilot import (
    AssistantMessage,
    CopilotEvent,
    CopilotSession,
    CopilotTool,
    PermissionAsk,
    ReasoningChunk,
    SessionError,
    SessionIdle,
    SessionSpec,
    TextChunk,
    UsageReport,
)

DENIED = "Not allowed by the platform: only the tools this step was granted may be used."


def translate(event: Any) -> CopilotEvent | None:
    """One SDK session event as a `CopilotEvent`, or `None` for the ones a run does not need.

    The SDK's `input_tokens` already includes cache reads and writes; ours is uncached input, so
    they are taken out.
    """
    data: Any = event.data
    match str(event.type.value):
        case "assistant.message_delta":
            return TextChunk(data.delta_content) if data.delta_content else None
        case "assistant.reasoning_delta":
            return ReasoningChunk(data.delta_content) if data.delta_content else None
        case "assistant.message":
            # A turn that only asks for tools has no text; the last message with text is the answer.
            return AssistantMessage(data.content) if data.content else None
        case "assistant.usage":
            read = data.cache_read_tokens or 0
            write = data.cache_write_tokens or 0
            return UsageReport(
                model=data.model,
                input_tokens=max(0, (data.input_tokens or 0) - read - write),
                output_tokens=data.output_tokens or 0,
                cache_read_tokens=read,
                cache_write_tokens=write,
            )
        case "session.idle":
            return SessionIdle(aborted=bool(data.aborted))
        case "session.error":
            return SessionError(message=str(data.message), status_code=data.status_code)
        case _:
            return None


def permission_handler(allow: Callable[[PermissionAsk], bool]) -> Callable[[Any, Any], Any]:
    """The SDK's permission callback, answered by the platform's own rule."""

    def handle(request: Any, invocation: Any) -> Any:
        ask = PermissionAsk(
            kind=str(getattr(request, "kind", "")),
            tool_name=cast("str | None", getattr(request, "tool_name", None)),
        )
        return PermissionDecisionApproveOnce() if allow(ask) else PermissionDecisionReject(DENIED)

    return handle


def sdk_tool(tool: CopilotTool) -> Tool:
    async def handler(invocation: ToolInvocation) -> ToolResult:
        raw: Any = invocation.arguments
        arguments = cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}
        reply = await tool.handler(invocation.tool_call_id, arguments)
        if reply.is_error:
            return ToolResult(
                text_result_for_llm=reply.text, result_type="failure", error=reply.text
            )
        return ToolResult(text_result_for_llm=reply.text)

    return Tool(
        name=tool.name,
        description=tool.description,
        parameters=dict(tool.parameters),
        handler=handler,
    )


class _SdkSession:
    """Implements `CopilotSession` on one SDK client and session."""

    def __init__(self, client: Any, session: Any) -> None:
        self._client = client
        self._session = session

    def subscribe(self, handler: Callable[[CopilotEvent], None]) -> Callable[[], None]:
        def on_event(event: Any) -> None:
            translated = translate(event)
            if translated is not None:
                handler(translated)

        return self._session.on(on_event)

    async def send(self, prompt: str) -> None:
        await self._session.send(prompt)

    async def abort(self) -> None:
        await self._session.abort()

    async def close(self) -> None:
        try:
            await self._session.disconnect()
        finally:
            await self._client.stop()


class SdkConnector:
    """Implements `CopilotConnector`. One per run: it holds that run's starter's token."""

    def __init__(
        self,
        token: str,
        *,
        client_factory: Callable[[str], Any] | None = None,
    ) -> None:
        if not token:
            raise ValueError("a Copilot token is required")
        self._token = token
        self._client_factory = client_factory or _new_client

    def __repr__(self) -> str:
        return "SdkConnector(token=<hidden>)"

    async def open(self, spec: SessionSpec) -> CopilotSession:
        client = self._client_factory(self._token)
        await client.start()
        try:
            session = await client.create_session(
                on_permission_request=permission_handler(spec.allow),
                model=spec.model,
                # Append keeps Copilot's own instructions for tools; whether `replace` is
                # needed is for the spike to say.
                system_message={"mode": "append", "content": spec.system_prompt},
                tools=[sdk_tool(t) for t in spec.tools],
                # Only the platform's tools: leaves the SDK's built-in shell and file tools off.
                available_tools=[t.name for t in spec.tools],
                streaming=True,
            )
        except BaseException:
            await client.stop()
            raise
        return _SdkSession(client, session)


def _new_client(token: str) -> Any:
    # An explicit token turns the signed-in-user fallback off (SDK docs, "GitHub OAuth").
    return CopilotClient(github_token=token, use_logged_in_user=False)
