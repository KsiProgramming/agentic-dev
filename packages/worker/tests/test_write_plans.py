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
