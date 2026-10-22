"""Workflow spec v0: the document the canvas, Architect, monitor and engine share.

New primitives are added as members of the `Node` union; existing specs keep validating.
"""

from collections.abc import Collection, Iterator
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from agentic_engine.expr import ExpressionError, compile_condition, compile_list

NodeId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,62}$")]
"""Slug used in branch names (`agent/<run>/<node>`), so it must be path- and ref-safe."""

NonEmptyStr = Annotated[str, Field(min_length=1)]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


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


MAX_LOOP_ITERATIONS = 5
"""The policy default for loop iterations (tech stack). Phase 3.2 makes it configurable."""


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


MAX_AGENTS_ALIVE = 8
"""The policy default for agents running at once (tech stack); caps `map.max_concurrency`. Phase
2.2 makes it configurable."""

MAX_AGENTS_SPAWNED = 40
"""The policy default for agents a run may spawn (tech stack); caps a map's item count, which is
only known at runtime. Phase 3.2 makes it configurable."""


class MapNode(_Base):
    """Runs its body once per item of the list `over` evaluates to, at most `max_concurrency` at
    a time, and outputs the items' outputs in item order.

    `over` is a CEL expression over `last` (the map's input) and `results` (as for a loop's
    `until`), e.g. `results.list_modules.data.modules`. Each item is its body's input: a string
    as is, any other value as JSON. The body can only hold agent, tool and sequence nodes: the
    others are keyed by node id, which repeats for every item. A map has at most
    `MAX_AGENTS_SPAWNED` items; one that does not complete fails the map."""

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
        extra="forbid", frozen=True, validate_by_name=True, serialize_by_alias=True
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


WRITE_TOOLS = frozenset({"repo.write_file", "repo.commit"})
"""Tools that change a node's own branch in the sandbox: a node naming one is a writer."""

PUBLISH_TOOLS = frozenset({"github.openPR"})
"""Tools that publish a writer's branch outside the sandbox (push, pull request). They are
irreversible, so only a tool node may call one, after a gate that follows the writer."""


def publish_gate_errors(root: Node) -> list[str]:
    """Why the publishing nodes under `root` are not safe to run, in run order (depth first);
    empty if they are. Each must be a tool node whose `from_node` names an earlier writer, with a
    gate between that writer and itself, so a human approves what is published."""
    errors: list[str] = []
    seen: list[Node] = []
    for _, node in iter_nodes(root):
        if isinstance(node, SequenceNode | LoopNode | MapNode):
            continue
        for tool in sorted(PUBLISH_TOOLS.intersection(node_tools(node))):
            if not isinstance(node, ToolNode):
                errors.append(f"node {node.id!r}: {tool} can only be called by a tool node")
                continue
            errors.extend(_publish_errors(node, seen))
        seen.append(node)
    return errors


def _publish_errors(node: "ToolNode", earlier: list[Node]) -> list[str]:
    source = node.args.get("from_node")
    if not isinstance(source, str):
        return [f"node {node.id!r}: {node.tool} needs `from_node`, the writer to publish"]
    ids = [n.id for n in earlier]
    if source not in ids:
        return [f"node {node.id!r}: `from_node` {source!r} is not a node that runs before it"]
    writer = earlier[ids.index(source)]
    if not WRITE_TOOLS.intersection(node_tools(writer)):
        return [f"node {node.id!r}: `from_node` {source!r} is not a writer"]
    between = earlier[ids.index(source) + 1 :]
    if not any(isinstance(n, GateNode) for n in between):
        return [
            f"node {node.id!r}: {node.tool} must come after a gate that follows {source!r}, so "
            "a human approves what is published"
        ]
    return []


def loop_errors(root: Node) -> list[str]:
    """Why the loops under `root` cannot run, in run order (depth first); empty if they can. A
    loop's `until` must be a valid condition, and its body must not hold a gate, a writer, a
    publisher, another loop or a map."""
    errors: list[str] = []
    for path, node in iter_nodes(root):
        if not isinstance(node, LoopNode):
            continue
        try:
            compile_condition(node.until)
        except ExpressionError as e:
            errors.append(f"loop {node.id!r} at {path}: invalid until: {e}")
        for inner_path, inner in iter_nodes(node.body, f"{path}.body"):
            if reason := _not_in_loop(inner):
                errors.append(
                    f"loop {node.id!r} at {path}: {reason} {inner.id!r} at {inner_path} cannot "
                    "be inside a loop yet"
                )
    return errors


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
        case _ if tools & WRITE_TOOLS:
            return "writer"
        case _:
            return None


def map_errors(root: Node) -> list[str]:
    """Why the maps and reduces under `root` cannot run, in run order (depth first); empty if
    they can. A map's `over` must be a valid list expression, and its body must hold only agent,
    tool and sequence nodes, none of them a writer or a publisher. A reduce's `from` must name a
    map that runs before it."""
    errors: list[str] = []
    maps: set[str] = set()
    for path, node in iter_nodes(root):
        match node:
            case MapNode():
                try:
                    compile_list(node.over)
                except ExpressionError as e:
                    errors.append(f"map {node.id!r} at {path}: invalid over: {e}")
                for inner_path, inner in iter_nodes(node.body, f"{path}.body"):
                    if reason := _not_in_map(inner):
                        errors.append(
                            f"map {node.id!r} at {path}: {reason} {inner.id!r} at {inner_path} "
                            "cannot be inside a map yet"
                        )
                maps.add(node.id)
            case ReduceNode() if node.from_ not in maps:
                errors.append(
                    f"reduce {node.id!r} at {path}: `from` {node.from_!r} is not a map that runs "
                    "before it"
                )
            case _:
                pass
    return errors


def _not_in_map(node: Node) -> str | None:
    match node:
        case AgentNode() | ToolNode() | SequenceNode():
            return _not_in_loop(node)
        case _:
            return node.type


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
    def _unique_node_ids(self) -> Self:
        seen: dict[str, str] = {}
        for path, node in iter_nodes(self.root):
            if node.id in seen:
                raise ValueError(
                    f"duplicate node id {node.id!r} at {path} (first used at {seen[node.id]}); "
                    "node ids must be unique"
                )
            seen[node.id] = path
        return self

    @model_validator(mode="after")
    def _loops_can_run(self) -> Self:
        if errors := loop_errors(self.root):
            raise ValueError("; ".join(errors))
        return self

    @model_validator(mode="after")
    def _maps_can_run(self) -> Self:
        if errors := map_errors(self.root):
            raise ValueError("; ".join(errors))
        return self

    @model_validator(mode="after")
    def _publish_after_gate(self) -> Self:
        if errors := publish_gate_errors(self.root):
            raise ValueError("; ".join(errors))
        return self
