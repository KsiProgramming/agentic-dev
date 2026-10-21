"""Agent runtime: the `AgentRuntime` interface, its events, and provider adapters."""

from agentic_runtime.claude import ClaudeRuntime
from agentic_runtime.contract import ContractViolation, check_events
from agentic_runtime.events import (
    TERMINAL_EVENT_TYPES,
    AgentEvent,
    Cancelled,
    Completed,
    Failed,
    Message,
    TerminalEvent,
    TextDelta,
    ToolCall,
    ToolResult,
    Usage,
    agent_event_adapter,
    is_terminal,
)
from agentic_runtime.protocol import AgentRun, AgentRuntime
from agentic_runtime.request import AgentRequest
from agentic_runtime.tools import ToolDefinition, ToolExecutor, ToolOutput

__all__ = [
    "TERMINAL_EVENT_TYPES",
    "AgentEvent",
    "AgentRequest",
    "AgentRun",
    "AgentRuntime",
    "Cancelled",
    "ClaudeRuntime",
    "Completed",
    "ContractViolation",
    "Failed",
    "Message",
    "TerminalEvent",
    "TextDelta",
    "ToolCall",
    "ToolDefinition",
    "ToolExecutor",
    "ToolOutput",
    "ToolResult",
    "Usage",
    "agent_event_adapter",
    "check_events",
    "is_terminal",
]
