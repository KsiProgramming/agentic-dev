"""Workflow spec v0: the document the canvas, Architect, monitor and engine share.

New primitives are added as members of the `Node` union; existing specs keep validating.
"""

from collections.abc import Callable, Collection, Iterator
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from agentic_engine.expr import ExpressionError, compile_condition, compile_list
from agentic_engine.policy import PLATFORM_POLICY, Policy, PolicyLimit

NodeId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,62}$")]
"""Slug used in branch names (`agent/<run>/<node>`), so it must be path- and ref-safe."""

NonEmptyStr = Annotated[str, Field(min_length=1)]


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


class ToolNode(_Base):
    """One call of a platform tool with fixed arguments; no model is involved. Its output is the
    next node's input, and an error result fails the node."""

    type: Literal["tool"]
    id: NodeId
    tool: NonEmptyStr = Field(description="The platform tool to call, e.g. `repo.list_files`.")
    args: dict[str, JsonValue] = Field(
        default_factory=dict[str, JsonValue], description="The tool's arguments."
    )


class GateNode(_Base):
    """A human decision point: the run pauses here until someone approves or rejects. Its input
    (the previous node's output) is shown to the approver and passes through unchanged."""

    type: Literal["gate"]
    id: NodeId
    title: NonEmptyStr = Field(description="What the approver is asked to decide.")
    prompt: str | None = Field(
        default=None, description="More guidance for the approver, shown with the input."
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

    @model_validator(mode="after")
    def _strategy_fields(self) -> Self:
        if self.strategy == "agent" and self.agent is None:
            raise ValueError("the agent strategy needs `agent`")
        if self.strategy != "agent" and self.agent is not None:
            raise ValueError("`agent` is only used by the agent strategy")
        if self.strategy != "concat" and self.separator is not None:
            raise ValueError("`separator` is only used by the concat strategy")
        return self


Node = Annotated[
    AgentNode | ToolNode | GateNode | SequenceNode | LoopNode | MapNode | ReduceNode,
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
        case _:
            pass


def node_tools(node: Node) -> list[str]:
    """The platform tools `node` itself may call: an agent's `tools`, a tool node's `tool`."""
    match node:
        case AgentNode():
            return list(node.tools)
        case ToolNode():
            return [node.tool]
        case GateNode() | SequenceNode() | LoopNode() | MapNode() | ReduceNode():
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

PLATFORM_TOOLS = READ_TOOLS | WRITE_TOOLS | PUBLISH_TOOLS | CREATE_TOOLS
"""Every tool a node may name. The tool servers register exactly these (checked in tests)."""

type IssueCode = Literal[
    "schema",
    "id_mismatch",
    "duplicate_node_id",
    "invalid_expression",
    "not_allowed_in_loop",
    "not_allowed_in_map",
    "reference",
    "publish_not_tool_node",
    "publish_without_gate",
    "create_not_tool_node",
    "create_without_gate",
    "create_not_first",
    "unknown_tool",
    "policy_limit",
    "budget_unpriced_model",
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
        if isinstance(node, SequenceNode | LoopNode | MapNode):
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


def _uses_repo(node: Node) -> bool:
    return any(tool.startswith(("repo.", "github.")) for tool in node_tools(node))


def loop_issues(root: Node) -> list[ValidationIssue]:
    """Why the loops under `root` cannot run, in run order (depth first); empty if they can. A
    loop's `until` must be a valid condition, and its body must not hold a gate, a writer, a
    publisher, another loop or a map: the issue is on that node, which is the one to move."""
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
    `max_concurrency` within `agents_alive`, and loops and maps must not nest deeper than
    `max_depth`. Agents spawned and wall time are only known at runtime, where the engine checks
    them."""
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
            case _:
                pass
        match node:
            case LoopNode() | MapNode():
                if depth + 1 > policy.max_depth:
                    why = (
                        f"nesting depth {depth + 1} is above the workspace limit of "
                        f"{policy.max_depth}"
                    )
                    over(node, path, "max_depth", policy.max_depth, depth + 1, why)
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


def structure_issues(root: Node) -> list[ValidationIssue]:
    """Why the spec under `root` cannot run anywhere, in run order: duplicate node ids, the loop
    and map rules, references to other nodes, a gate before every publisher, and the rules for
    creating the repo."""
    issues = duplicate_id_issues(root) + loop_issues(root) + map_issues(root)
    issues += publish_gate_issues(root) + create_repo_issues(root)
    return in_run_order(root, issues)


def in_run_order(root: Node, issues: list[ValidationIssue]) -> list[ValidationIssue]:
    """`issues` sorted by where their node runs under `root` (depth first). The sort is stable,
    and issues on no node come first."""
    order = {path: i for i, (path, _) in enumerate(iter_nodes(root))}
    return sorted(issues, key=lambda issue: order.get(issue.path, -1))


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
