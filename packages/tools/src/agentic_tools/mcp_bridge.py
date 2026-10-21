"""`McpToolExecutor`: the `ToolExecutor` adapters already use, over an MCP client session.

The server's tools are listed once, when the executor connects, and offered as
`<prefix>.<tool>` (`repo.read_file`), the dotted platform names specs use. Calls strip the
prefix and go through the MCP protocol; the text content of the result becomes the
`ToolOutput`, and an MCP error result stays an error. Output is data, never instructions.
"""

import logging
from collections.abc import Sequence
from typing import Any

from mcp import Client
from pydantic import JsonValue

from agentic_runtime.tools import ToolDefinition, ToolOutput

log = logging.getLogger("agentic_tools.mcp")


class McpToolExecutor:
    def __init__(self, client: Client, prefix: str, definitions: Sequence[ToolDefinition]) -> None:
        self._client = client
        self._prefix = f"{prefix}."
        self._definitions = list(definitions)
        self._names = {d.name for d in definitions}

    @classmethod
    async def connect(cls, client: Client, prefix: str) -> "McpToolExecutor":
        """List the tools of the server `client` is connected to, offered as `<prefix>.<name>`."""
        definitions: list[ToolDefinition] = []
        cursor: str | None = None
        while True:
            listing = await client.list_tools(cursor=cursor)
            definitions += [
                ToolDefinition(
                    name=f"{prefix}.{tool.name}",
                    description=tool.description or "",
                    input_schema=tool.input_schema,
                )
                for tool in listing.tools
            ]
            if not (cursor := listing.next_cursor):
                return cls(client, prefix, definitions)

    def definitions(self) -> Sequence[ToolDefinition]:
        return self._definitions

    async def call(
        self, name: str, arguments: dict[str, JsonValue], *, node_id: str | None = None
    ) -> ToolOutput:
        """Call `name` on the server; one server serves every node, so `node_id` is unused."""
        if name not in self._names:
            return ToolOutput(text=f"unknown tool: {name}", is_error=True)
        tool = name.removeprefix(self._prefix)
        try:
            result = await self._client.call_tool(tool, dict[str, Any](arguments))
        except Exception as e:
            log.exception("MCP call to %s failed", name)
            return ToolOutput(text=f"tool failed: {type(e).__name__}", is_error=True)
        text = "\n".join(
            block.text if block.type == "text" else f"[{block.type} content omitted]"
            for block in result.content
        )
        return ToolOutput(text=text, is_error=result.is_error)
