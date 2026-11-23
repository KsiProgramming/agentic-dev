"""Platform-owned tools as an adapter sees them: definitions to offer the model and a way to call
them. The real executors are MCP servers bridged by `agentic_tools`; adapters only route calls
here."""

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from agentic_runtime.paths import matches, normalise

NonEmptyStr = Annotated[str, Field(min_length=1)]


class ToolDefinition(BaseModel):
    """A tool the model may call. `input_schema` is the JSON Schema of its arguments."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: NonEmptyStr
    description: str = ""
    input_schema: dict[str, JsonValue] = Field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )


class ToolOutput(BaseModel):
    """What a tool call returned. The text is data, never instructions. `data` is the tool's
    structured result, if it has one (e.g. the pull request `github.openPR` opened)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    is_error: bool = False
    data: dict[str, JsonValue] | None = None


class ToolExecutor(Protocol):
    """Runs platform-owned tools for an agent run."""

    def definitions(self) -> Sequence[ToolDefinition]:
        """Every tool this executor can run; a request may use any subset by name."""
        ...

    async def call(
        self, name: str, arguments: dict[str, JsonValue], *, node_id: str | None = None
    ) -> ToolOutput:
        """Run one tool for the node `node_id`, which lets a run's executor route the call (a
        writer node's `repo.*` calls go to its own worktree). An exception is reported to the
        model as an error result."""
        ...


@dataclass(frozen=True)
class ReadableWriter:
    """A node whose work a later step may read: a `writer` (its own branch) or an `integration`
    (an orchestrator's integration branch, with its team's merged work)."""

    node_id: str
    kind: Literal["writer", "integration"]


class WorkRefused(Exception):
    """A `node` that cannot be read. `str(e)` is the fixed text the tool returns."""


def no_commits_text(node_id: str) -> str:
    return f"writer '{node_id}' has no commits"


class ReadableWriters:
    """The writers whose work the step that is about to run may read (13.1), shared between the
    engine, which sets it before every step from the run's state, and the repo tools, which resolve
    a call's `node` through it (the same pattern as `BranchSaver` and `GateReview`).

    `branch_of` names a node's branch. `known` are all the run's writers, so a refusal can tell
    one that has not run yet from a node that is no writer at all."""

    def __init__(self, branch_of: Callable[[str], str]) -> None:
        self._branch_of = branch_of
        self._ready: dict[str, ReadableWriter] = {}
        self._known: frozenset[str] = frozenset()

    def set(
        self, completed: Sequence[ReadableWriter], known: Collection[str] | None = None
    ) -> None:
        """Replace the writers that completed, in run order; `known` replaces the run's writers
        if given."""
        self._ready = {w.node_id: w for w in completed}
        if known is not None:
            self._known = frozenset(known)

    def writers(self) -> list[ReadableWriter]:
        """The writers that completed, in run order."""
        return list(self._ready.values())

    def branch_name(self, node_id: str) -> str:
        """The branch of `node_id`, whoever it is (no check)."""
        return self._branch_of(node_id)

    def branch(self, node_id: str) -> str:
        """The branch of a writer that completed. Raises `WorkRefused` for a node that is no
        writer of the run or has not run before this step."""
        if node_id in self._ready:
            return self._branch_of(node_id)
        if node_id in self._known:
            raise WorkRefused(f"writer '{node_id}' has not run before this step")
        raise WorkRefused(f"'{node_id}' is not a writer of this run")


@dataclass(frozen=True)
class ProtectRule:
    """One reason a path is protected (13.5). `default` is the platform's own list and `workflow`
    a pattern of the spec's `protect.paths`; both are globs. `frozen` is one file an earlier writer
    changed, which a writer that started from it can read but not change: `glob` is that exact path,
    `writer` the writer it came from and `gate` the gate that approved it."""

    glob: str
    kind: Literal["default", "workflow", "frozen"]
    writer: str | None = None
    gate: str | None = None

    def covers(self, path: str) -> bool:
        if self.kind == "frozen":
            return (
                normalise(self.glob) is not None
                and (normalise(path) or "").lower() == (normalise(self.glob) or "").lower()
            )
        return matches(self.glob, path)


def refusal_text(path: str, rule: ProtectRule) -> str:
    """The fixed text of a refused write: the path and the rule it came from, never file content."""
    if rule.kind == "default":
        why = "by the platform (CI and analyzer config)"
    elif rule.kind == "workflow":
        why = f"by this workflow ({rule.glob})"
    else:
        why = f"(approved at '{rule.gate}' from '{rule.writer}')"
    return f"'{path}' is protected {why}: you can read it but not change it"


class ProtectedPaths:
    """The paths the step that is about to run may not change (13.5), shared between the engine,
    which sets it before every step as it sets `ReadableWriters`, and the repo tools, which check
    every `write_file` and `commit` against it.

    `rules` apply to every writer; `allow` exempts a node from the `default` and `workflow` rules
    its globs match (a person approves what it changes at a gate); `frozen` holds the rules of
    a writer that started from another. A task of an orchestrator (`fix.t1`) takes its
    orchestrator's rules. `refused` is called back for each refusal."""

    def __init__(
        self, on_refused: Callable[[str, str, str, ProtectRule], None] | None = None
    ) -> None:
        self._rules: tuple[ProtectRule, ...] = ()
        self._allow: dict[str, tuple[str, ...]] = {}
        self._frozen: dict[str, tuple[ProtectRule, ...]] = {}
        self.on_refused = on_refused

    def set(
        self,
        rules: Sequence[ProtectRule],
        allow: Mapping[str, Sequence[str]] | None = None,
        frozen: Mapping[str, Sequence[ProtectRule]] | None = None,
    ) -> None:
        """Replace the rules for every node, the per-node exemptions and the frozen files."""
        self._rules = tuple(rules)
        self._allow = {node: tuple(globs) for node, globs in (allow or {}).items()}
        self._frozen = {node: tuple(r) for node, r in (frozen or {}).items()}

    def rules_for(self, node_id: str) -> list[ProtectRule]:
        """Every rule `node_id` is held to, to show an agent: a path its `allow` globs match is
        still listed, since `rule_for` decides."""
        return [*self._rules, *self._frozen.get(node_id.partition(".")[0], ())]

    def rule_for(self, node_id: str, path: str) -> ProtectRule | None:
        """The rule that refuses `node_id` a change to `path`, or None."""
        owner = node_id.partition(".")[0]
        allowed = self._allow.get(owner, ())
        if frozen := next((r for r in self._frozen.get(owner, ()) if r.covers(path)), None):
            return frozen  # the most specific reason: a person approved this very file
        return next(
            (
                r
                for r in self._rules
                if r.covers(path) and not any(matches(g, path) for g in allowed)
            ),
            None,
        )

    def refused(self, node_id: str, tool: str, path: str, rule: ProtectRule) -> None:
        """Tell the engine about one refusal."""
        if self.on_refused is not None:
            self.on_refused(node_id, tool, path, rule)
