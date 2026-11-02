"""`POST /workflows/{id}/validate`: every reason a workflow cannot run in a workspace, without
running it (3.4). Stored workflows (5.1): `POST /workflows`, `GET /workflows/{id}` and its
versions, and `PATCH /workflows/{id}`, where graph operations make a new, immutable version."""

import json
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api import create_app
from agentic_api.settings import Settings
from agentic_engine.policy import PolicyOverrides
from agentic_store import Run, RunEventRow, Workspace, replace_policy_overrides

pytestmark = pytest.mark.integration

SPECS = Path(__file__).resolve().parents[2] / "engine" / "tests" / "fixtures" / "specs"


def spec_json(name: str) -> dict[str, Any]:
    return json.loads((SPECS / name).read_text(encoding="utf-8"))


@pytest.fixture
async def client(
    postgres_url: str, redis_url: str, sessions: async_sessionmaker[AsyncSession]
) -> AsyncIterator[AsyncClient]:
    """`sessions` migrates the database first."""
    app = create_app(Settings(database_url=postgres_url, redis_url=redis_url))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


@pytest.fixture
async def workspace(sessions: async_sessionmaker[AsyncSession]) -> UUID:
    """A workspace of its own, so limits never leak between tests."""
    workspace_id = uuid4()
    async with sessions.begin() as session:
        session.add(Workspace(id=workspace_id, name=f"validate-{workspace_id.hex[:6]}"))
    return workspace_id


async def validate(
    client: AsyncClient, workflow: dict[str, Any], workspace: UUID, **fields: Any
) -> dict[str, Any]:
    response = await client.post(
        f"/workflows/{workflow['id']}/validate",
        json={"workflow": workflow, "workspace_id": str(workspace), **fields},
    )
    assert response.status_code == 200, response.text
    return response.json()


def where(body: dict[str, Any]) -> list[tuple[str, str, str | None]]:
    return [(i["code"], i["path"], i["node_id"]) for i in body["issues"]]


async def test_a_valid_workflow_has_no_issues_and_shows_the_limits(
    client: AsyncClient, workspace: UUID
) -> None:
    body = await validate(client, spec_json("valid/review-loop.json"), workspace)

    assert body["valid"] is True
    assert body["issues"] == []
    assert body["policy"]["loop_iterations"] == 5
    assert body["policy"]["budget_usd"] is None


async def test_an_invalid_workflow_is_answered_with_its_issues(
    client: AsyncClient, workspace: UUID
) -> None:
    body = await validate(client, spec_json("invalid/loop-with-gate.json"), workspace)

    assert body["valid"] is False
    [issue] = body["issues"]
    assert issue == {
        "code": "not_allowed_in_loop",
        "path": "root.body.steps[1]",
        "node_id": "check",
        "message": "loop 'revise' at root: gate 'check' at root.body.steps[1] cannot be inside "
        "a loop yet",
        "limit": None,
        "value": None,
        "observed": None,
    }


async def test_a_spec_off_the_schema_is_answered_not_refused(
    client: AsyncClient, workspace: UUID
) -> None:
    body = await validate(client, spec_json("invalid/gate-missing-title.json"), workspace)

    assert body["valid"] is False
    assert where(body) == [("schema", "root.steps[1].title", "gate")]


async def test_an_id_other_than_the_specs_is_an_issue_next_to_the_others(
    client: AsyncClient, workspace: UUID
) -> None:
    workflow = spec_json("invalid/loop-with-gate.json")
    response = await client.post(
        "/workflows/other/validate", json={"workflow": workflow, "workspace_id": str(workspace)}
    )

    assert response.status_code == 200, response.text
    assert [i["code"] for i in response.json()["issues"]] == ["id_mismatch", "not_allowed_in_loop"]


async def test_the_workspace_limits_apply(
    client: AsyncClient, workspace: UUID, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await replace_policy_overrides(sessions, workspace, PolicyOverrides(loop_iterations=2))

    body = await validate(client, spec_json("valid/review-loop.json"), workspace)

    assert body["valid"] is False
    assert body["policy"]["loop_iterations"] == 2
    [issue] = body["issues"]
    assert issue["code"] == "policy_limit"
    assert (issue["node_id"], issue["limit"], issue["value"], issue["observed"]) == (
        "revise",
        "loop_iterations",
        2,
        3,
    )


async def test_a_gate_waiting_longer_than_the_workspace_allows_is_an_issue(
    client: AsyncClient, workspace: UUID, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await replace_policy_overrides(sessions, workspace, PolicyOverrides(approval_ttl_s=3600))
    spec = spec_json("valid/gate-approval.json")
    spec["root"]["steps"][1]["ttl_s"] = 7200

    body = await validate(client, spec, workspace)

    assert (body["valid"], body["policy"]["approval_ttl_s"]) == (False, 3600)
    [issue] = body["issues"]
    assert (issue["code"], issue["node_id"], issue["limit"], issue["observed"]) == (
        "policy_limit",
        "gate",
        "approval_ttl_s",
        7200,
    )


async def test_a_budget_needs_every_model_priced(client: AsyncClient, workspace: UUID) -> None:
    workflow = spec_json("valid/single-agent.json")
    workflow["root"]["model"] = "no-such-model"

    budgeted = await validate(client, workflow, workspace, budget_usd=1)
    unbudgeted = await validate(client, workflow, workspace)

    assert where(budgeted) == [("budget_unpriced_model", "root", "summarizer")]
    assert budgeted["policy"]["budget_usd"] == 1
    assert unbudgeted["valid"] is True


async def test_the_workspace_default_budget_applies(
    client: AsyncClient, workspace: UUID, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await replace_policy_overrides(sessions, workspace, PolicyOverrides(budget_usd=Decimal("5")))
    workflow = spec_json("valid/single-agent.json")
    workflow["root"]["model"] = "no-such-model"

    body = await validate(client, workflow, workspace)

    assert [i["code"] for i in body["issues"]] == ["budget_unpriced_model"]


async def test_an_unknown_workspace_is_not_found(client: AsyncClient) -> None:
    response = await client.post(
        "/workflows/summarize-readme/validate",
        json={"workflow": spec_json("valid/single-agent.json"), "workspace_id": str(uuid4())},
    )

    assert response.status_code == 404


async def test_a_workflow_that_is_not_an_object_is_refused(client: AsyncClient) -> None:
    response = await client.post("/workflows/x/validate", json={"workflow": [1, 2]})

    assert response.status_code == 422


async def test_validating_writes_nothing(
    client: AsyncClient, workspace: UUID, sessions: async_sessionmaker[AsyncSession]
) -> None:
    async def counts() -> tuple[int, int]:
        async with sessions() as session:
            runs = await session.scalar(select(func.count()).select_from(Run))
            events = await session.scalar(select(func.count()).select_from(RunEventRow))
        return runs or 0, events or 0

    before = await counts()
    await validate(client, spec_json("valid/review-loop.json"), workspace)
    await validate(client, spec_json("invalid/open-pr-without-gate.json"), workspace)

    assert await counts() == before


async def test_typed_ports_are_checked_before_a_run(client: AsyncClient, workspace: UUID) -> None:
    broken = await validate(client, spec_json("invalid/port-not-object.json"), workspace)
    mismatched = await validate(client, spec_json("invalid/port-mismatch-required.json"), workspace)
    typed = await validate(client, spec_json("valid/typed-ports.json"), workspace)

    assert where(broken) == [("invalid_schema", "root.output_schema", "triage")]
    assert where(mismatched) == [("port_mismatch", "root.steps[2]", "report")]
    assert mismatched["issues"][0]["message"] == (
        "agent 'report' at root.steps[2]: input_schema requires 'issues', which the "
        "output_schema of 'triage' does not declare"
    )
    assert typed["valid"] is True


# Stored workflows (5.1)


async def create(client: AsyncClient, workspace: UUID, spec: dict[str, Any]) -> dict[str, Any]:
    response = await client.post(
        "/workflows", params={"workspace_id": str(workspace)}, json={"spec": spec}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def patch(
    client: AsyncClient, workspace: UUID, workflow_id: str, base: int, *ops: dict[str, Any]
) -> Any:
    return await client.patch(
        f"/workflows/{workflow_id}",
        params={"workspace_id": str(workspace)},
        json={"base_version": base, "ops": list(ops)},
    )


SET_PUBLISH = {
    "op": "setParam",
    "node_id": "publish",
    "path": "instructions",
    "value": "Format it as Markdown with a title.",
}


async def test_applying_ops_produces_a_new_immutable_version(
    client: AsyncClient, workspace: UUID
) -> None:
    original = spec_json("valid/review-loop.json")
    first = await create(client, workspace, original)
    assert (first["version"], first["base_version"], first["ops"]) == (1, None, None)
    assert (first["valid"], first["spec"]) == (True, original)

    added = {
        "type": "agent",
        "id": "check",
        "role": "Checker",
        "instructions": "Check the links.",
    }
    response = await patch(
        client,
        workspace,
        "review-loop",
        1,
        {"op": "addNode", "node": added, "at": {"after": "publish"}},
        SET_PUBLISH,
    )

    assert response.status_code == 201, response.text
    second = response.json()
    assert (second["version"], second["base_version"], second["valid"]) == (2, 1, True)
    assert [s["id"] for s in second["spec"]["root"]["steps"]] == ["revise", "publish", "check"]
    assert second["ops"] == [
        {"op": "addNode", "node": added, "at": {"after": "publish"}},
        SET_PUBLISH,
    ]
    params = {"workspace_id": str(workspace)}
    old = await client.get("/workflows/review-loop", params={**params, "version": 1})
    assert old.json()["spec"] == original
    latest = await client.get("/workflows/review-loop", params=params)
    assert latest.json()["version"] == 2
    versions = await client.get("/workflows/review-loop/versions", params=params)
    assert versions.json()["items"] == [
        {"version": 2, "base_version": 1, "created_at": second["created_at"], "op_count": 2},
        {"version": 1, "base_version": None, "created_at": first["created_at"], "op_count": 0},
    ]


async def test_a_version_is_stored_with_its_issues(client: AsyncClient, workspace: UUID) -> None:
    await create(client, workspace, spec_json("valid/review-loop.json"))
    gate = {"type": "gate", "id": "check", "title": "Looks right?"}

    response = await patch(
        client,
        workspace,
        "review-loop",
        1,
        {"op": "addNode", "node": gate, "at": {"after": "review"}},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["valid"] is False
    assert where(body) == [("not_allowed_in_loop", "root.steps[0].body.steps[2]", "check")]


async def test_a_stale_base_version_is_a_conflict(client: AsyncClient, workspace: UUID) -> None:
    await create(client, workspace, spec_json("valid/review-loop.json"))
    assert (await patch(client, workspace, "review-loop", 1, SET_PUBLISH)).status_code == 201

    response = await patch(client, workspace, "review-loop", 1, SET_PUBLISH)

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "version_conflict",
        "message": "version 1 is not the latest (2); apply the ops to the latest version",
        "workflow_id": None,
        "latest_version": 2,
        "issues": [],
    }


async def test_ops_that_cannot_apply_are_refused_with_the_op(
    client: AsyncClient, workspace: UUID
) -> None:
    await create(client, workspace, spec_json("valid/review-loop.json"))

    response = await patch(
        client,
        workspace,
        "review-loop",
        1,
        SET_PUBLISH,
        {"op": "removeNode", "node_id": "main"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "root_node",
        "message": "'main' is the workflow's root; it cannot be removed or moved",
        "op_index": 1,
        "node_id": "main",
    }
    versions = await client.get(
        "/workflows/review-loop/versions", params={"workspace_id": str(workspace)}
    )
    assert [v["version"] for v in versions.json()["items"]] == [1]


async def test_a_malformed_op_is_refused(client: AsyncClient, workspace: UUID) -> None:
    await create(client, workspace, spec_json("valid/review-loop.json"))

    unknown = await patch(client, workspace, "review-loop", 1, {"op": "explode"})
    empty = await patch(client, workspace, "review-loop", 1)

    assert (unknown.status_code, empty.status_code) == (422, 422)


async def test_creating_a_workflow_twice_or_off_the_schema_is_refused(
    client: AsyncClient, workspace: UUID
) -> None:
    await create(client, workspace, spec_json("valid/review-loop.json"))
    params = {"workspace_id": str(workspace)}

    again = await client.post(
        "/workflows", params=params, json={"spec": spec_json("valid/review-loop.json")}
    )
    off = await client.post(
        "/workflows", params=params, json={"spec": spec_json("invalid/gate-missing-title.json")}
    )

    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "workflow_exists"
    assert again.json()["detail"]["workflow_id"] == "review-loop"
    assert off.status_code == 422
    assert off.json()["detail"]["code"] == "schema"
    assert where(off.json()["detail"]) == [("schema", "root.steps[1].title", "gate")]


@pytest.mark.parametrize("template", ["generate-docs", "audit-codebase"])
async def test_a_template_with_its_defaults_is_stored_as_version_1(
    client: AsyncClient, workspace: UUID, template: str
) -> None:
    params = {"workspace_id": str(workspace)}

    response = await client.post("/workflows", params=params, json={"template": {"id": template}})

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["workflow_id"], body["version"]) == (body["spec"]["id"], 1)
    assert not any(value is None for value in body["spec"]["root"].values())
    again = await client.post("/workflows", params=params, json={"template": {"id": template}})
    assert again.status_code == 409
    assert again.json()["detail"]["workflow_id"] == body["workflow_id"]


async def test_a_template_needs_known_id_valid_options_and_no_spec(
    client: AsyncClient, workspace: UUID
) -> None:
    params = {"workspace_id": str(workspace)}

    responses = [
        await client.post("/workflows", params=params, json={"template": {"id": "nope"}}),
        await client.post(
            "/workflows",
            params=params,
            json={"template": {"id": "audit-codebase", "parameters": {"reviewers": 9}}},
        ),
        await client.post(
            "/workflows",
            params=params,
            json={"template": {"id": "generate-docs"}, "spec": spec_json("valid/review-loop.json")},
        ),
        await client.post("/workflows", params=params, json={}),
    ]

    assert [r.status_code for r in responses] == [422] * 4


async def test_unknown_workflows_versions_and_workspaces_are_not_found(
    client: AsyncClient, workspace: UUID
) -> None:
    await create(client, workspace, spec_json("valid/review-loop.json"))
    params = {"workspace_id": str(workspace)}

    responses = [
        await client.get("/workflows/nope", params=params),
        await client.get("/workflows/review-loop", params={**params, "version": 7}),
        await client.get("/workflows/nope/versions", params=params),
        await patch(client, workspace, "nope", 1, SET_PUBLISH),
        await client.get("/workflows/review-loop", params={"workspace_id": str(uuid4())}),
        await patch(client, uuid4(), "review-loop", 1, SET_PUBLISH),
    ]

    assert [r.status_code for r in responses] == [404] * 6
