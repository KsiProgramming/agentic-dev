"""`list_modules` on the `repo` MCP server, on both sandbox backends (see conftest)."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from mcp import Client

from agentic_sandbox import RepoSource, SandboxManager
from agentic_sandbox.testing import make_repo
from agentic_tools.repo import RepoLimits, build_repo_server


async def _modules(
    manager: SandboxManager,
    repos: Path,
    files: Mapping[str, str],
    limits: RepoLimits | None = None,
    **arguments: Any,
) -> dict[str, Any]:
    """`list_modules`'s structured result on a repo of `files`; its text holds the same JSON."""
    repo = make_repo(repos / f"r{uuid4().hex[:8]}", files)
    async with (
        manager.open(uuid4(), RepoSource(url=str(repo))) as box,
        Client(build_repo_server(box, limits=limits)) as client,
    ):
        result = await client.call_tool("list_modules", arguments)
    assert not result.is_error, result.content
    text = "\n".join(c.text for c in result.content if c.type == "text")
    assert json.loads(text) == result.structured_content
    assert result.structured_content is not None
    return result.structured_content


MONOREPO = {
    "pyproject.toml": "[tool.uv.workspace]\n",
    "packages/api/pyproject.toml": "[project]\n",
    "packages/api/src/api/__init__.py": "",
    "packages/engine/pyproject.toml": "[project]\n",
    "web/package.json": "{}\n",
    "web/node_modules/left-pad/package.json": "{}\n",
    "services/billing/Billing.csproj": "<Project/>\n",
    "tools/go/cli/go.mod": "module cli\n",
    "docs/site/package.json": "{}\n",
    ".github/actions/x/package.json": "{}\n",
}


async def test_lists_each_directory_with_a_manifest(manager: SandboxManager, repos: Path) -> None:
    result = await _modules(manager, repos, MONOREPO)

    assert result == {
        "modules": [
            {"path": "packages/api", "kind": "python"},
            {"path": "packages/engine", "kind": "python"},
            {"path": "services/billing", "kind": "dotnet"},
            {"path": "tools/go/cli", "kind": "go"},
            {"path": "web", "kind": "node"},
        ],
        "truncated": False,
    }


async def test_a_single_package_repo_is_one_module(manager: SandboxManager, repos: Path) -> None:
    files = {"pyproject.toml": "[project]\n", "package.json": "{}\n", "src/app/__init__.py": ""}

    result = await _modules(manager, repos, files)

    assert result["modules"] == [{"path": ".", "kind": "python"}]


async def test_without_manifests_lists_top_level_directories(
    manager: SandboxManager, repos: Path
) -> None:
    files = {"README.md": "x", "src/a.c": "", "lib/b.c": "", "docs/x.md": "", ".ci/y": ""}

    result = await _modules(manager, repos, files)

    assert result["modules"] == [
        {"path": "lib", "kind": "directory"},
        {"path": "src", "kind": "directory"},
    ]


async def test_a_flat_repo_is_the_whole_repository(manager: SandboxManager, repos: Path) -> None:
    result = await _modules(manager, repos, {"README.md": "x", "main.c": ""})

    assert result["modules"] == [{"path": ".", "kind": "repo"}]


async def test_include_filters_by_glob(manager: SandboxManager, repos: Path) -> None:
    result = await _modules(manager, repos, MONOREPO, include=["packages/*", "web"])

    assert [m["path"] for m in result["modules"]] == ["packages/api", "packages/engine", "web"]


async def test_long_lists_are_truncated(manager: SandboxManager, repos: Path) -> None:
    result = await _modules(manager, repos, MONOREPO, RepoLimits(max_modules=2))

    assert [m["path"] for m in result["modules"]] == ["packages/api", "packages/engine"]
    assert result["truncated"] is True


async def test_bad_arguments_are_reported(manager: SandboxManager, repos: Path) -> None:
    repo = make_repo(repos / "bad", {"README.md": "x"})
    async with (
        manager.open(uuid4(), RepoSource(url=str(repo))) as box,
        Client(build_repo_server(box)) as client,
    ):
        result = await client.call_tool("list_modules", {"include": [""], "depth": 2})

    assert result.is_error
