"""`McpToolExecutor` over the real `repo` server (fake and Docker sandboxes), and over small
servers for the edge cases."""

from typing import Any, cast

from mcp import Client
from mcp.server.mcpserver import MCPServer

from agentic_runtime import AgentRequest, ClaudeRuntime, ToolCall, ToolResult
from agentic_runtime.testing import MockClaude, collect_and_check, text_reply, tool_use_reply
from agentic_sandbox import Sandbox
from agentic_tools.mcp_bridge import McpToolExecutor
from agentic_tools.repo import open_repo_tools


async def test_offers_the_repo_tools_with_their_schemas(sandbox: Sandbox) -> None:
    async with open_repo_tools(sandbox) as tools:
        definitions = {d.name: d for d in tools.definitions()}

    assert sorted(definitions) == [
        "repo.list_files",
        "repo.list_modules",
        "repo.read_file",
        "repo.search",
    ]
    read = definitions["repo.read_file"]
    assert read.description.startswith("Read a text file from the repository.")
    assert read.input_schema["required"] == ["path"]
    assert read.input_schema["additionalProperties"] is False
    assert read.input_schema["examples"] == [
        {"path": "pyproject.toml", "end_line": 60, "description": "Read the project settings"}
    ]


async def test_calls_go_through_the_server(sandbox: Sandbox) -> None:
    async with open_repo_tools(sandbox) as tools:
        output = await tools.call("repo.read_file", {"path": "README.md"})

    assert (output.text, output.is_error) == ("1\t# Hello repo", False)


async def test_error_results_stay_errors(sandbox: Sandbox) -> None:
    async with open_repo_tools(sandbox) as tools:
        output = await tools.call("repo.read_file", {"path": "/etc/passwd"})

    assert output.is_error
    assert "path must stay inside the repository" in output.text


async def test_unknown_and_unprefixed_names_are_errors(sandbox: Sandbox) -> None:
    async with open_repo_tools(sandbox) as tools:
        unknown = await tools.call("repo.write_file", {})
        unprefixed = await tools.call("read_file", {"path": "README.md"})

    assert (unknown.is_error, unknown.text) == (True, "unknown tool: repo.write_file")
    assert (unprefixed.is_error, unprefixed.text) == (True, "unknown tool: read_file")


async def test_a_raising_tool_is_an_error_result() -> None:
    server = MCPServer("boom")

    @server.tool()
    def explode() -> str:  # pyright: ignore[reportUnusedFunction]
        raise RuntimeError("secret detail")

    async with Client(server) as client:
        tools = await McpToolExecutor.connect(client, "boom")
        output = await tools.call("boom.explode", {})

    assert output.is_error


async def test_a_failing_session_is_an_error_without_details() -> None:
    class Broken:
        async def call_tool(self, name: str, arguments: dict[str, Any]) -> None:
            raise ConnectionError("lost /var/run/secret")

    tools = McpToolExecutor(cast(Client, Broken()), "repo", [])
    tools._names.add("repo.list_files")  # pyright: ignore[reportPrivateUsage]

    output = await tools.call("repo.list_files", {})

    assert (output.is_error, output.text) == (True, "tool failed: ConnectionError")


async def test_claude_reads_a_file_through_the_repo_server(sandbox: Sandbox) -> None:
    """With a scripted Claude: the adapter's tool call goes through MCP into the sandbox."""
    mock = MockClaude(
        [
            tool_use_reply(("toolu_1", "repo__read_file", {"path": "src/app.py"})),
            text_reply("It prints hello."),
        ]
    )
    request = AgentRequest(
        node_id="reader",
        role="Explorer",
        instructions="What does src/app.py do?",
        tools=["repo.list_files", "repo.read_file", "repo.search"],
    )

    async with open_repo_tools(sandbox) as tools:
        events = await collect_and_check(ClaudeRuntime(mock.client, tools=tools), request)

    call = next(e for e in events if isinstance(e, ToolCall))
    result = next(e for e in events if isinstance(e, ToolResult))
    assert (call.name, call.arguments) == ("repo.read_file", {"path": "src/app.py"})
    assert (result.output, result.is_error) == ("1\tprint('hello')", False)
    sent_back = mock.requests[1]["messages"][-1]["content"][0]
    assert sent_back["content"] == result.output
    offered = sorted(t["name"] for t in mock.requests[0]["tools"])
    assert offered == ["repo__list_files", "repo__read_file", "repo__search"]


async def test_structured_results_become_the_output_data(sandbox: Sandbox) -> None:
    async with open_repo_tools(sandbox) as tools:
        output = await tools.call("repo.list_modules", {})

    assert not output.is_error
    assert output.data == {"modules": [{"path": "src", "kind": "directory"}], "truncated": False}
