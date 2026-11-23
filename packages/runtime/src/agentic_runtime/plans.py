"""The plan of an outward write (13.8): what a tool would do, worked out without doing it.

Each outward write tool (`github.openPR`, `github.createRepo`, `jira.comment`, `jira.transition`)
has a plan mode (the engine-only argument `plan: true`) that returns a `WritePlan`. The engine asks
for the plans before a gate pauses, shows them under "What approving does", plans again before the
first write of the batch (`same_plan`), and compares each result with its plan (`compare`).

The model lives here, beside `agentic_runtime.findings`, so the tools and the engine share it
without depending on each other. A plan carries comment and pull request text, which is data: it
is shown as sanitised Markdown or text, never as HTML. It never holds a token or a host path.
"""

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, Field, JsonValue

type PlanAction = Literal["open_pr", "push_to_pr", "create_repo", "comment", "transition"]
type TargetKind = Literal["repo", "issue", "pull_request"]
type PendingKind = Literal["links", "review_notes"]
type Outcome = Literal["as_planned", "differs", "stale"]

PLAN_ARG = "plan"
EXPECT_ARG = "expect"
ENGINE_ONLY_ARGS = frozenset({PLAN_ARG, EXPECT_ARG})
"""The arguments only the engine passes: a spec's `args` may not set them, and the tool manifests
do not list them."""

STALE_PREFIX = "plan_stale"
"""A tool refuses with `plan_stale: <what changed>` when an `expect` no longer holds."""


class PlanTarget(BaseModel):
    """What the write acts on."""

    kind: TargetKind
    label: str = Field(description="`org/repo`, an issue key or `org/repo#12`.")
    url: str | None = Field(default=None, description="Where a person can see it, if anywhere.")


class PlanPending(BaseModel):
    """A part of the write the platform fills in only after approval, from its own results."""

    kind: PendingKind
    text: str = Field(
        description="One line saying what is added, e.g. 'Links to the pull request'."
    )


class PlanError(BaseModel):
    """Why the write would fail now: a fixed code and text, never the service's own words."""

    code: str
    message: str


class WritePlan(BaseModel):
    node_id: str | None = Field(
        default=None, description="The tool node the plan is for; the engine sets it."
    )
    tool: str = Field(description="The platform's tool name, e.g. `jira.comment`.")
    action: PlanAction
    summary: str = Field(description="One line the platform writes.")
    target: PlanTarget
    fields: dict[str, JsonValue] = Field(
        default_factory=dict[str, JsonValue],
        description="The values a result is compared with.",
    )
    body: str | None = Field(
        default=None, description="Markdown to show (a comment, a pull request's body); data."
    )
    pending: list[PlanPending] = Field(default_factory=list[PlanPending])
    expect: dict[str, JsonValue] = Field(
        default_factory=dict[str, JsonValue],
        description="The preconditions handed back to the tool at apply time.",
    )
    error: PlanError | None = None


class Difference(BaseModel):
    field: str
    planned: JsonValue = None
    actual: JsonValue = None


def compare(
    plan: WritePlan,
    result: Mapping[str, JsonValue],
    fill: Mapping[str, JsonValue] | None = None,
) -> list[Difference]:
    """How the `result` of a write differs from its `plan`, field by field.

    `fill` holds the planned values that are known only after approval (`pending` parts the
    platform filled in from its own results, a tip a gate edit moved), by field name. A field the
    result does not report is not compared: a tool only reports what it did."""
    planned = {**plan.fields, **(fill or {})}
    differences: list[Difference] = []
    for name in COMPARED[plan.action]:
        if name not in planned or name not in result:
            continue
        if planned[name] != result[name]:
            differences.append(Difference(field=name, planned=planned[name], actual=result[name]))
    return differences


COMPARED: dict[PlanAction, tuple[str, ...]] = {
    "comment": ("key", "text"),
    "transition": ("key", "from_status", "to_status"),
    "open_pr": ("repo", "head", "base", "commit", "title", "body"),
    "push_to_pr": ("repo", "head", "base", "commit"),
    "create_repo": ("full_name", "private"),
}
"""The fields of a plan's `fields` that a tool's result is compared with, per action. The names
are those of both the plan's `fields` and the tool's structured result."""


SHOWN_ONLY = frozenset({"commits", "offered", "created", "number"})
"""Fields a plan shows but that are no precondition, so a change in them is not a stale plan: how
many commits a push has (a gate edit adds one), the moves a workflow offers, whether this run
posted a comment already (a step run again after a crash has), and a pull request's number."""


def same_plan(shown: WritePlan, again: WritePlan) -> list[Difference]:
    """How a plan made again differs from the one a person was shown: its `fields`, its `expect`,
    its body (which has none of its `pending` parts) and whether it would fail. Anything else
    (`summary`, `target`) follows from these."""
    differences: list[Difference] = []
    for name in sorted((set(shown.fields) | set(again.fields)) - SHOWN_ONLY):
        before, after = shown.fields.get(name), again.fields.get(name)
        if before != after:
            differences.append(Difference(field=name, planned=before, actual=after))
    for name in sorted(set(shown.expect) | set(again.expect)):
        before, after = shown.expect.get(name), again.expect.get(name)
        if before != after:
            differences.append(Difference(field=f"expect.{name}", planned=before, actual=after))
    if shown.body != again.body:
        differences.append(Difference(field="body", planned=shown.body, actual=again.body))
    before_error = shown.error.code if shown.error else None
    after_error = again.error.code if again.error else None
    if before_error != after_error:
        differences.append(Difference(field="error", planned=before_error, actual=after_error))
    return differences


def fill_for(plan: WritePlan, args: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """The planned values that are known only after approval, from the call as it went out
    (`args`, with the review's notes and the links the platform made put in place): a comment's
    text and a pull request's title and description. Never from a model's answer."""
    filled: dict[str, JsonValue] = {}
    body = args.get("body")
    if plan.action == "comment" and isinstance(body, str):
        footer = plan.fields.get("footer")
        text = body.rstrip() + "\n\n" + footer if isinstance(footer, str) else body
        filled["text"] = text
    if plan.action == "open_pr":
        if isinstance(body, str):
            filled["body"] = body
        if isinstance(title := args.get("title"), str):
            filled["title"] = title
    return filled


def describe(differences: list[Difference]) -> str:
    """What changed, as one line for a `plan_stale` failure (the fields and their values, cut)."""
    parts = [f"{d.field}: {_short(d.planned)} -> {_short(d.actual)}" for d in differences[:5]]
    more = len(differences) - 5
    return "; ".join(parts) + (f" (and {more} more)" if more > 0 else "")


def _short(value: JsonValue) -> str:
    text = value if isinstance(value, str) else repr(value)
    text = " ".join(text.split())
    return text if len(text) <= 60 else text[:57] + "..."
