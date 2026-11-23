"""Asking an outward write tool for its plan (13.8), and reading the answer.

`plan_call` calls a tool node's tool with the engine-only argument `plan: true` through the run's
`ToolExecutor` and returns a `WritePlan`: the tool's own, or, when the tool refuses, one that
would fail with the tool's fixed code and text. The engine never builds a plan itself: only the
tool knows which site, issue, branch and base the real call resolves.

The helpers here are the engine's side of the contract in `agentic_runtime.plans`: the parts a
plan leaves to the platform (`pending`), what a tool answers when it refuses a stale plan, and the
text the console shows.
"""

import re
from collections.abc import Mapping

from pydantic import JsonValue, ValidationError

from agentic_engine.spec import ToolNode
from agentic_runtime import ToolExecutor
from agentic_runtime.plans import (
    EXPECT_ARG,
    PLAN_ARG,
    STALE_PREFIX,
    PlanAction,
    PlanError,
    PlanPending,
    PlanTarget,
    WritePlan,
)

ACTIONS: Mapping[str, PlanAction] = {
    "github.openPR": "open_pr",
    "github.createRepo": "create_repo",
    "jira.comment": "comment",
    "jira.transition": "transition",
}

_CODE = re.compile(r"(?:Error executing tool \w+:\s*)?([a-z][a-z_]*):\s*(.*)", re.DOTALL)
MAX_ERROR_CHARS = 300


def split_error(text: str) -> tuple[str, str]:
    """A tool's refusal as `(code, message)`: its text starts with a fixed code
    (`transition_unavailable: …`), after the MCP server's own prefix. Text without one is
    `tool_failed`."""
    found = _CODE.match(text.strip())
    if found is None:
        return "tool_failed", text.strip()[:MAX_ERROR_CHARS]
    return found.group(1), found.group(2).strip()[:MAX_ERROR_CHARS]


def is_stale(text: str) -> bool:
    return split_error(text)[0] == STALE_PREFIX


def pending_parts(node: ToolNode) -> list[PlanPending]:
    """What the platform adds to the write only after approval, from its own results, never from
    a model: a comment's links (`links_from`) and a pull request's review notes (`notes_from`)."""
    parts: list[PlanPending] = []
    if "links_from" in node.args:
        parts.append(
            PlanPending(
                kind="links",
                text="Links to the pull request and the files in it are added once it is open.",
            )
        )
    if "notes_from" in node.args:
        parts.append(
            PlanPending(
                kind="review_notes",
                text="The review's comments that are not dismissed are added to the description.",
            )
        )
    return parts


def failing_plan(node: ToolNode, args: Mapping[str, JsonValue], text: str) -> WritePlan:
    """The plan of a write whose plan mode refused (a project not picked, a missing artifact): it
    would fail, with the tool's code and text. The target is what the arguments name."""
    code, message = split_error(text)
    kind = "issue" if node.tool.startswith("jira.") else "repo"
    named = args.get("issue") or args.get("from_node") or args.get("name") or node.id
    return WritePlan(
        node_id=node.id,
        tool=node.tool,
        action=ACTIONS[node.tool],
        summary=f"Would fail: {code}",
        target=PlanTarget(kind=kind, label=str(named)[:120]),
        pending=pending_parts(node),
        error=PlanError(code=code, message=message),
    )


async def plan_call(
    node: ToolNode,
    called: ToolNode,
    tools: ToolExecutor,
    expect: Mapping[str, JsonValue] | None = None,
) -> WritePlan:
    """The plan of `node`, whose arguments are resolved in `called` (the call as it will go out):
    the tool's plan mode, with `expect` handed back when given. Never raises."""
    args: dict[str, JsonValue] = {**called.args, PLAN_ARG: True}
    if expect is not None:
        args[EXPECT_ARG] = dict(expect)
    try:
        output = await tools.call(node.tool, args, node_id=node.id)
    except Exception as e:
        return failing_plan(node, called.args, f"tool_failed: {type(e).__name__}")
    if output.is_error:
        return failing_plan(node, called.args, output.text)
    try:
        plan = WritePlan.model_validate(output.data)
    except ValidationError:
        return failing_plan(node, called.args, "plan_unreadable: the tool's plan was not readable")
    return plan.model_copy(update={"node_id": node.id, "pending": pending_parts(node)})
