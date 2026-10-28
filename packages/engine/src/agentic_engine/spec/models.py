"""Workflow spec v0: the document the canvas, Architect, monitor and engine share.

New primitives are added as members of the `Node` union; existing specs keep validating.
"""

from collections.abc import Callable, Collection, Iterator
from dataclasses import dataclass, field
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from agentic_engine.expr import ExpressionError, compile_condition, compile_list
from agentic_engine.policy import PLATFORM_POLICY, Policy, PolicyLimit
from agentic_engine.ports import schema_problem

NodeId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,62}$")]
"""Slug used in branch names (`agent/<run>/<node>`), so it must be path- and ref-safe."""

NonEmptyStr = Annotated[str, Field(min_length=1)]

PortSchema = Annotated[
    dict[str, JsonValue],
    Field(
        description="A JSON Schema 2020-12 whose root is an object, with only local `$ref`s.",
        examples=[{"type": "object", "required": ["findings"], "properties": {"findings": {}}}],
    ),
]
"""A typed port (4.2): checked against the value that crosses it, at runtime."""

ArtifactName = Annotated[
    str,
    Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,58}\.(json|md|txt)$",
        description="A run artifact's name: letters, digits, `.`, `_` and `-`, ending in `.json`, "
        "`.md` or `.txt`, which give its media type.",
        examples=["findings.json"],
    ),
]
"""The name of a run artifact (4.3), shared by the nodes of one run."""

_WRITES_DESCRIPTION = (
    "Write the node's output as this run artifact (a new version each time it runs); a `.json` "
    "artifact must be JSON."
)
_READS_DESCRIPTION = (
    "Take these run artifacts as input, instead of the previous output: one artifact's content, "
    "or an object by name for several."
)


class _Base(BaseModel):
    # One JSON Schema per model: a spec is both sent (`POST /runs`) and read back
    # (`GET /runs/{id}`), and both sides name it the same.
    model_config = ConfigDict(extra="forbid", frozen=True, json_schema_mode_override="validation")


class AgentNode(_Base):
    """One agent turn: a role and instructions run on a provider."""

    type: Literal["agent"]
    id: NodeId
    role: NonEmptyStr
    instructions: NonEmptyStr
    provider: Literal["claude"] | None = Field(
        default=None, description="Unset means the workspace default."
    )
    model: NonEmptyStr | None = None
    tools: list[str] = Field(default_factory=list[str])
    input_schema: PortSchema | None = Field(
        default=None, description="Its input must be JSON that matches this, or it does not start."
    )
    output_schema: PortSchema | None = Field(
        default=None,
        description="It is asked to answer with JSON that matches this, and fails if it does not; "
        "the parsed object is its `data`.",
    )
    reads: list[ArtifactName] = Field(
        default_factory=list[str], max_length=8, description=_READS_DESCRIPTION
    )
    writes: ArtifactName | None = Field(default=None, description=_WRITES_DESCRIPTION)

    @model_validator(mode="after")
    def _unique_reads(self) -> Self:
        return _check_unique_reads(self)


class ToolNode(_Base):
    """One call of a platform tool with fixed arguments; no model is involved. Its output is the
    next node's input, and an error result fails the node."""

    type: Literal["tool"]
    id: NodeId
    tool: NonEmptyStr = Field(description="The platform tool to call, e.g. `repo.list_files`.")
    args: dict[str, JsonValue] = Field(
        default_factory=dict[str, JsonValue], description="The tool's arguments."
    )
    input_schema: PortSchema | None = Field(
        default=None, description="Its input must be JSON that matches this, or it does not run."
    )
    output_schema: PortSchema | None = Field(
        default=None,
        description="Its structured result (else its text as JSON) must match this, or it fails.",
    )
    reads: list[ArtifactName] = Field(
        default_factory=list[str], max_length=8, description=_READS_DESCRIPTION
    )
    writes: ArtifactName | None = Field(default=None, description=_WRITES_DESCRIPTION)

    @model_validator(mode="after")
    def _unique_reads(self) -> Self:
        return _check_unique_reads(self)


def _check_unique_reads[N: AgentNode | ToolNode](node: N) -> N:
    if len(set(node.reads)) != len(node.reads):
        raise ValueError(f"node {node.id!r}: `reads` names an artifact twice")
    return node


class GateNode(_Base):
    """A human decision point: the run pauses here until someone approves or rejects. Its input
    (the previous node's output) is shown to the approver and passes through unchanged."""

    type: Literal["gate"]
    id: NodeId
    title: NonEmptyStr = Field(description="What the approver is asked to decide.")
    prompt: str | None = Field(
        default=None, description="More guidance for the approver, shown with the input."
    )
    ttl_s: int | None = Field(
        default=None,
        ge=1,
        description="Seconds the gate waits for a decision before the run is cancelled; at most "
        "the run's `approval_ttl_s`, which applies when this is unset.",
    )


class SequenceNode(_Base):
    """Runs its steps in order."""

    type: Literal["sequence"]
    id: NodeId
    steps: list["Node"] = Field(min_length=1)


MAX_LOOP_ITERATIONS = PLATFORM_POLICY.loop_iterations
"""The platform's ceiling for loop iterations; a workspace policy may lower it (`policy_errors`)."""


class LoopNode(_Base):
    """Runs its body again and again until `until` is true, at most `max_iterations` times.

    Iteration 1 gets the loop's input; each later one gets the previous iteration's output, and
    the loop's output is its last iteration's. `until` is a CEL condition over `last` (the body's
    output), `iteration` (iterations completed, from 1) and `results` (node id → `{status, text,
    data}`, the latest result of each node run so far). Reaching `max_iterations` ends the loop
    normally. The body cannot contain gates, writers, publishers or loops: each is keyed by node
    id, which repeats in every iteration."""

    type: Literal["loop"]
    id: NodeId
    body: "Node"
    until: NonEmptyStr = Field(
        description="CEL condition checked after each iteration; true stops the loop.",
        examples=['last.contains("APPROVED")'],
    )
    max_iterations: int = Field(ge=1, le=MAX_LOOP_ITERATIONS)


MAX_AGENTS_ALIVE = PLATFORM_POLICY.agents_alive
"""The platform's ceiling for agents running at once; caps `map.max_concurrency`. A workspace
policy may lower it (`policy_errors`)."""

MAX_AGENTS_SPAWNED = PLATFORM_POLICY.agents_spawned
"""The platform's ceiling for agents a run may start. A map's item count is only known at
runtime, so the engine checks it there against the run's policy."""


class MapNode(_Base):
    """Runs its body once per item of the list `over` evaluates to, at most `max_concurrency` at
    a time, and outputs the items' outputs in item order.

    `over` is a CEL expression over `last` (the map's input) and `results` (as for a loop's
    `until`), e.g. `results.list_modules.data.modules`. Each item is its body's input: a string
    as is, any other value as JSON. The body can only hold agent, tool and sequence nodes: the
    others are keyed by node id, which repeats for every item. Its items' agents count toward the
    run's `agents_spawned` limit; one item that does not complete fails the map."""

    type: Literal["map"]
    id: NodeId
    over: NonEmptyStr = Field(
        description="CEL expression that evaluates to the list of items.",
        examples=["results.list_modules.data.modules"],
    )
    body: "Node"
    max_concurrency: int = Field(ge=1, le=MAX_AGENTS_ALIVE)


class ReduceAgent(_Base):
    """The agent a `reduce` node with the `agent` strategy runs, as for an `agent` node."""

    role: NonEmptyStr
    instructions: NonEmptyStr
    provider: Literal["claude"] | None = Field(
        default=None, description="Unset means the workspace default."
    )
    model: NonEmptyStr | None = None


class ReduceNode(_Base):
    """Combines the outputs of the map `from`, which runs before it, in item order.

    `concat` joins them with `separator`. `agent` runs one agent turn whose input is the JSON
    array `[{"item": …, "output": …}]` (data, never instructions)."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_mode_override="validation",
        validate_by_name=True,
        serialize_by_alias=True,
    )

    type: Literal["reduce"]
    id: NodeId
    from_: NodeId = Field(alias="from", description="The map whose outputs are combined.")
    strategy: Literal["concat", "agent"]
    separator: str | None = Field(
        default=None, description="`concat` only: what goes between outputs (default two newlines)."
    )
    agent: ReduceAgent | None = Field(default=None, description="`agent` only, and required.")
    writes: ArtifactName | None = Field(default=None, description=_WRITES_DESCRIPTION)

    @model_validator(mode="after")
    def _strategy_fields(self) -> Self:
        if self.strategy == "agent" and self.agent is None:
            raise ValueError("the agent strategy needs `agent`")
        if self.strategy != "agent" and self.agent is not None:
            raise ValueError("`agent` is only used by the agent strategy")
        if self.strategy != "concat" and self.separator is not None:
            raise ValueError("`separator` is only used by the concat strategy")
        return self


class ParallelNode(_Base):
    """Runs its branches at the same time, each on the parallel's input, and joins them.

    `join` says when the parallel is done: `all` once every branch completed, `any` once one
    did, `quorum` once `quorum` did. It decides as soon as the outcome is known (`all` fails on
    the first branch that does not complete, the others once the join can no longer be met) and
    the branches still running end `node_cancelled`. Its output is the completed branches'
    outputs in branch order. A branch is one `agent`, `tool` or `sequence` node, its id names the
    branch, and it holds no gate, writer or publisher. Every agent in the branches counts toward
    the run's `agents_spawned` limit when the parallel starts."""

    type: Literal["parallel"]
    id: NodeId
    branches: list["Node"] = Field(min_length=2, max_length=MAX_AGENTS_ALIVE)
    join: Literal["all", "any", "quorum"]
    quorum: int | None = Field(
        default=None, description="`quorum` only, and required: how many branches must complete."
    )

    @model_validator(mode="after")
    def _join_fields(self) -> Self:
        if self.join != "quorum":
            if self.quorum is not None:
                raise ValueError("`quorum` is only used by the quorum join")
            return self
        if self.quorum is None:
            raise ValueError("the quorum join needs `quorum`")
        if not 1 <= self.quorum <= len(self.branches):
            raise ValueError(
                f"`quorum` {self.quorum} must be from 1 to the {len(self.branches)} branches"
            )
        return self


Node = Annotated[
    AgentNode | ToolNode | GateNode | SequenceNode | LoopNode | MapNode | ReduceNode | ParallelNode,
    Field(discriminator="type"),
]


def iter_nodes(node: Node, path: str = "root") -> Iterator[tuple[str, Node]]:
    """Yield `(path, node)` for `node` and all its descendants, depth first.

    Paths use the JSON field names, e.g. `root.steps[1].steps[0]`.
    """
    yield path, node
    match node:
        case SequenceNode():
            for i, step in enumerate(node.steps):
                yield from iter_nodes(step, f"{path}.steps[{i}]")
        case LoopNode() | MapNode():
            yield from iter_nodes(node.body, f"{path}.body")
        case ParallelNode():
            for i, branch in enumerate(node.branches):
                yield from iter_nodes(branch, f"{path}.branches[{i}]")
        case _:
            pass


def node_tools(node: Node) -> list[str]:
    """The platform tools `node` itself may call: an agent's `tools`, a tool node's `tool`."""
    match node:
        case AgentNode():
            return list(node.tools)
        case ToolNode():
            return [node.tool]
        case GateNode() | SequenceNode() | LoopNode() | MapNode() | ReduceNode() | ParallelNode():
            return []


READ_TOOLS = frozenset({"repo.list_files", "repo.read_file", "repo.search", "repo.list_modules"})
"""Tools that read the run's repo in the sandbox."""

WRITE_TOOLS = frozenset({"repo.write_file", "repo.commit"})
"""Tools that change a node's own branch in the sandbox: a node naming one is a writer."""

PUBLISH_TOOLS = frozenset({"github.openPR"})
"""Tools that publish a writer's branch outside the sandbox (push, pull request). They are
irreversible, so only a tool node may call one, after a gate that follows the writer."""

CREATE_TOOLS = frozenset({"github.createRepo"})
"""Tools that create the run's repo on GitHub. Irreversible, so only a tool node may call one,
after a gate, as a step of the root sequence before anything uses the repo."""

ARTIFACT_TOOLS = frozenset({"artifacts.list", "artifacts.read"})
"""Tools that read the run's artifacts (4.3). Every run has them, with or without a repo."""

SCAN_TOOLS = frozenset({"scan.lint", "scan.secrets", "scan.dependencies"})
"""Deterministic scanners over the run's repo in the sandbox (4.4): read-only, so allowed
everywhere. Each returns a findings report (`agentic_tools.scan.FindingsReport`)."""

PLATFORM_TOOLS = (
    READ_TOOLS | WRITE_TOOLS | PUBLISH_TOOLS | CREATE_TOOLS | ARTIFACT_TOOLS | SCAN_TOOLS
)
"""Every tool a node may name. The tool servers register exactly these (checked in tests)."""

type IssueCode = Literal[
    "schema",
    "id_mismatch",
    "duplicate_node_id",
    "invalid_expression",
    "not_allowed_in_loop",
    "not_allowed_in_map",
    "not_allowed_in_parallel",
    "reference",
    "publish_not_tool_node",
    "publish_without_gate",
    "create_not_tool_node",
    "create_without_gate",
    "create_not_first",
    "unknown_tool",
    "policy_limit",
    "budget_unpriced_model",
    "invalid_schema",
    "port_mismatch",
    "artifact_unknown",
    "artifact_conflict",
]


class ValidationIssue(_Base):
    """One reason a workflow cannot run: what is wrong (`code`), where (`path`, `node_id`) and
    what to change (`message`). A `policy_limit` issue also names the `limit`, its `value` and
    what the spec would reach (`observed`)."""

    code: IssueCode = Field(description="The kind of problem; stable, so clients may branch on it.")
    path: str = Field(
        description="Where in the spec, by its JSON field names, e.g. `root.steps[1].body`; "
        "empty for the document itself.",
        examples=["root.steps[1].body"],
    )
    node_id: str | None = Field(default=None, description="The node to fix, if there is one.")
    message: str = Field(description="The problem and what to change, for people.")
    limit: PolicyLimit | None = None
    value: int | None = Field(default=None, description="The limit's value.")
    observed: int | None = Field(default=None, description="What the spec would reach.")


def messages(issues: list[ValidationIssue]) -> list[str]:
    """The issues' messages, in order."""
    return [issue.message for issue in issues]


def duplicate_id_issues(root: Node) -> list[ValidationIssue]:
    """Each node under `root` whose id an earlier node already uses, in run order."""
    issues: list[ValidationIssue] = []
    seen: dict[str, str] = {}
    for path, node in iter_nodes(root):
        if node.id not in seen:
            seen[node.id] = path
            continue
        issues.append(
            ValidationIssue(
                code="duplicate_node_id",
                path=path,
                node_id=node.id,
                message=f"duplicate node id {node.id!r} at {path} (first used at "
                f"{seen[node.id]}); node ids must be unique",
            )
        )
    return issues


def publish_gate_issues(root: Node) -> list[ValidationIssue]:
    """Why the publishing nodes under `root` are not safe to run, in run order (depth first);
    empty if they are. Each must be a tool node whose `from_node` names an earlier writer, with a
    gate between that writer and itself, so a human approves what is published."""
    issues: list[ValidationIssue] = []
    seen: list[Node] = []
    for path, node in iter_nodes(root):
        if isinstance(node, SequenceNode | LoopNode | MapNode | ParallelNode):
            continue
        for tool in sorted(PUBLISH_TOOLS.intersection(node_tools(node))):
            if not isinstance(node, ToolNode):
                message = f"node {node.id!r}: {tool} can only be called by a tool node"
                issues.append(
                    ValidationIssue(
                        code="publish_not_tool_node", path=path, node_id=node.id, message=message
                    )
                )
            elif found := _publish_issue(node, seen):
                code, message = found
                issues.append(
                    ValidationIssue(code=code, path=path, node_id=node.id, message=message)
                )
        seen.append(node)
    return issues


def publish_gate_errors(root: Node) -> list[str]:
    """The messages of `publish_gate_issues`."""
    return messages(publish_gate_issues(root))


def _publish_issue(node: "ToolNode", earlier: list[Node]) -> tuple[IssueCode, str] | None:
    source = node.args.get("from_node")
    if not isinstance(source, str):
        return (
            "reference",
            f"node {node.id!r}: {node.tool} needs `from_node`, the writer to publish",
        )
    ids = [n.id for n in earlier]
    if source not in ids:
        return (
            "reference",
            f"node {node.id!r}: `from_node` {source!r} is not a node that runs before it",
        )
    writer = earlier[ids.index(source)]
    if not WRITE_TOOLS.intersection(node_tools(writer)):
        return "reference", f"node {node.id!r}: `from_node` {source!r} is not a writer"
    between = earlier[ids.index(source) + 1 :]
    if not any(isinstance(n, GateNode) for n in between):
        return (
            "publish_without_gate",
            f"node {node.id!r}: {node.tool} must come after a gate that follows {source!r}, so "
            "a human approves what is published",
        )
    return None


def create_repo_issues(root: Node) -> list[ValidationIssue]:
    """Why the nodes under `root` that create the run's repo are not safe to run, in run order;
    empty if they are. Each must be a tool node, a step of the root sequence, and the only one;
    a gate must come before it, so a human approves the new repo, and no node before it may use
    the repo (`repo.*`, `github.*`), which does not exist yet."""
    issues: list[ValidationIssue] = []
    top = {id(step) for step in root.steps} if isinstance(root, SequenceNode) else set[int]()
    earlier: list[Node] = []
    created = False
    for path, node in iter_nodes(root):
        tools = node_tools(node)
        for tool in sorted(CREATE_TOOLS.intersection(tools)):
            found: tuple[IssueCode, str] | None
            if not isinstance(node, ToolNode):
                found = (
                    "create_not_tool_node",
                    f"node {node.id!r}: {tool} can only be called by a tool node",
                )
            elif created:
                found = (
                    "create_not_first",
                    f"node {node.id!r}: a workflow creates at most one repo",
                )
            elif id(node) not in top:
                found = (
                    "create_not_first",
                    f"node {node.id!r}: {tool} must be a step of the root sequence",
                )
            elif user := next((n for n in earlier if _uses_repo(n)), None):
                found = (
                    "create_not_first",
                    f"node {node.id!r}: {tool} must come before {user.id!r}, which uses the repo",
                )
            elif not any(isinstance(n, GateNode) for n in earlier):
                found = (
                    "create_without_gate",
                    f"node {node.id!r}: {tool} must come after a gate, so a human approves the "
                    "new repo",
                )
            else:
                found = None
            if found is not None:
                code, message = found
                issues.append(
                    ValidationIssue(code=code, path=path, node_id=node.id, message=message)
                )
            created = True
        earlier.append(node)
    return issues


def creates_repo(root: Node) -> bool:
    """Whether a node under `root` creates the run's repo."""
    return any(CREATE_TOOLS.intersection(node_tools(node)) for _, node in iter_nodes(root))


REPO_TOOL_PREFIXES = ("repo.", "github.", "scan.")
"""Tools that work on the run's repo, so a run naming one needs a repo: `repo.*` and `scan.*` in
its sandbox, `github.*` on its GitHub remote."""


def _uses_repo(node: Node) -> bool:
    return any(tool.startswith(REPO_TOOL_PREFIXES) for tool in node_tools(node))


def loop_issues(root: Node) -> list[ValidationIssue]:
    """Why the loops under `root` cannot run, in run order (depth first); empty if they can. A
    loop's `until` must be a valid condition, and its body must not hold a gate, a writer, a
    publisher, another loop, a map or a parallel: the issue is on that node, which is the one to
    move."""
    issues: list[ValidationIssue] = []
    for path, node in iter_nodes(root):
        if not isinstance(node, LoopNode):
            continue
        try:
            compile_condition(node.until)
        except ExpressionError as e:
            message = f"loop {node.id!r} at {path}: invalid until: {e}"
            issues.append(
                ValidationIssue(
                    code="invalid_expression", path=path, node_id=node.id, message=message
                )
            )
        for inner_path, inner in iter_nodes(node.body, f"{path}.body"):
            if reason := _not_in_loop(inner):
                message = (
                    f"loop {node.id!r} at {path}: {reason} {inner.id!r} at {inner_path} cannot "
                    "be inside a loop yet"
                )
                issues.append(
                    ValidationIssue(
                        code="not_allowed_in_loop",
                        path=inner_path,
                        node_id=inner.id,
                        message=message,
                    )
                )
    return issues


def loop_errors(root: Node) -> list[str]:
    """The messages of `loop_issues`."""
    return messages(loop_issues(root))


def _not_in_loop(node: Node) -> str | None:
    tools = set(node_tools(node))
    match node:
        case GateNode():
            return "gate"
        case LoopNode():
            return "loop"
        case MapNode():
            return "map"
        case ParallelNode():
            return "parallel"
        case _ if tools & PUBLISH_TOOLS:
            return "publisher"
        case _ if tools & CREATE_TOOLS:
            return "repo creator"
        case _ if tools & WRITE_TOOLS:
            return "writer"
        case _:
            return None


def map_issues(root: Node) -> list[ValidationIssue]:
    """Why the maps and reduces under `root` cannot run, in run order (depth first); empty if
    they can. A map's `over` must be a valid list expression, and its body must hold only agent,
    tool and sequence nodes, none of them a writer or a publisher. A reduce's `from` must name a
    map that runs before it."""
    issues: list[ValidationIssue] = []
    maps: set[str] = set()
    for path, node in iter_nodes(root):
        match node:
            case MapNode():
                try:
                    compile_list(node.over)
                except ExpressionError as e:
                    message = f"map {node.id!r} at {path}: invalid over: {e}"
                    issues.append(
                        ValidationIssue(
                            code="invalid_expression", path=path, node_id=node.id, message=message
                        )
                    )
                for inner_path, inner in iter_nodes(node.body, f"{path}.body"):
                    if reason := _not_in_map(inner):
                        message = (
                            f"map {node.id!r} at {path}: {reason} {inner.id!r} at {inner_path} "
                            "cannot be inside a map yet"
                        )
                        issues.append(
                            ValidationIssue(
                                code="not_allowed_in_map",
                                path=inner_path,
                                node_id=inner.id,
                                message=message,
                            )
                        )
                maps.add(node.id)
            case ReduceNode() if node.from_ not in maps:
                message = (
                    f"reduce {node.id!r} at {path}: `from` {node.from_!r} is not a map that runs "
                    "before it"
                )
                issues.append(
                    ValidationIssue(code="reference", path=path, node_id=node.id, message=message)
                )
            case _:
                pass
    return issues


def map_errors(root: Node) -> list[str]:
    """The messages of `map_issues`."""
    return messages(map_issues(root))


def _not_in_map(node: Node) -> str | None:
    match node:
        case AgentNode() | ToolNode() | SequenceNode():
            return _not_in_loop(node)
        case _:
            return node.type


def parallel_issues(root: Node) -> list[ValidationIssue]:
    """Why the parallels under `root` cannot run, in run order (depth first); empty if they can.
    A branch must hold only agent, tool and sequence nodes, none of them a writer or a publisher
    (as a map's body): the issue is on that node, which is the one to move."""
    issues: list[ValidationIssue] = []
    for path, node in iter_nodes(root):
        if not isinstance(node, ParallelNode):
            continue
        for i, branch in enumerate(node.branches):
            for inner_path, inner in iter_nodes(branch, f"{path}.branches[{i}]"):
                if reason := _not_in_map(inner):
                    message = (
                        f"parallel {node.id!r} at {path}: {reason} {inner.id!r} at {inner_path} "
                        "cannot be inside a parallel yet"
                    )
                    issues.append(
                        ValidationIssue(
                            code="not_allowed_in_parallel",
                            path=inner_path,
                            node_id=inner.id,
                            message=message,
                        )
                    )
    return issues


def tool_issues(root: Node, known_tools: Collection[str] = PLATFORM_TOOLS) -> list[ValidationIssue]:
    """Each tool a node under `root` names that is not one of `known_tools`, in run order."""
    issues: list[ValidationIssue] = []
    known = ", ".join(sorted(known_tools))
    for path, node in iter_nodes(root):
        for tool in node_tools(node):
            if tool in known_tools:
                continue
            message = (
                f"{node.type} {node.id!r} at {path}: unknown tool {tool!r}; use one of {known}"
            )
            issues.append(
                ValidationIssue(code="unknown_tool", path=path, node_id=node.id, message=message)
            )
    return issues


def policy_issues(root: Node, policy: Policy) -> list[ValidationIssue]:
    """Why the spec under `root` cannot run under `policy`, in run order (depth first); empty if
    it can. A loop's `max_iterations` must be within `loop_iterations`, a map's
    `max_concurrency` and a parallel's branches within `agents_alive`, and loops, maps and
    parallels must not nest deeper than `max_depth`, and a gate's `ttl_s` must be within
    `approval_ttl_s`. Agents spawned and wall time are only known at runtime, where the engine
    checks them."""
    issues: list[ValidationIssue] = []

    def over(
        node: Node, path: str, limit: PolicyLimit, value: int, observed: int, why: str
    ) -> None:
        issues.append(
            ValidationIssue(
                code="policy_limit",
                path=path,
                node_id=node.id,
                message=f"{node.type} {node.id!r} at {path}: {why}",
                limit=limit,
                value=value,
                observed=observed,
            )
        )

    def visit(node: Node, path: str, depth: int) -> None:
        match node:
            case LoopNode() if node.max_iterations > policy.loop_iterations:
                why = (
                    f"max_iterations {node.max_iterations} is above the workspace limit of "
                    f"{policy.loop_iterations}"
                )
                over(
                    node, path, "loop_iterations", policy.loop_iterations, node.max_iterations, why
                )
            case MapNode() if node.max_concurrency > policy.agents_alive:
                why = (
                    f"max_concurrency {node.max_concurrency} is above the workspace limit of "
                    f"{policy.agents_alive} agents alive"
                )
                over(node, path, "agents_alive", policy.agents_alive, node.max_concurrency, why)
            case ParallelNode() if len(node.branches) > policy.agents_alive:
                why = (
                    f"{len(node.branches)} branches are above the workspace limit of "
                    f"{policy.agents_alive} agents alive"
                )
                over(node, path, "agents_alive", policy.agents_alive, len(node.branches), why)
            case GateNode() if node.ttl_s is not None and node.ttl_s > policy.approval_ttl_s:
                why = (
                    f"ttl_s {node.ttl_s} is above the workspace limit of "
                    f"{policy.approval_ttl_s} seconds"
                )
                over(node, path, "approval_ttl_s", policy.approval_ttl_s, node.ttl_s, why)
            case _:
                pass
        match node:
            case LoopNode() | MapNode() | ParallelNode():
                if depth + 1 > policy.max_depth:
                    why = (
                        f"nesting depth {depth + 1} is above the workspace limit of "
                        f"{policy.max_depth}"
                    )
                    over(node, path, "max_depth", policy.max_depth, depth + 1, why)
                if isinstance(node, ParallelNode):
                    for i, branch in enumerate(node.branches):
                        visit(branch, f"{path}.branches[{i}]", depth + 1)
                else:
                    visit(node.body, f"{path}.body", depth + 1)
            case SequenceNode():
                for i, step in enumerate(node.steps):
                    visit(step, f"{path}.steps[{i}]", depth)
            case _:
                pass

    visit(root, "root", 0)
    return issues


def policy_errors(root: Node, policy: Policy) -> list[str]:
    """The messages of `policy_issues`."""
    return messages(policy_issues(root, policy))


def budget_issues(
    root: Node, policy: Policy, priced: Callable[[str], bool], default_model: str
) -> list[ValidationIssue]:
    """Why the budget of `policy` cannot be held to the spec under `root`, in spec order; empty
    if it can, or if there is no budget. Every agent (a reduce's too) must run on a model that
    `priced` knows: its own `model`, else `default_model`. A usage with no price cannot be
    counted against a budget."""
    if policy.budget_usd is None:
        return []
    issues: list[ValidationIssue] = []
    for path, node in iter_nodes(root):
        match node:
            case AgentNode():
                model = node.model
            case ReduceNode() if node.agent is not None:
                model = node.agent.model
            case _:
                continue
        model = model or default_model
        if not priced(model):
            message = (
                f"{node.type} {node.id!r} at {path}: model {model!r} has no price, so the "
                "budget cannot be enforced"
            )
            issues.append(
                ValidationIssue(
                    code="budget_unpriced_model",
                    path=path,
                    node_id=node.id,
                    message=message,
                    limit="budget_usd",
                )
            )
    return issues


def budget_errors(
    root: Node, policy: Policy, priced: Callable[[str], bool], default_model: str
) -> list[str]:
    """The messages of `budget_issues`."""
    return messages(budget_issues(root, policy, priced, default_model))


type PortNode = AgentNode | ToolNode
"""A node that may declare typed ports."""

type ArtifactWriter = AgentNode | ToolNode | ReduceNode
"""A node that may write a run artifact."""


@dataclass
class _ArtifactFlow:
    """What `_walk_artifacts` finds: each reader's writers, by artifact name, and the issues."""

    writers: dict[str, dict[str, ArtifactWriter]] = field(
        default_factory=dict[str, dict[str, ArtifactWriter]]
    )
    issues: list[ValidationIssue] = field(default_factory=list[ValidationIssue])


def _walk_artifacts(root: Node) -> _ArtifactFlow:
    """Follow the run artifacts under `root` in run order. A read must have a writer that has
    always run before it: an earlier step, not a sibling branch of the same parallel, and not a
    later step of the same loop body (its first iteration would not have it). A map's body may not
    write (its ids repeat for every item), and two branches of one parallel may not write the same
    name. After a parallel, what its branches wrote is visible."""
    flow = _ArtifactFlow()

    def conflict(node: Node, path: str, why: str) -> None:
        message = f"{node.type} {node.id!r} at {path}: {why}"
        flow.issues.append(
            ValidationIssue(code="artifact_conflict", path=path, node_id=node.id, message=message)
        )

    def visit(node: Node, path: str, seen: dict[str, ArtifactWriter]) -> dict[str, ArtifactWriter]:
        match node:
            case AgentNode() | ToolNode():
                found: dict[str, ArtifactWriter] = {}
                for i, name in enumerate(node.reads):
                    if name in seen:
                        found[name] = seen[name]
                        continue
                    message = (
                        f"{node.type} {node.id!r} at {path}: reads {name!r}, which no node writes "
                        "before it; write it in an earlier step"
                    )
                    flow.issues.append(
                        ValidationIssue(
                            code="artifact_unknown",
                            path=f"{path}.reads[{i}]",
                            node_id=node.id,
                            message=message,
                        )
                    )
                if node.reads:
                    flow.writers[node.id] = found
                return {**seen, node.writes: node} if node.writes else seen
            case ReduceNode():
                return {**seen, node.writes: node} if node.writes else seen
            case GateNode():
                return seen
            case SequenceNode():
                for i, step in enumerate(node.steps):
                    seen = visit(step, f"{path}.steps[{i}]", seen)
                return seen
            case LoopNode():
                return visit(node.body, f"{path}.body", seen)
            case MapNode():
                for inner_path, inner in iter_nodes(node.body, f"{path}.body"):
                    if isinstance(inner, AgentNode | ToolNode | ReduceNode) and inner.writes:
                        conflict(
                            inner,
                            inner_path,
                            f"writes {inner.writes!r} inside map {node.id!r}, which runs it once "
                            "per item; write it after the map (e.g. from a reduce)",
                        )
                visit(node.body, f"{path}.body", seen)
                return seen
            case ParallelNode():
                after = dict(seen)
                by_branch: dict[str, str] = {}
                for i, branch in enumerate(node.branches):
                    branch_path = f"{path}.branches[{i}]"
                    wrote = visit(branch, branch_path, seen)
                    for name, writer in wrote.items():
                        if seen.get(name) is writer:
                            continue
                        if name in by_branch:
                            conflict(
                                writer,
                                branch_path,
                                f"writes {name!r}, which branch {by_branch[name]!r} of parallel "
                                f"{node.id!r} also writes; branches run at the same time",
                            )
                            continue
                        by_branch[name] = branch.id
                        after[name] = writer
                return after

    visit(root, "root", {})
    return flow


def artifact_issues(root: Node) -> list[ValidationIssue]:
    """Why the run artifacts under `root` cannot be exchanged, in run order: a read with no
    earlier writer (`artifact_unknown`, on the read), and a write that races
    (`artifact_conflict`, on the writer)."""
    return _walk_artifacts(root).issues


def artifact_writers(root: Node) -> dict[str, dict[str, ArtifactWriter]]:
    """For each node under `root` that reads run artifacts, the node that last wrote each of
    them before it (names with no earlier writer left out)."""
    return _walk_artifacts(root).writers


def port_edges(root: Node) -> list[tuple[PortNode, PortNode, str]]:
    """Each place under `root` where one agent or tool node's output is the next one's input, as
    `(producer, consumer, consumer's path)` in run order: consecutive steps of a sequence (nested
    sequences flattened), looking through gates, which pass their input on unchanged. A loop, map,
    parallel or reduce between two steps breaks the edge: its output is not typed. A node that
    reads one run artifact takes it from the artifact's last writer instead (if that is an agent or
    tool node), and one that reads several has no producer."""
    edges: list[tuple[PortNode, PortNode, str]] = []
    writers = artifact_writers(root)

    def steps(node: Node, path: str) -> Iterator[tuple[str, Node]]:
        if isinstance(node, SequenceNode):
            for i, step in enumerate(node.steps):
                yield from steps(step, f"{path}.steps[{i}]")
        else:
            yield path, node

    def visit(node: Node, path: str) -> None:
        previous: PortNode | None = None
        for step_path, step in steps(node, path):
            match step:
                case AgentNode() | ToolNode():
                    if step.reads:
                        read = writers.get(step.id, {})
                        source = read.get(step.reads[0]) if len(step.reads) == 1 else None
                        if isinstance(source, AgentNode | ToolNode):
                            edges.append((source, step, step_path))
                    elif previous is not None:
                        edges.append((previous, step, step_path))
                    previous = step
                case GateNode():
                    pass
                case LoopNode() | MapNode():
                    previous = None
                    visit(step.body, f"{step_path}.body")
                case ParallelNode():
                    previous = None
                    for i, branch in enumerate(step.branches):
                        visit(branch, f"{step_path}.branches[{i}]")
                case ReduceNode() | SequenceNode():
                    previous = None

    visit(root, "root")
    return edges


def port_issues(root: Node) -> list[ValidationIssue]:
    """Why the typed ports under `root` cannot work, in run order: a schema that is not a port's
    schema (`invalid_schema`, on the field), and a consumer whose `input_schema` requires what the
    previous step's `output_schema` does not give (`port_mismatch`, on the consumer). The second
    check is light: required properties must be declared, with the same top-level type."""
    issues: list[ValidationIssue] = []
    broken: set[str] = set()
    for path, node in iter_nodes(root):
        if not isinstance(node, AgentNode | ToolNode):
            continue
        for side, schema in (("input", node.input_schema), ("output", node.output_schema)):
            if schema is None or (problem := schema_problem(schema)) is None:
                continue
            broken.add(node.id)
            issues.append(
                ValidationIssue(
                    code="invalid_schema",
                    path=f"{path}.{side}_schema",
                    node_id=node.id,
                    message=f"{node.type} {node.id!r} at {path}: {side}_schema: {problem}",
                )
            )
    for producer, consumer, path in port_edges(root):
        out, wanted = producer.output_schema, consumer.input_schema
        if out is None or wanted is None or {producer.id, consumer.id} & broken:
            continue
        if why := _port_mismatch(out, wanted, producer.id):
            message = f"{consumer.type} {consumer.id!r} at {path}: input_schema {why}"
            issues.append(
                ValidationIssue(
                    code="port_mismatch", path=path, node_id=consumer.id, message=message
                )
            )
    return issues


def _port_mismatch(
    out: dict[str, JsonValue], wanted: dict[str, JsonValue], producer: str
) -> str | None:
    given = _properties(out)
    expected = _properties(wanted)
    required = wanted.get("required")
    for name in required if isinstance(required, list) else []:
        if not isinstance(name, str):
            continue
        if name not in given:
            return f"requires {name!r}, which the output_schema of {producer!r} does not declare"
        has, needs = _types(given[name]), _types(expected.get(name))
        if "number" in needs:
            needs.add("integer")
        if has and needs and not has & needs:
            return (
                f"wants {name!r} as {' or '.join(sorted(needs))}, but the output_schema of "
                f"{producer!r} gives {' or '.join(sorted(has))}"
            )
    return None


def _properties(schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    properties = schema.get("properties")
    return properties if isinstance(properties, dict) else {}


def _types(schema: JsonValue) -> set[str]:
    """A property schema's top-level `type`s; empty when it does not say."""
    if not isinstance(schema, dict):
        return set()
    match schema.get("type"):
        case str() as one:
            return {one}
        case list() as many:
            return {t for t in many if isinstance(t, str)}
        case _:
            return set()


def structure_issues(root: Node) -> list[ValidationIssue]:
    """Why the spec under `root` cannot run anywhere, in run order: duplicate node ids, the loop,
    map and parallel rules, references to other nodes, a gate before every publisher, the rules
    for creating the repo, typed ports and run artifacts."""
    issues = duplicate_id_issues(root) + loop_issues(root) + map_issues(root)
    issues += parallel_issues(root)
    issues += publish_gate_issues(root) + create_repo_issues(root)
    issues += port_issues(root) + artifact_issues(root)
    return in_run_order(root, issues)


def in_run_order(root: Node, issues: list[ValidationIssue]) -> list[ValidationIssue]:
    """`issues` sorted by where their node runs under `root` (depth first); an issue on a node's
    field (`root.steps[1].output_schema`) sorts with its node. The sort is stable, and issues on
    no node come first."""
    order = {path: i for i, (path, _) in enumerate(iter_nodes(root))}

    def key(issue: ValidationIssue) -> int:
        return order.get(issue.path, order.get(issue.path.rpartition(".")[0], -1))

    return sorted(issues, key=key)


def writer_node_ids(root: Node, write_tools: Collection[str] = WRITE_TOOLS) -> set[str]:
    """The ids of the nodes under `root` that may call one of `write_tools` (each gets its own
    worktree and branch)."""
    return {
        node.id
        for _, node in iter_nodes(root)
        if any(tool in write_tools for tool in node_tools(node))
    }


class WorkflowSpec(_Base):
    """A versioned workflow document with a single root node."""

    spec_version: Literal["0"]
    id: NodeId
    name: NonEmptyStr
    description: str | None = None
    root: Node

    @model_validator(mode="after")
    def _can_run(self) -> Self:
        if issues := structure_issues(self.root):
            raise ValueError("; ".join(messages(issues)))
        return self
