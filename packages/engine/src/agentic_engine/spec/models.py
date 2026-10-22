"""Workflow spec v0: the document the canvas, Architect, monitor and engine share.

New primitives are added as members of the `Node` union; existing specs keep validating.
"""

from collections.abc import Collection, Iterator
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

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


Node = Annotated[AgentNode | ToolNode | GateNode | SequenceNode, Field(discriminator="type")]


def iter_nodes(node: Node, path: str = "root") -> Iterator[tuple[str, Node]]:
    """Yield `(path, node)` for `node` and all its descendants, depth first.

    Paths use the JSON field names, e.g. `root.steps[1].steps[0]`.
    """
    yield path, node
    if isinstance(node, SequenceNode):
        for i, step in enumerate(node.steps):
            yield from iter_nodes(step, f"{path}.steps[{i}]")


def node_tools(node: Node) -> list[str]:
    """The platform tools `node` itself may call: an agent's `tools`, a tool node's `tool`."""
    match node:
        case AgentNode():
            return list(node.tools)
        case ToolNode():
            return [node.tool]
        case GateNode() | SequenceNode():
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
        if isinstance(node, SequenceNode):
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
    def _publish_after_gate(self) -> Self:
        if errors := publish_gate_errors(self.root):
            raise ValueError("; ".join(errors))
        return self
