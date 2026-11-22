"""Which provider and model each agent of a run uses (8.3).

A run's providers are worked out once, when it is created, and stored on it: a resume after the
workspace's default changed must not move a half-done run to another provider (as the frozen
policy, 3.2). The order, most specific first: the node's own `provider`, the run's override (the
New run sheet's choice), the workflow's `provider`, the workspace's default, Claude.

A node's `model` belongs to the provider it was written for, its explicit `provider` or else
Claude: on any other provider the node gets that provider's default (`None`; the worker fills a
Copilot node's from the workspace's `copilot_model`). So one workflow runs on either provider
unchanged.

A run a trigger started (Jira, GitHub) stays on Claude whatever the nodes ask for (decisions log,
8.1): every node resolves to Claude and the ones that wanted Copilot are listed in `fallback`.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from pydantic import JsonValue

from agentic_engine.spec.models import (
    AgentNode,
    Node,
    OrchestratorNode,
    ReduceNode,
    RouterNode,
    ValidationIssue,
    WorkflowSpec,
    iter_nodes,
)
from agentic_runtime.request import Provider

DEFAULT_PROVIDER: Provider = "claude"
"""The provider when nothing names one."""


@dataclass(frozen=True)
class ResolvedNode:
    """The provider and model one agent-like node runs on. `model` is `None` for the provider's
    default."""

    provider: Provider
    model: str | None


@dataclass(frozen=True)
class ResolvedProviders:
    """What `resolve_providers` decided: each agent-like node's `ResolvedNode` by node id (`nodes`),
    the run's default (`default`), the providers its nodes use (`providers`, in a fixed order; the
    default when it has no agent), and for a triggered run the nodes that asked for Copilot and
    stay on Claude (`fallback`). `paths` says where each node is, for validation issues."""

    nodes: dict[str, ResolvedNode]
    default: Provider
    providers: list[Provider]
    fallback: list[str] = field(default_factory=list[str])
    paths: dict[str, str] = field(default_factory=dict[str, str])

    def of(self, node_id: str) -> ResolvedNode | None:
        return self.nodes.get(node_id)

    def to_json(self) -> dict[str, JsonValue]:
        """What a run stores (`runs.provider_map`): the nodes, the default and the fallback list.
        Paths are left out; they are only for validation."""
        nodes: dict[str, JsonValue] = {
            node_id: {"provider": n.provider, "model": n.model} for node_id, n in self.nodes.items()
        }
        fallback: list[JsonValue] = [*self.fallback]
        return {"default": self.default, "nodes": nodes, "fallback": fallback}

    @classmethod
    def from_json(cls, stored: Mapping[str, JsonValue]) -> "ResolvedProviders":
        """The resolution `to_json` stored."""
        raw = cast(Mapping[str, Mapping[str, str | None]], stored.get("nodes") or {})
        nodes = {
            node_id: ResolvedNode(cast(Provider, n["provider"]), n.get("model"))
            for node_id, n in raw.items()
        }
        default = cast(Provider, stored.get("default") or DEFAULT_PROVIDER)
        used = {n.provider for n in nodes.values()} or {default}
        order: tuple[Provider, ...] = ("claude", "copilot")
        fallback = [str(f) for f in cast(list[JsonValue], stored.get("fallback") or [])]
        return cls(nodes, default, [p for p in order if p in used], fallback)

    def on(self, provider: Provider) -> list[str]:
        """The ids of the nodes that run on `provider`, in run order."""
        return [node_id for node_id, node in self.nodes.items() if node.provider == provider]


def agent_settings(node: Node) -> tuple[Provider | None, str | None] | None:
    """The `provider` and `model` a node writes for the agent it runs, or `None` when it runs no
    agent: an agent, a reduce with an agent, a router with a classifier, an orchestrator's hub."""
    match node:
        case AgentNode():
            return node.provider, node.model
        case ReduceNode() if node.agent is not None:
            return node.agent.provider, node.agent.model
        case RouterNode() if node.classifier is not None:
            return node.classifier.provider, node.classifier.model
        case OrchestratorNode():
            return node.hub.provider, node.hub.model
        case _:
            return None


def resolve_providers(
    spec: WorkflowSpec,
    *,
    run_override: Provider | None = None,
    workspace_default: Provider | None = None,
    triggered: bool = False,
) -> ResolvedProviders:
    """The provider and model of every agent-like node under `spec.root` (expanded: a subflow's or
    a composite's nodes count, as the validator walks them), with the run's default.

    `run_override` is the run's own choice, `workspace_default` the workspace's, and `triggered`
    says a trigger started the run, which keeps every node on Claude."""
    return resolve_root(
        spec.root,
        spec.provider,
        run_override=run_override,
        workspace_default=workspace_default,
        triggered=triggered,
    )


def resolve_root(
    root: Node,
    workflow_provider: Provider | None,
    *,
    run_override: Provider | None = None,
    workspace_default: Provider | None = None,
    triggered: bool = False,
) -> ResolvedProviders:
    """`resolve_providers` for the expanded `root` of a workflow whose own `provider` is
    `workflow_provider` (what validation has, before the document is a `WorkflowSpec`)."""
    inherited: Provider = run_override or workflow_provider or workspace_default or DEFAULT_PROVIDER
    default: Provider = DEFAULT_PROVIDER if triggered else inherited
    nodes: dict[str, ResolvedNode] = {}
    paths: dict[str, str] = {}
    fallback: list[str] = []
    for path, node in iter_nodes(root):
        if (settings := agent_settings(node)) is None:
            continue
        own, model = settings
        wanted: Provider = own or inherited
        provider: Provider = DEFAULT_PROVIDER if triggered else wanted
        if triggered and wanted != DEFAULT_PROVIDER:
            fallback.append(node.id)
        written_for: Provider = own or DEFAULT_PROVIDER
        nodes[node.id] = ResolvedNode(provider, model if provider == written_for else None)
        paths[node.id] = path
    used = {node.provider for node in nodes.values()} or {default}
    order: tuple[Provider, ...] = ("claude", "copilot")
    return ResolvedProviders(nodes, default, [p for p in order if p in used], fallback, paths)


def provider_gaps(
    resolved: ResolvedProviders, *, has_copilot_connection: bool
) -> list[ValidationIssue]:
    """Why the run cannot use the providers it resolved to, one issue per node (8.3).

    `copilot_connection_required`: a node runs on Copilot and the person has no usable personal
    connection (8.2). The one place that knows it, so `validate_workflow`, the canvas and
    `POST /runs` give the same answer."""
    if has_copilot_connection:
        return []
    return [
        ValidationIssue(
            code="copilot_connection_required",
            path=resolved.paths.get(node_id, ""),
            node_id=node_id,
            message=f"node {node_id!r} runs on Copilot, which needs a personal GitHub connection "
            "with a Copilot subscription; connect one, or run it on Claude",
        )
        for node_id in resolved.on("copilot")
    ]
