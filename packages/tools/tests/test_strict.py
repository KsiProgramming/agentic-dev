"""`strict_tool`: strict arguments, an example call and the caller's optional intent."""

from typing import Annotated

import pytest
from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import TextContent
from pydantic import Field

from agentic_tools.strict import INTENT_HELP, INTENT_MAX_LENGTH, strict_tool

seen: list[dict[str, object]] = []


def greet(name: Annotated[str, Field(description="Who to greet.")]) -> str:
    """Say hello."""
    seen.append({"name": name})
    return f"hello {name}"


def label(description: str | None = None) -> str:
    """A tool whose own `description` means something else."""
    return f"label {description}"


def server() -> MCPServer:
    return MCPServer(
        "t",
        tools=[
            strict_tool(greet, {"name": "Ada", "description": "Greet the user"}),
            strict_tool(label, {"description": "a label"}),
        ],
    )


async def call(tool: str, arguments: dict[str, object]) -> tuple[bool, str]:
    async with Client(server()) as client:
        result = await client.call_tool(tool, arguments)
    text = "".join(c.text for c in result.content if isinstance(c, TextContent))
    return result.is_error, text


async def test_the_schema_offers_an_optional_intent() -> None:
    async with Client(server()) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}

    schema = tools["greet"].input_schema
    assert schema["required"] == ["name"]
    assert schema["additionalProperties"] is False
    assert INTENT_HELP in str(schema["properties"]["description"])
    assert schema["examples"] == [{"name": "Ada", "description": "Greet the user"}]


async def test_the_intent_never_reaches_the_function() -> None:
    seen.clear()

    error, text = await call("greet", {"name": "Ada", "description": "Greet the user"})

    assert (error, text) == (False, "hello Ada")
    assert seen == [{"name": "Ada"}]


async def test_a_call_without_an_intent_still_works() -> None:
    assert await call("greet", {"name": "Ada"}) == (False, "hello Ada")


@pytest.mark.parametrize(
    "arguments",
    [
        {"name": "Ada", "colour": "red"},
        {"name": "Ada", "description": "x" * (INTENT_MAX_LENGTH + 1)},
    ],
)
async def test_unknown_arguments_and_long_intents_are_refused(
    arguments: dict[str, object],
) -> None:
    error, _ = await call("greet", arguments)

    assert error


async def test_a_tool_with_its_own_description_keeps_it() -> None:
    async with Client(server()) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}

    assert INTENT_HELP not in str(tools["label"].input_schema)
    assert await call("label", {"description": "mine"}) == (False, "label mine")
