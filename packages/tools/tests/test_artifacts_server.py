"""The `artifacts` MCP server (4.3): agents list and read the run's artifacts, never write them."""

import json
from dataclasses import dataclass
from typing import Any

from mcp import Client

from agentic_tools.artifacts import (
    ARTIFACT_TOOL_NAMES,
    MAX_READ_CHARS,
    build_artifacts_server,
    open_artifact_tools,
)


@dataclass(frozen=True)
class Version:
    name: str
    version: int
    node_id: str
    media_type: str
    size: int
    content: str


class Store:
    """A run's artifacts: every version by name, the last one latest."""

    def __init__(self, *versions: Version) -> None:
        self.versions = versions

    async def get(self, name: str, version: int | None = None) -> Version | None:
        found = [v for v in self.versions if v.name == name]
        if version is None:
            return found[-1] if found else None
        return next((v for v in found if v.version == version), None)

    async def latest(self) -> list[Version]:
        latest = {v.name: v for v in self.versions}
        return [latest[n] for n in sorted(latest)]


FINDINGS = Version("findings.json", 1, "scan", "application/json", 15, '{"findings": []}')
NOTES_1 = Version("notes.md", 1, "a", "text/markdown", 3, "one")
NOTES_2 = Version("notes.md", 2, "b", "text/markdown", 3, "two")


async def call(store: Store, tool: str, mirror_dir: str | None = None, **args: Any) -> Any:
    async with Client(build_artifacts_server(store, mirror_dir=mirror_dir)) as client:
        result = await client.call_tool(tool, args)
    if result.is_error:
        return "error: " + "\n".join(c.text for c in result.content if c.type == "text")
    text = "\n".join(c.text for c in result.content if c.type == "text")
    assert json.loads(text) == result.structured_content
    return result.structured_content


async def test_list_gives_the_latest_version_of_each() -> None:
    listed = await call(Store(FINDINGS, NOTES_1, NOTES_2), "list")

    assert [(a["name"], a["version"], a["node_id"]) for a in listed["artifacts"]] == [
        ("findings.json", 1, "scan"),
        ("notes.md", 2, "b"),
    ]
    assert listed["artifacts"][0]["path"] is None


async def test_list_names_the_sandbox_copy_when_the_run_has_one() -> None:
    listed = await call(Store(FINDINGS), "list", mirror_dir="/workspace/artifacts")

    assert listed["artifacts"][0]["path"] == "/workspace/artifacts/findings.json"


async def test_read_gives_the_latest_or_the_version_asked_for() -> None:
    store = Store(NOTES_1, NOTES_2)

    latest = await call(store, "read", name="notes.md", description="Read the notes")
    first = await call(store, "read", name="notes.md", version=1)

    assert (latest["content"], latest["version"], latest["truncated"]) == ("two", 2, False)
    assert first["content"] == "one"


async def test_read_of_a_missing_artifact_says_so() -> None:
    store = Store(NOTES_1)

    missing = await call(store, "read", name="nope.md")
    no_version = await call(store, "read", name="notes.md", version=3)

    assert missing.endswith("the run has no artifact 'nope.md'; see artifacts.list")
    assert no_version.endswith(
        "the run has no version 3 of artifact 'notes.md'; see artifacts.list"
    )


async def test_read_cuts_a_long_artifact() -> None:
    big = "x" * (MAX_READ_CHARS + 10)
    store = Store(Version("big.txt", 1, "a", "text/plain", len(big), big))

    read = await call(store, "read", name="big.txt")

    assert len(read["content"]) == MAX_READ_CHARS
    assert read["truncated"] is True


async def test_unknown_arguments_are_refused_and_there_is_no_write_tool() -> None:
    assert (await call(Store(), "read", name="a.md", path="x")).startswith("error:")
    async with open_artifact_tools(Store()) as tools:
        names = {d.name for d in tools.definitions()}

    assert names == ARTIFACT_TOOL_NAMES == {"artifacts.list", "artifacts.read"}
