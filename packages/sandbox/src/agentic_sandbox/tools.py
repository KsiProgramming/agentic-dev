"""Repo tools that run inside a run's sandbox. `repo.list_files` is the first; phase 1.2 moves
the repo tools into the `repo` MCP server."""

import re
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from agentic_runtime.tools import ToolDefinition, ToolOutput
from agentic_sandbox.protocol import Sandbox

MAX_ENTRIES = 1000

LIST_FILES = ToolDefinition(
    name="repo.list_files",
    description=(
        "List the files and directories in the repository, as paths relative to its root. "
        "Directories end with '/'. The .git directory is skipped."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory to list, relative to the repository root.",
                "default": ".",
            },
            "max_depth": {
                "type": "integer",
                "description": "How many directory levels to descend.",
                "minimum": 1,
                "maximum": 10,
                "default": 3,
            },
        },
        "additionalProperties": False,
    },
)

# Lists `$1` (relative to the repo root) to depth `$2`: directories, a marker line, then the rest.
# `cd -P` resolves symlinks, so a link pointing out of the repo is refused (exit 4).
_LIST_SCRIPT = """
root=$(pwd -P)
cd -P -- "$1" 2>/dev/null || exit 3
case "$(pwd -P)/" in "$root"/*) ;; *) exit 4 ;; esac
find . -mindepth 1 -maxdepth "$2" -name .git -prune -o -type d -print || exit 1
echo ::files::
find . -mindepth 1 -maxdepth "$2" -name .git -prune -o ! -type d -print || exit 1
"""
_DRIVE = re.compile(r"^[A-Za-z]:")


class ListFilesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = "."
    max_depth: Annotated[int, Field(ge=1, le=10)] = 3


class SandboxTools:
    """Implements `ToolExecutor` for one run's sandbox. Outputs are data, never instructions."""

    def __init__(self, sandbox: Sandbox, *, max_entries: int = MAX_ENTRIES) -> None:
        self._sandbox = sandbox
        self._max_entries = max_entries

    def definitions(self) -> Sequence[ToolDefinition]:
        return [LIST_FILES]

    async def call(self, name: str, arguments: dict[str, JsonValue]) -> ToolOutput:
        if name != LIST_FILES.name:
            return ToolOutput(text=f"unknown tool: {name}", is_error=True)
        try:
            args = ListFilesArgs.model_validate(arguments)
        except ValidationError as e:
            problems = "; ".join(f"{'.'.join(map(str, d['loc']))}: {d['msg']}" for d in e.errors())
            return ToolOutput(text=f"invalid arguments: {problems}", is_error=True)
        return await self._list_files(args)

    async def _list_files(self, args: ListFilesArgs) -> ToolOutput:
        relative = repo_relative(args.path)
        if relative is None:
            return ToolOutput(
                text=f"path must stay inside the repository: {args.path}", is_error=True
            )
        argv = ["sh", "-c", _LIST_SCRIPT, "list_files", f"./{relative}", str(args.max_depth)]
        result = await self._sandbox.exec(argv)
        if result.exit_code in (3, 4):
            return ToolOutput(text=f"not a directory in the repository: {args.path}", is_error=True)
        if result.exit_code != 0 or ("::files::" not in result.stdout and not result.truncated):
            return ToolOutput(text="could not list the files", is_error=True)

        dirs, _, files = result.stdout.partition("::files::")
        prefix = "" if relative == "." else f"{relative}/"
        entries = sorted(
            [f"{prefix}{line[2:]}/" for line in dirs.splitlines() if line.startswith("./")]
            + [f"{prefix}{line[2:]}" for line in files.splitlines() if line.startswith("./")]
        )
        if not entries:
            return ToolOutput(text="(empty directory)")
        shown = entries[: self._max_entries]
        text = "\n".join(shown)
        if len(entries) > len(shown) or result.truncated:
            total = f"more than {len(entries)}" if result.truncated else str(len(entries))
            text += f"\n(truncated: showing {len(shown)} of {total} entries)"
        return ToolOutput(text=text)


def repo_relative(path: str) -> str | None:
    """`path` normalised relative to the repo root (`.` for the root), or None if it is absolute
    or leaves the repo."""
    path = path.replace("\\", "/").strip()
    if path.startswith("/") or _DRIVE.match(path):
        return None
    parts = [p for p in PurePosixPath(path).parts if p != "."]
    if ".." in parts:
        return None
    return "/".join(parts) or "."
