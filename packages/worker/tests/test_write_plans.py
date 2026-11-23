"""Every outward write has a plan mode (13.8): the tool servers and the engine agree on which
tools write outside the run, and none shows the engine-only arguments in its manifest."""

from typing import cast
from uuid import uuid4

from mcp import Client

from agentic_engine.spec import OUTWARD_WRITE_TOOLS
from agentic_runtime.plans import ENGINE_ONLY_ARGS
from agentic_sandbox import Sandbox
from agentic_tools.github import GithubTarget, build_github_server
from agentic_tools.jira import JiraAccess, build_jira_server
from agentic_tools.testing import FakeGithub


async def test_every_outward_write_has_a_plan_mode() -> None:
    target = GithubTarget(installation_id=1, full_name="acme/hello")
    servers = {
        "github": build_github_server(
            FakeGithub(),
            target,
            cast(Sandbox, object()),
            run_id=uuid4(),
            writers=("writer",),
        ),
        "jira": build_jira_server(cast(JiraAccess, object()), run_id=uuid4()),
    }
    planned: set[str] = set()
    for prefix, server in servers.items():
        async with Client(server) as client:
            for tool in (await client.list_tools()).tools:
                shown = set(tool.input_schema.get("properties", {}))
                if "WritePlan" in str(tool.output_schema):
                    planned.add(f"{prefix}.{tool.name}")
                    assert not shown & ENGINE_ONLY_ARGS, tool.name

    assert planned == OUTWARD_WRITE_TOOLS


# --- the engine on the real Jira tools ------------------------------------------------------------

from collections.abc import Awaitable, Callable, Mapping  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from typing import Any  # noqa: E402
from uuid import UUID  # noqa: E402

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from pydantic import SecretStr  # noqa: E402

from agentic_engine.agent import RunContext  # noqa: E402
from agentic_engine.artifacts import InMemoryArtifactStore  # noqa: E402
from agentic_engine.events import InMemoryEventSink  # noqa: E402
from agentic_engine.gate import GateDecision  # noqa: E402
from agentic_engine.graph import checkpoint_serde, resume_workflow, run_workflow  # noqa: E402
from agentic_engine.spec import parse_spec  # noqa: E402
from agentic_jira import FakeAtlassian  # noqa: E402
from agentic_runtime import Message  # noqa: E402
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime  # noqa: E402
from agentic_store import JiraConnectionInfo, JiraProjectRef, JiraSiteInfo  # noqa: E402
from agentic_tools.jira import open_jira_tools  # noqa: E402

SITE = JiraSiteInfo(
    cloud_id="fake-cloud-acme",
    url="https://acme.atlassian.net",
    name="Acme",
    enabled=True,
    projects=(JiraProjectRef("10001", "API", "Public API"),),
)


class Access:
    """A workspace's Jira over `FakeAtlassian`, as the jira tools need it."""

    def __init__(self) -> None:
        self.platform = FakeAtlassian("http://api.test")
        self.info = JiraConnectionInfo(
            id=uuid4(),
            workspace_id=uuid4(),
            account="Ada",
            scopes=(),
            needs_attention=None,
            sites=(SITE,),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    async def connection(self) -> JiraConnectionInfo | None:
        return self.info

    async def allowed(self, cloud_id: str, project_key: str) -> bool:
        return project_key == "API"

    async def moving(self, cloud_id: str, key: str, status: str, run_id: UUID) -> None:
        pass

    async def field_mappings(self, cloud_id: str) -> Mapping[str, Mapping[str, str]]:
        return {}

    async def call[T](self, request: Callable[[SecretStr], Awaitable[T]]) -> T:
        grant = await self.platform.exchange("fake-code")
        return await request(grant.access_token)


JIRA_SPEC = parse_spec(
    {
        "spec_version": "0",
        "id": "jira",
        "name": "Jira",
        "root": {
            "type": "sequence",
            "id": "main",
            "steps": [
                {"type": "gate", "id": "approve", "title": "Update the issue?"},
                {
                    "type": "tool",
                    "id": "comment",
                    "tool": "jira.comment",
                    "args": {"issue": "API-1", "body": "Done **now**."},
                },
                {
                    "type": "tool",
                    "id": "move",
                    "tool": "jira.transition",
                    "args": {"issue": "API-1", "to": "Done"},
                },
            ],
        },
    }
)


async def test_the_engine_on_the_real_jira_tools_plans_approves_and_refuses_a_stale_plan() -> None:
    access = Access()
    sink = InMemoryEventSink()
    run_id = uuid4()
    runtime = FakeRuntime({"writer": [Message(text="x"), ECHO_USAGE]})

    async with open_jira_tools(access, run_id=run_id, run_url="https://app.test/runs/x") as tools:
        common: dict[str, Any] = {
            "run_id": run_id,
            "sink": sink,
            "checkpointer": InMemorySaver(serde=checkpoint_serde()),
            "tools": tools,
            "artifacts": InMemoryArtifactStore(),
            "context": RunContext(request="API-1"),
        }
        waiting = await run_workflow(JIRA_SPEC, runtime, "API-1", **common)
        assert waiting.status == "waiting"
        shown = next(e for e in sink.events if e.type == "gate_waiting")
        assert shown.payload is not None
        plans = shown.payload["plans"]
        assert [p["summary"] for p in plans] == [  # type: ignore[index, union-attr]
            "Comment on API-1",
            "Move API-1 from To Do to Done",
        ]
        assert access.platform.posted == [] and access.platform.moved == []

        # Someone moves the issue while the gate waits.
        grant = await access.platform.exchange("fake-code")
        await access.platform.transition(grant.access_token, "fake-cloud-acme", "API-1", "11")

        done = await resume_workflow(
            JIRA_SPEC,
            runtime,
            "API-1",
            next_seq=sink.events[-1].seq + 1,
            attempt=2,
            decision=GateDecision(decision="approve"),
            **common,
        )

    assert done.status == "failed"
    failed = next(e for e in sink.events if e.type == "node_failed" and e.node_id == "comment")
    assert failed.payload is not None
    assert str(failed.payload["error"]).startswith("plan_stale: move: ")
    assert access.platform.posted == []  # nothing posted to Jira
