"""Provider selection (8.3): the resolution order, the model rule, the trigger fallback, the gaps
and what each agent's request carries."""

from decimal import Decimal
from typing import Any

import pytest

from agentic_engine.events import InMemoryEventSink
from agentic_engine.graph import run_workflow
from agentic_engine.policy import PLATFORM_POLICY, with_budget
from agentic_engine.providers import provider_gaps, resolve_providers
from agentic_engine.spec import WorkflowSpec, parse_spec, validate_workflow
from agentic_runtime import Provider
from agentic_runtime.fake import FakeRuntime


def agent(node_id: str, **extra: Any) -> dict[str, Any]:
    return {"type": "agent", "id": node_id, "role": "Dev", "instructions": "Work.", **extra}


def spec_of(root: dict[str, Any], **extra: Any) -> WorkflowSpec:
    document = {"spec_version": "0", "id": "w", "name": "W", "root": root, **extra}
    return parse_spec(document)


def sequence(*steps: dict[str, Any]) -> dict[str, Any]:
    return {"type": "sequence", "id": "seq", "steps": list(steps)}


def providers_of(spec: WorkflowSpec, **kwargs: Any) -> dict[str, tuple[str, str | None]]:
    resolved = resolve_providers(spec, **kwargs)
    return {node_id: (n.provider, n.model) for node_id, n in resolved.nodes.items()}


# (node provider, run override, workflow provider, workspace default) → the node's provider
ORDER: list[tuple[Provider | None, Provider | None, Provider | None, Provider | None, Provider]] = [
    (None, None, None, None, "claude"),
    (None, None, None, "copilot", "copilot"),
    (None, None, "claude", "copilot", "claude"),
    (None, None, "copilot", "claude", "copilot"),
    (None, "claude", "copilot", "copilot", "claude"),
    (None, "copilot", "claude", "claude", "copilot"),
    ("claude", "copilot", "copilot", "copilot", "claude"),
    ("copilot", "claude", "claude", "claude", "copilot"),
]


@pytest.mark.parametrize(("node", "override", "workflow", "workspace", "expected"), ORDER)
def test_the_most_specific_setting_wins(
    node: Provider | None,
    override: Provider | None,
    workflow: Provider | None,
    workspace: Provider | None,
    expected: Provider,
) -> None:
    extra: dict[str, Any] = {"provider": node} if node else {}
    spec = spec_of(agent("a", **extra), **({"provider": workflow} if workflow else {}))

    resolved = resolve_providers(spec, run_override=override, workspace_default=workspace)

    assert resolved.nodes["a"].provider == expected
    assert resolved.providers == [expected]
    assert resolved.fallback == []


def test_every_agent_like_node_is_resolved_in_run_order() -> None:
    spec = spec_of(
        sequence(
            agent("first"),
            {
                "type": "orchestrator",
                "id": "team",
                "hub": {"role": "Lead", "instructions": "Plan."},
                "max_workers": 2,
                "max_concurrency": 1,
                "body": agent("worker"),
            },
            {
                "type": "router",
                "id": "pick",
                "classifier": {"instructions": "Choose."},
                "routes": [
                    {"id": "a", "then": agent("on_a")},
                ],
            },
        )
    )

    resolved = resolve_providers(spec, run_override="copilot")

    assert list(resolved.nodes) == ["first", "team", "worker", "pick", "on_a"]
    assert resolved.providers == ["copilot"]
    assert resolved.paths["worker"] == "root.steps[1].body"


def test_a_reduce_agent_is_resolved() -> None:
    spec = spec_of(
        sequence(
            {
                "type": "map",
                "id": "each",
                "over": "[1, 2]",
                "max_concurrency": 1,
                "body": agent("one"),
            },
            {
                "type": "reduce",
                "id": "sum",
                "from": "each",
                "strategy": "agent",
                "agent": {"role": "Sum", "instructions": "Sum up.", "provider": "claude"},
            },
        )
    )

    assert providers_of(spec, run_override="copilot") == {
        "one": ("copilot", None),
        "sum": ("claude", None),
    }


def test_a_mixed_workflow_lists_both_providers() -> None:
    spec = spec_of(sequence(agent("builder"), agent("reviewer", provider="copilot")))

    resolved = resolve_providers(spec)

    assert resolved.providers == ["claude", "copilot"]
    assert resolved.default == "claude"
    assert resolved.on("copilot") == ["reviewer"]


def test_a_workflow_with_no_agent_uses_the_default() -> None:
    spec = spec_of({"type": "tool", "id": "t", "tool": "repo.list_files"}, provider="copilot")

    resolved = resolve_providers(spec)

    assert (resolved.nodes, resolved.providers, resolved.default) == ({}, ["copilot"], "copilot")


MODELS: list[tuple[Provider | None, str, Provider | None, Provider, str | None]] = [
    # node provider, node model, run override, resolved provider, resolved model
    (None, "claude-opus-5-5", None, "claude", "claude-opus-5-5"),
    (None, "claude-opus-5-5", "copilot", "copilot", None),
    ("claude", "claude-opus-5-5", "copilot", "claude", "claude-opus-5-5"),
    ("copilot", "gpt-5", None, "copilot", "gpt-5"),
    ("copilot", "gpt-5", "claude", "copilot", "gpt-5"),
]


@pytest.mark.parametrize(("own", "model", "override", "provider", "expected"), MODELS)
def test_a_model_belongs_to_the_provider_it_was_written_for(
    own: Provider | None,
    model: str,
    override: Provider | None,
    provider: Provider,
    expected: str | None,
) -> None:
    extra: dict[str, Any] = {"model": model, **({"provider": own} if own else {})}
    spec = spec_of(agent("a", **extra))

    assert providers_of(spec, run_override=override) == {"a": (provider, expected)}


def test_a_triggered_run_stays_on_claude_and_lists_what_it_dropped() -> None:
    spec = spec_of(
        sequence(
            agent("plain"),
            agent("pinned", provider="copilot", model="gpt-5"),
            agent("kept", provider="claude", model="claude-opus-5-5"),
        ),
        provider="copilot",
    )

    resolved = resolve_providers(spec, workspace_default="copilot", triggered=True)

    assert {n: (r.provider, r.model) for n, r in resolved.nodes.items()} == {
        "plain": ("claude", None),
        "pinned": ("claude", None),
        "kept": ("claude", "claude-opus-5-5"),
    }
    assert (resolved.default, resolved.providers) == ("claude", ["claude"])
    assert resolved.fallback == ["plain", "pinned"]


def test_a_triggered_run_that_asked_for_nothing_has_no_fallback() -> None:
    resolved = resolve_providers(spec_of(agent("a")), triggered=True)

    assert resolved.fallback == []


def test_a_called_workflows_nodes_are_resolved_too() -> None:
    from agentic_engine.spec.subflows import expand_workflow

    inner = spec_of(agent("inner_agent", provider="copilot"))
    outer = spec_of(
        sequence(
            agent("outer_agent"),
            {"type": "subflow", "id": "call", "workflow": {"id": "w", "version": 1}},
        ),
        id="outer",
    )
    expanded = expand_workflow(
        outer, lambda _id, _v: inner.model_dump(mode="json", exclude_none=True)
    ).spec

    resolved = resolve_providers(expanded, run_override="claude")

    assert providers_of(expanded, run_override="claude") == {
        "outer_agent": ("claude", None),
        "inner_agent": ("copilot", None),
    }
    assert resolved.providers == ["claude", "copilot"]


def test_gaps_name_every_copilot_node_without_a_connection() -> None:
    spec = spec_of(sequence(agent("a"), agent("b", provider="copilot"), agent("c")))
    resolved = resolve_providers(spec, workspace_default="copilot")

    issues = provider_gaps(resolved, has_copilot_connection=False)

    assert [(i.code, i.node_id, i.path) for i in issues] == [
        ("copilot_connection_required", "a", "root.steps[0]"),
        ("copilot_connection_required", "b", "root.steps[1]"),
        ("copilot_connection_required", "c", "root.steps[2]"),
    ]
    assert provider_gaps(resolved, has_copilot_connection=True) == []


def test_no_gap_when_nothing_runs_on_copilot() -> None:
    resolved = resolve_providers(spec_of(agent("a")))

    assert provider_gaps(resolved, has_copilot_connection=False) == []


def checked(document: dict[str, Any], **kwargs: Any) -> list[tuple[str, str | None]]:
    issues = validate_workflow(
        document,
        policy=PLATFORM_POLICY,
        priced=lambda _model: True,
        default_model="claude-sonnet-5-5",
        **kwargs,
    )
    return [(i.code, i.node_id) for i in issues]


def document_of(root: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"spec_version": "0", "id": "w", "name": "W", "root": root, **extra}


def test_validation_reports_the_gap_per_node() -> None:
    document = document_of(sequence(agent("a"), agent("b", provider="copilot")))

    assert checked(document, workspace_default="copilot", has_copilot_connection=False) == [
        ("copilot_connection_required", "a"),
        ("copilot_connection_required", "b"),
    ]
    assert checked(document, has_copilot_connection=False) == [("copilot_connection_required", "b")]


def test_validation_follows_the_workflows_own_provider() -> None:
    document = document_of(agent("a"), provider="copilot")

    assert checked(document, has_copilot_connection=False) == [("copilot_connection_required", "a")]
    assert checked(document, has_copilot_connection=True) == []


def test_validation_without_a_connection_answer_does_not_check_it() -> None:
    document = document_of(agent("a", provider="copilot"))

    assert checked(document) == []


async def test_each_agent_request_carries_its_resolved_provider_and_model() -> None:
    spec = spec_of(
        sequence(
            agent("builder", model="claude-opus-5-5"),
            agent("reviewer", provider="copilot", model="gpt-5"),
            agent("plain"),
        )
    )
    resolved = resolve_providers(spec)
    runtime = FakeRuntime()

    result = await run_workflow(spec, runtime, "go", providers=resolved)

    assert result.status == "completed"
    assert [(r.node_id, r.provider, r.model) for r in runtime.requests] == [
        ("builder", "claude", "claude-opus-5-5"),
        ("reviewer", "copilot", "gpt-5"),
        ("plain", "claude", None),
    ]


async def test_the_stored_map_decides_not_the_spec() -> None:
    spec = spec_of(sequence(agent("a"), agent("b")))
    stored = resolve_providers(spec, run_override="copilot")
    runtime = FakeRuntime()

    await run_workflow(spec, runtime, "go", providers=stored)

    assert [(r.node_id, r.provider) for r in runtime.requests] == [
        ("a", "copilot"),
        ("b", "copilot"),
    ]


async def test_a_run_with_no_stored_map_uses_each_nodes_own_provider() -> None:
    spec = spec_of(sequence(agent("a"), agent("b", provider="copilot", model="gpt-5")))
    runtime = FakeRuntime()

    await run_workflow(spec, runtime, "go")

    assert [(r.node_id, r.provider, r.model) for r in runtime.requests] == [
        ("a", "claude", None),
        ("b", "copilot", "gpt-5"),
    ]


async def test_a_hub_a_classifier_and_a_reduce_agent_carry_their_provider() -> None:
    spec = spec_of(
        sequence(
            {
                "type": "orchestrator",
                "id": "team",
                "hub": {"role": "Lead", "instructions": "Plan."},
                "max_workers": 2,
                "max_concurrency": 1,
                "body": agent("worker"),
            },
            {
                "type": "reduce",
                "id": "sum",
                "from": "team",
                "strategy": "agent",
                "agent": {"role": "Sum", "instructions": "Sum up."},
            },
        )
    )
    runtime = FakeRuntime(fit_schemas=True)

    await run_workflow(
        spec, runtime, "go", providers=resolve_providers(spec, run_override="copilot")
    )

    seen = {r.node_id: r.provider for r in runtime.requests}
    assert seen["team"] == "copilot"
    assert seen["sum"] == "copilot"


async def test_a_triggered_run_says_once_that_it_stayed_on_claude() -> None:
    spec = spec_of(
        sequence(agent("a"), agent("b", provider="claude"), agent("c", provider="copilot"))
    )
    resolved = resolve_providers(spec, workspace_default="copilot", triggered=True)
    sink = InMemoryEventSink()

    result = await run_workflow(spec, FakeRuntime(), "go", sink=sink, providers=resolved)

    assert result.status == "completed"
    fallbacks = [e for e in sink.events if e.type == "provider_fallback"]
    assert [e.payload for e in fallbacks] == [
        {"nodes": ["a", "c"], "reason": "triggered", "provider": "claude"}
    ]
    assert [e.type for e in sink.events[:2]] == ["run_started", "provider_fallback"]


async def test_a_run_that_kept_nothing_off_copilot_says_nothing() -> None:
    spec = spec_of(agent("a"))
    sink = InMemoryEventSink()

    await run_workflow(
        spec, FakeRuntime(), "go", sink=sink, providers=resolve_providers(spec, triggered=True)
    )

    assert not [e for e in sink.events if e.type == "provider_fallback"]


async def test_an_agents_start_event_carries_its_provider_and_model() -> None:
    spec = spec_of(sequence(agent("a", model="claude-opus-5-5"), agent("b", provider="copilot")))
    sink = InMemoryEventSink()

    await run_workflow(spec, FakeRuntime(), "go", sink=sink, providers=resolve_providers(spec))

    started = {e.node_id: e.payload for e in sink.events if e.type == "node_started"}
    assert started["a"] == {"provider": "claude", "model": "claude-opus-5-5"}
    assert started["b"] == {"provider": "copilot", "model": None}


def test_a_budget_does_not_need_a_claude_price_for_a_node_on_copilot() -> None:
    spec = spec_of(sequence(agent("a", model="gpt-5"), agent("b", model="gpt-5")))
    document = spec.model_dump(mode="json", exclude_none=True)
    policy = with_budget(PLATFORM_POLICY, Decimal(1))

    def issues(provider: Provider | None) -> list[str | None]:
        found = validate_workflow(
            {**document, **({"provider": provider} if provider else {})},
            policy=policy,
            priced=lambda model: model.startswith("claude"),
            default_model="claude-sonnet-5-5",
        )
        return [i.node_id for i in found if i.code == "budget_unpriced_model"]

    assert issues(None) == ["a", "b"]  # Claude has no price for "gpt-5"
    assert issues("copilot") == []  # Copilot is priced by credits
