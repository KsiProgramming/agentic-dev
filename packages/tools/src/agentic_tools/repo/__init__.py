"""The `repo` MCP server over a run's sandbox, and `open_repo_tools`, which connects a run's
agents to it: readers to the shared checkout, writers each to their own worktree."""

from agentic_tools.repo.paths import repo_relative
from agentic_tools.repo.routing import RepoTools, open_repo_tools
from agentic_tools.repo.server import (
    COMMIT_AUTHOR,
    SERVER_NAME,
    WRITE_TOOLS,
    RepoLimits,
    build_repo_server,
)

WRITE_TOOL_NAMES = frozenset(f"{SERVER_NAME}.{tool}" for tool in WRITE_TOOLS)
"""The platform names of the write tools (`repo.write_file`, `repo.commit`): a node whose spec
names one is a writer."""


__all__ = [
    "COMMIT_AUTHOR",
    "SERVER_NAME",
    "WRITE_TOOLS",
    "WRITE_TOOL_NAMES",
    "RepoLimits",
    "RepoTools",
    "build_repo_server",
    "open_repo_tools",
    "repo_relative",
]
