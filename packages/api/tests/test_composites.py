"""Composites (6.6): `POST /workflows/{id}/publish` makes a version callable by others and the
workflow a composite; its unpublished versions are drafts no run may call. An `extract` op stores
the workflow it makes with the caller's new version, both or neither. `GET
/workflows/{id}/callers` lists who calls a composite, and `GET /node-types?workspace_id=` lists
the workspace's composites in the palette."""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api import create_app
from agentic_api.settings import Settings
from agentic_store import RUN_QUEUE, AuditEvent, Workflow, Workspace

pytestmark = pytest.mark.integration


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
    workspace_id = uuid4()
    async with sessions.begin() as session:
        session.add(Workspace(id=workspace_id, name=f"composites-{workspace_id.hex[:6]}"))
    return workspace_id


def agent(node_id: str, **fields: Any) -> dict[str, Any]:
    return {"type": "agent", "id": node_id, "role": "R", "instructions": "Go.", **fields}


def call(node_id: str, workflow_id: str, version: int) -> dict[str, Any]:
    return {"type": "subflow", "id": node_id, "workflow": {"id": workflow_id, "version": version}}


def workflow(workflow_id: str, *steps: dict[str, Any], name: str | None = None) -> dict[str, Any]:
    root = {"type": "sequence", "id": "main", "steps": list(steps)}
    return {"spec_version": "0", "id": workflow_id, "name": name or workflow_id, "root": root}


class Api:
    def __init__(self, client: AsyncClient, workspace: UUID) -> None:
        self.client = client
        self.params = {"workspace_id": str(workspace)}

    async def create(self, spec: dict[str, Any]) -> dict[str, Any]:
        response = await self.client.post("/workflows", params=self.params, json={"spec": spec})
        assert response.status_code == 201, response.text
        return response.json()

    async def patch(self, workflow_id: str, base: int, *ops: dict[str, Any]) -> Any:
        return await self.client.patch(
            f"/workflows/{workflow_id}",
            params=self.params,
            json={"base_version": base, "ops": list(ops)},
        )

    async def publish(self, workflow_id: str, version: int) -> Any:
        return await self.client.post(
            f"/workflows/{workflow_id}/publish", params=self.params, json={"version": version}
        )

    async def get(self, path: str, **params: Any) -> Any:
        return await self.client.get(path, params={**self.params, **params})


SET_ROLE = {"op": "setParam", "node_id": "x", "path": "role", "value": "Reviewer"}


async def test_publishing_makes_a_composite_and_its_other_versions_drafts(
    client: AsyncClient, workspace: UUID, sessions: async_sessionmaker[AsyncSession]
) -> None:
    api = Api(client, workspace)
    await api.create(workflow("review", agent("x"), name="Review"))

    published = await api.publish("review", 1)
    await api.patch("review", 1, SET_ROLE)

    assert published.status_code == 200, published.text
    body = published.json()
    assert (body["version"], body["published_version"]) == (1, 1)
    assert body["published_at"] is not None
    latest = (await api.get("/workflows/review")).json()
    assert (latest["version"], latest["published_at"], latest["published_version"]) == (2, None, 1)
    versions = (await api.get("/workflows/review/versions")).json()["items"]
    assert [(v["version"], v["published_at"] is not None) for v in versions] == [
        (2, False),
        (1, True),
    ]
    [summary] = (await api.get("/workflows")).json()["items"]
    assert summary["published_version"] == 1
    async with sessions() as session:
        actions = list(
            await session.scalars(
                select(AuditEvent.details).where(
                    AuditEvent.workspace_id == workspace, AuditEvent.action == "workflow.published"
                )
            )
        )
    assert actions == [{"workflow_id": "review", "version": 1}]


async def test_a_version_publishes_once_and_only_when_it_can_run(
    client: AsyncClient, workspace: UUID
) -> None:
    api = Api(client, workspace)
    await api.create(workflow("review", agent("x")))
    await api.create(workflow("broken", agent("x", tools=["nope.tool"])))

    first = await api.publish("review", 1)
    again = await api.publish("review", 1)
    broken = await api.publish("broken", 1)
    unknown = await api.publish("review", 9)
    missing = await api.publish("nope", 1)

    assert first.status_code == 200, first.text
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "already_published"
    assert broken.status_code == 422
    assert broken.json()["detail"]["code"] == "cannot_publish"
    assert [i["code"] for i in broken.json()["detail"]["issues"]] == ["unknown_tool"]
    assert (unknown.status_code, missing.status_code) == (404, 404)
    assert (await api.get("/workflows/broken")).json()["published_version"] is None


async def test_a_publication_never_changes(
    client: AsyncClient, workspace: UUID, sessions: async_sessionmaker[AsyncSession]
) -> None:
    api = Api(client, workspace)
    await api.create(workflow("review", agent("x")))
    await api.publish("review", 1)

    for statement in (
        "UPDATE workflow_publications SET version = 2",
        "DELETE FROM workflow_publications",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            async with sessions.begin() as session:
                await session.execute(text(statement))


async def test_a_composites_draft_is_an_issue_and_cannot_run(
    client: AsyncClient, workspace: UUID, redis_url: str
) -> None:
    api = Api(client, workspace)
    await api.create(workflow("review", agent("x")))
    await api.patch("review", 1, SET_ROLE)
    caller_v2 = workflow("caller", agent("a"), call("check", "review", 2))
    caller_v1 = workflow("caller", agent("a"), call("check", "review", 1))

    # Never published: any version may be called, as in 6.5.
    plain = await client.post(
        "/workflows/caller/validate", json={"workflow": caller_v2, **api.params}
    )
    await api.publish("review", 1)
    draft = await client.post(
        "/workflows/caller/validate", json={"workflow": caller_v2, **api.params}
    )
    refused = await client.post("/runs", json={"workflow": caller_v2, **api.params})
    started = await client.post("/runs", json={"workflow": caller_v1, **api.params})
    if started.status_code == 202:
        redis = Redis.from_url(redis_url)  # pyright: ignore[reportUnknownMemberType]
        try:
            await redis.lrem(RUN_QUEUE, 0, started.json()["run_id"])  # pyright: ignore[reportUnknownMemberType]
        finally:
            await redis.aclose()

    assert plain.json()["valid"] is True
    assert [(i["code"], i["node_id"]) for i in draft.json()["issues"]] == [
        ("subflow_unpublished", "check")
    ]
    assert refused.status_code == 422
    assert [i["code"] for i in refused.json()["detail"]["issues"]] == ["subflow_unpublished"]
    assert started.status_code == 202, started.text


EXTRACT = {
    "op": "extract",
    "node_ids": ["b", "c"],
    "subflow_id": "review_call",
    "workflow": {"id": "review", "name": "Review", "description": "Two checks."},
}


async def test_extract_stores_the_new_workflow_with_the_callers_version(
    client: AsyncClient, workspace: UUID, sessions: async_sessionmaker[AsyncSession]
) -> None:
    api = Api(client, workspace)
    await api.create(workflow("docs", agent("a"), agent("b"), agent("c"), agent("d")))

    response = await api.patch("docs", 1, EXTRACT)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["extracted"] == {"workflow_id": "review", "version": 1}
    assert body["valid"] is True, body["issues"]
    assert [s["id"] for s in body["spec"]["root"]["steps"]] == ["a", "review_call", "d"]
    review = (await api.get("/workflows/review")).json()
    assert (review["version"], review["published_version"]) == (1, None)
    assert review["spec"]["name"] == "Review"
    assert [s["id"] for s in review["spec"]["root"]["steps"]] == ["b", "c"]
    async with sessions() as session:
        audits = list(
            await session.execute(
                select(AuditEvent.action, AuditEvent.details)
                .where(AuditEvent.workspace_id == workspace)
                .order_by(AuditEvent.id)
            )
        )
    assert [(a, d) for a, d in audits][-2:] == [
        (
            "workflow.created",
            {
                "workflow_id": "review",
                "version": 1,
                "extracted_from": {"workflow_id": "docs", "version": 2},
            },
        ),
        (
            "workflow.updated",
            {
                "workflow_id": "docs",
                "version": 2,
                "base_version": 1,
                "op_count": 1,
                "ops": {"extract": 1},
            },
        ),
    ]


async def test_a_refused_extract_stores_nothing(
    client: AsyncClient, workspace: UUID, sessions: async_sessionmaker[AsyncSession]
) -> None:
    api = Api(client, workspace)
    await api.create(workflow("docs", agent("a"), agent("b"), agent("c"), agent("d")))
    await api.create(workflow("taken", agent("t")))

    exists = await api.patch("docs", 1, {**EXTRACT, "workflow": {"id": "taken", "name": "Taken"}})
    later = await api.patch("docs", 1, EXTRACT, {"op": "removeNode", "node_id": "nope"})

    assert exists.status_code == 409
    assert exists.json()["detail"] == {
        "code": "workflow_exists",
        "message": "workflow taken already exists; extract into a workflow with a new id",
        "workflow_id": "taken",
        "latest_version": None,
        "issues": [],
    }
    assert later.status_code == 422
    assert later.json()["detail"]["code"] == "unknown_node"
    async with sessions() as session:
        stored = list(
            await session.scalars(
                select(Workflow.id).where(Workflow.workspace_id == workspace).order_by(Workflow.id)
            )
        )
    assert stored == ["docs", "taken"]
    assert (await api.get("/workflows/docs")).json()["version"] == 1


async def test_callers_are_the_latest_versions_that_call_a_workflow(
    client: AsyncClient, workspace: UUID
) -> None:
    api = Api(client, workspace)
    await api.create(workflow("review", agent("x"), name="Review"))
    await api.patch("review", 1, SET_ROLE)
    await api.create(workflow("zeta", call("r", "review", 1), name="Zeta"))
    await api.create(
        workflow("alpha", call("r1", "review", 1), call("r2", "review", 2), name="Alpha")
    )
    await api.create(workflow("gone", call("r", "review", 1), name="Gone"))
    await api.patch(
        "gone",
        1,
        {"op": "addNode", "node": agent("y"), "at": {"after": "r"}},
        {"op": "removeNode", "node_id": "r"},
    )
    await api.create(workflow("other", agent("o")))

    response = await api.get("/workflows/review/callers")
    unknown = await api.get("/workflows/nope/callers")

    assert response.status_code == 200, response.text
    assert response.json()["items"] == [
        {"workflow_id": "alpha", "name": "Alpha", "latest_version": 1, "calls_version": 2},
        {"workflow_id": "zeta", "name": "Zeta", "latest_version": 1, "calls_version": 1},
    ]
    assert unknown.status_code == 404


async def test_the_palette_lists_the_workspaces_composites_at_their_latest_published_version(
    client: AsyncClient, workspace: UUID
) -> None:
    api = Api(client, workspace)
    spec = {
        **workflow("security-review", agent("x"), name="Security review"),
        "description": "Leaks.",
    }
    await api.create(spec)
    await api.create(workflow("draft-only", agent("x")))
    primitives = (await client.get("/node-types")).json()
    await api.publish("security-review", 1)
    await api.patch("security-review", 1, SET_ROLE)
    await api.publish("security-review", 2)

    listed = (await client.get("/node-types", params=api.params)).json()
    unknown = await client.get("/node-types", params={"workspace_id": str(uuid4())})

    assert listed[: len(primitives)] == primitives
    [entry] = listed[len(primitives) :]
    assert (entry["kind"], entry["label"], entry["category"]) == (
        "subflow",
        "Security review",
        "workspace",
    )
    assert entry["description"] == "Leaks."
    assert entry["composite"] == {"workflow_id": "security-review", "version": 2}
    assert entry["default"]["workflow"] == {"id": "security-review", "version": 2}
    assert all(m["composite"] is None for m in primitives)
    assert unknown.status_code == 404
