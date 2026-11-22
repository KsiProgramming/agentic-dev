"""One run on two providers (8.3): which runtime each agent gets, when each is opened, and what a
resume keeps."""

from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest

from agentic_engine.events import InMemoryEventSink
from agentic_engine.graph import run_workflow
from agentic_engine.providers import resolve_providers
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import (
    AgentEvent,
    AgentRequest,
    AgentRuntime,
    Cancelled,
    Completed,
    CopilotRuntime,
    Failed,
    Provider,
)
from agentic_runtime.copilot import AssistantMessage, SessionIdle, UsageReport
from agentic_runtime.copilot_fake import FakeCopilotConnector
from agentic_runtime.fake import FakeRuntime
from agentic_store import StoredRun
from agentic_worker.errors import RunSetupError
from agentic_worker.providers import ProviderRouter, run_providers

TOKEN = "gho_router_token_0001"


def agent(node_id: str, **extra: Any) -> dict[str, Any]:
    return {"type": "agent", "id": node_id, "role": "Dev", "instructions": "Work.", **extra}


def spec_of(*steps: dict[str, Any], **extra: Any) -> WorkflowSpec:
    root = {"type": "sequence", "id": "seq", "steps": list(steps)}
    return parse_spec({"spec_version": "0", "id": "w", "name": "W", "root": root, **extra})


class Openings:
    """The runtimes a router opened, and how often each was opened and closed."""

    def __init__(self) -> None:
        self.runtimes: dict[Provider, AgentRuntime] = {}
        self.opened: list[Provider] = []
        self.closed: list[Provider] = []

    def opener(self, provider: Provider, runtime: AgentRuntime, *, fail: str | None = None) -> Any:
        @asynccontextmanager
        async def open_it() -> AsyncGenerator[AgentRuntime]:
            if fail is not None:
                raise RunSetupError(fail)
            self.opened.append(provider)
            self.runtimes[provider] = runtime
            try:
                yield runtime
            finally:
                self.closed.append(provider)

        return open_it


async def collect(runtime: AgentRuntime, request: AgentRequest) -> list[AgentEvent]:
    return [event async for event in runtime.start(request)]


def request(provider: Provider, node_id: str = "n") -> AgentRequest:
    return AgentRequest(node_id=node_id, role="r", instructions="i", provider=provider)


async def test_each_request_goes_to_its_providers_runtime_and_each_opens_once() -> None:
    claude, copilot = FakeRuntime(), FakeRuntime()
    seen = Openings()
    async with AsyncExitStack() as stack:
        router = ProviderRouter(
            {"claude": seen.opener("claude", claude), "copilot": seen.opener("copilot", copilot)},
            stack,
        )
        assert seen.opened == []  # nothing is opened until a request asks

        await collect(router, request("copilot", "review"))
        await collect(router, request("claude", "build"))
        await collect(router, request("copilot", "review_again"))
        await collect(router, request("claude", "build_again"))

        assert seen.opened == ["copilot", "claude"]
        assert seen.closed == []  # held until the attempt ends
    assert sorted(seen.closed) == ["claude", "copilot"]
    assert [r.node_id for r in claude.requests] == ["build", "build_again"]
    assert [r.node_id for r in copilot.requests] == ["review", "review_again"]


async def test_a_claude_only_run_never_opens_copilot() -> None:
    seen = Openings()
    async with AsyncExitStack() as stack:
        router = ProviderRouter(
            {
                "claude": seen.opener("claude", FakeRuntime()),
                "copilot": seen.opener("copilot", FakeRuntime(), fail="would read a token"),
            },
            stack,
        )

        events = await collect(router, request("claude"))

    assert isinstance(events[-1], Completed)
    assert seen.opened == ["claude"]


async def test_two_agents_asking_at_once_open_a_provider_once() -> None:
    import asyncio

    seen = Openings()
    async with AsyncExitStack() as stack:
        router = ProviderRouter({"claude": seen.opener("claude", FakeRuntime())} | {}, stack)  # pyright: ignore[reportArgumentType]

        await asyncio.gather(*(collect(router, request("claude", f"n{i}")) for i in range(5)))

    assert seen.opened == ["claude"]


async def test_a_provider_that_cannot_open_fails_the_agent_that_asked_with_a_safe_message() -> None:
    seen = Openings()
    message = "copilot_needs_attention: ada's GitHub connection needs attention"
    async with AsyncExitStack() as stack:
        router = ProviderRouter(
            {
                "claude": seen.opener("claude", FakeRuntime()),
                "copilot": seen.opener("copilot", FakeRuntime(), fail=message),
            },
            stack,
        )

        events = await collect(router, request("copilot"))

        assert events == [Failed(error=message)]
        assert seen.opened == []


async def test_a_cancel_before_the_runtime_opens_ends_the_agent_cancelled() -> None:
    seen = Openings()
    async with AsyncExitStack() as stack:
        router = ProviderRouter({"claude": seen.opener("claude", FakeRuntime())} | {}, stack)  # pyright: ignore[reportArgumentType]
        run = router.start(request("claude"))

        run.cancel()

        assert [e async for e in run] == [Cancelled()]


async def test_a_cancel_reaches_the_running_agent() -> None:
    runtime = FakeRuntime()
    async with AsyncExitStack() as stack:
        seen = Openings()
        router = ProviderRouter({"claude": seen.opener("claude", runtime)} | {}, stack)  # pyright: ignore[reportArgumentType]
        run = router.start(request("claude"))
        iterator = run.__aiter__()

        first = await anext(iterator)
        run.cancel()
        rest = [event async for event in iterator]

    assert first is not None
    assert rest  # the stream still ends with its terminal event


async def test_a_mixed_workflow_sends_each_node_to_its_providers_runtime() -> None:
    """Claude builds and Copilot reviews: the two runtimes see only their own nodes."""
    spec = spec_of(agent("builder"), agent("reviewer", provider="copilot", model="gpt-5"))
    claude = FakeRuntime()
    connector = FakeCopilotConnector(
        [
            UsageReport(model="gpt-5", input_tokens=3, output_tokens=2, nano_aiu=500_000_000),
            AssistantMessage("looks fine"),
            SessionIdle(),
        ]
    )
    copilot = CopilotRuntime(connector, secrets=[TOKEN])
    seen = Openings()
    sink = InMemoryEventSink()
    async with AsyncExitStack() as stack:
        router = ProviderRouter(
            {"claude": seen.opener("claude", claude), "copilot": seen.opener("copilot", copilot)},
            stack,
        )

        result = await run_workflow(
            spec, router, "go", sink=sink, providers=resolve_providers(spec)
        )

    assert result.status == "completed"
    assert seen.opened == ["claude", "copilot"]
    assert [(r.node_id, r.provider) for r in claude.requests] == [("builder", "claude")]
    assert len(connector.sessions) == 1  # the reviewer, on Copilot
    usage = [e for e in sink.events if e.type == "usage" and e.node_id == "reviewer"]
    assert [u.payload["ai_credits"] for u in usage] == [0.5]
    assert [u.payload["estimated_usd"] for u in usage] == [0.005]
    assert TOKEN not in str([e.payload for e in sink.events])


def a_run(spec: WorkflowSpec, **kwargs: Any) -> StoredRun:
    return StoredRun(id=uuid4(), status="queued", spec=spec, input="", **kwargs)


def test_a_run_uses_the_providers_it_stored_not_the_workspace_default_of_now() -> None:
    spec = spec_of(agent("a"), agent("b"))
    stored = resolve_providers(spec, workspace_default="claude")  # when it was created

    run = a_run(spec, resolved=stored, provider="claude", providers=("claude",))

    assert run_providers(run) is stored
    assert run_providers(run).providers == ["claude"]


def test_a_run_from_before_8_3_resolves_from_the_provider_it_was_started_on() -> None:
    spec = spec_of(agent("a"), agent("b", provider="claude"))

    on_claude = run_providers(a_run(spec))
    on_copilot = run_providers(a_run(spec, provider="copilot"))
    with_connection = run_providers(a_run(spec, copilot_connection_id=uuid4()))

    assert on_claude.providers == ["claude"]
    assert [(n, r.provider) for n, r in on_copilot.nodes.items()] == [
        ("a", "copilot"),
        ("b", "claude"),
    ]
    assert with_connection.on("copilot") == ["a"]  # 8.2: a connection alone is Copilot


@pytest.mark.parametrize(("attempt", "opened"), [(0, ["claude"]), (1, ["claude"]), (2, [])])
async def test_a_first_attempt_opens_what_the_run_resolved_to_and_a_resume_waits_to_be_asked(
    attempt: int, opened: list[str]
) -> None:
    from agentic_worker.main import WorkerSettings, run_runtimes

    runtimes = run_runtimes(WorkerSettings(), None, None)  # pyright: ignore[reportArgumentType]
    run = a_run(spec_of(agent("a")), attempt=attempt)

    async with runtimes(run, None) as router:
        assert isinstance(router, ProviderRouter)
        assert router.opened == opened
