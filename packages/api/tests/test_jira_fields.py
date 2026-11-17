"""Mapping a picked project's Jira fields (7.4), against the fake Atlassian."""

from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api import create_app
from agentic_api.settings import Settings
from agentic_jira import FAKE_AC_FIELD, FAKE_POINTS_FIELD, FakeAtlassian
from agentic_secrets import generate_key_file

pytestmark = pytest.mark.integration

ACME = "fake-cloud-acme"
LABS = "fake-cloud-labs"
AC_TEXT = "customfield_10101"
WEB_OWN = "customfield_10300"
"""The WEB project's own (team-managed) paragraph field."""


Sessions = async_sessionmaker[AsyncSession]


@pytest.fixture
def atlassian() -> FakeAtlassian:
    return FakeAtlassian("http://test")


@pytest.fixture
async def client(
    postgres_url: str, redis_url: str, tmp_path: Path, atlassian: FakeAtlassian, sessions: Sessions
) -> AsyncIterator[AsyncClient]:
    """`sessions` migrates the database first."""
    master_key = tmp_path / "master.key"
    generate_key_file(master_key)
    settings = Settings(
        database_url=postgres_url,
        redis_url=redis_url,
        master_key_file=master_key,
        web_base_url="http://web.test/",
    )
    app = create_app(settings)
    app.state.jira = atlassian
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c


@pytest.fixture
async def workspace(client: AsyncClient) -> str:
    created = await client.post("/workspaces", json={"name": f"fields-{uuid4().hex[:8]}"})
    assert created.status_code == 201
    return f"/workspaces/{created.json()['id']}"


async def connect(client: AsyncClient, workspace: str) -> None:
    started = await client.post(f"{workspace}/connections/jira/authorize")
    target = urlsplit(str(started.json()["authorize_url"]))
    back = await client.get(
        target.path, params={k: v[0] for k, v in parse_qs(target.query).items()}
    )
    assert back.status_code == 303 and "jira=connected" in back.headers["location"]


async def picked(client: AsyncClient, workspace: str, *ids: str) -> None:
    await connect(client, workspace)
    saved = await client.put(
        f"{workspace}/jira/sites/{ACME}/projects", json={"project_ids": list(ids)}
    )
    assert saved.status_code == 200


async def test_fields_are_listed_per_role_suggested_first(
    client: AsyncClient, workspace: str
) -> None:
    await picked(client, workspace, "10001", "10004")
    fields = f"{workspace}/jira/sites/{ACME}/fields"

    ac = (await client.get(fields, params={"role": "acceptance_criteria"})).json()
    points = (await client.get(fields, params={"role": "story_points"})).json()
    for_web = (
        await client.get(fields, params={"role": "acceptance_criteria", "project": "web"})
    ).json()

    def rows(listed: dict[str, list[dict[str, object]]]) -> list[tuple[object, ...]]:
        return [(f["id"], f["name"], f["type"], f["suggested"]) for f in listed["fields"]]

    assert rows(ac) == [
        (FAKE_AC_FIELD, "Acceptance criteria", "Paragraph", True),
        (AC_TEXT, "Acceptance notes", "Short text", False),
    ]
    assert rows(points) == [(FAKE_POINTS_FIELD, "Story point estimate", "Number", True)]
    assert [f["id"] for f in for_web["fields"]] == [FAKE_AC_FIELD, AC_TEXT, WEB_OWN]


async def test_listing_fields_needs_a_role_and_a_picked_project(
    client: AsyncClient, workspace: str
) -> None:
    await picked(client, workspace, "10001")
    fields = f"{workspace}/jira/sites/{ACME}/fields"

    no_role = await client.get(fields)
    bad_role = await client.get(fields, params={"role": "priority"})
    not_picked = await client.get(fields, params={"role": "story_points", "project": "OPS"})
    other_site = await client.get(
        f"{workspace}/jira/sites/fake-cloud-nope/fields", params={"role": "story_points"}
    )

    assert no_role.status_code == bad_role.status_code == 422
    assert not_picked.status_code == 422
    assert not_picked.json()["detail"]["code"] == "project_not_allowed"
    assert other_site.status_code == 404


async def test_a_project_maps_its_fields(client: AsyncClient, workspace: str) -> None:
    await picked(client, workspace, "10001", "10004")
    mapping = f"{workspace}/jira/sites/{ACME}/projects/api/fields"

    before = (await client.get(mapping)).json()
    saved = await client.put(
        mapping, json={"acceptance_criteria": FAKE_AC_FIELD, "story_points": FAKE_POINTS_FIELD}
    )
    after = (await client.get(mapping)).json()
    jira = (await client.get(f"{workspace}/jira")).json()

    assert before == {"acceptance_criteria": None, "story_points": None}
    assert saved.status_code == 200
    assert (
        saved.json()
        == after
        == {
            "acceptance_criteria": {"id": FAKE_AC_FIELD, "name": "Acceptance criteria"},
            "story_points": {"id": FAKE_POINTS_FIELD, "name": "Story point estimate"},
        }
    )
    by_key = {p["key"]: p["fields"] for p in jira["sites"][0]["projects"]}
    assert by_key["API"] == after
    assert by_key["WEB"] == {"acceptance_criteria": None, "story_points": None}

    cleared = await client.put(mapping, json={"story_points": FAKE_POINTS_FIELD})
    assert cleared.json()["acceptance_criteria"] is None


async def test_a_team_managed_field_maps_only_in_its_own_project(
    client: AsyncClient, workspace: str
) -> None:
    await picked(client, workspace, "10001", "10004")
    site = f"{workspace}/jira/sites/{ACME}/projects"

    own = await client.put(f"{site}/WEB/fields", json={"acceptance_criteria": WEB_OWN})
    other = await client.put(f"{site}/API/fields", json={"acceptance_criteria": WEB_OWN})

    assert own.status_code == 200
    assert other.status_code == 422
    assert other.json()["detail"]["code"] == "unknown_field"


async def test_a_wrong_mapping_is_refused_and_stores_nothing(
    client: AsyncClient, workspace: str
) -> None:
    await picked(client, workspace, "10001")
    mapping = f"{workspace}/jira/sites/{ACME}/projects/API/fields"
    await client.put(mapping, json={"story_points": FAKE_POINTS_FIELD})

    unknown = await client.put(mapping, json={"acceptance_criteria": "customfield_99999"})
    wrong_type = await client.put(mapping, json={"story_points": "customfield_10200"})
    system = await client.put(mapping, json={"story_points": "timeestimate"})
    swapped = await client.put(
        mapping, json={"acceptance_criteria": FAKE_POINTS_FIELD, "story_points": FAKE_AC_FIELD}
    )
    not_picked = await client.put(
        f"{workspace}/jira/sites/{ACME}/projects/OPS/fields", json={"story_points": None}
    )
    unpicked_site = await client.put(f"{workspace}/jira/sites/{LABS}/projects/LAB/fields", json={})
    extra = await client.put(mapping, json={"priority": "x"})

    assert unknown.json()["detail"]["code"] == "unknown_field"
    assert wrong_type.json()["detail"]["code"] == "field_type_mismatch"
    assert "Story points (Option)" in wrong_type.json()["detail"]["message"]
    assert system.json()["detail"]["code"] == "field_type_mismatch"
    assert swapped.json()["detail"]["code"] == "field_type_mismatch"
    for refused in (not_picked, unpicked_site):
        assert refused.status_code == 422
        assert refused.json()["detail"]["code"] == "project_not_allowed"
    assert extra.status_code == 422
    assert (await client.get(mapping)).json()["story_points"] == {
        "id": FAKE_POINTS_FIELD,
        "name": "Story point estimate",
    }


async def test_a_mapping_goes_with_its_project(client: AsyncClient, workspace: str) -> None:
    await picked(client, workspace, "10001", "10004")
    projects = f"{workspace}/jira/sites/{ACME}/projects"
    await client.put(f"{projects}/API/fields", json={"acceptance_criteria": FAKE_AC_FIELD})
    await client.put(f"{projects}/WEB/fields", json={"story_points": FAKE_POINTS_FIELD})

    await client.put(projects, json={"project_ids": ["10004"]})
    await client.put(projects, json={"project_ids": ["10004", "10001"]})

    assert (await client.get(f"{projects}/API/fields")).json()["acceptance_criteria"] is None
    assert (await client.get(f"{projects}/WEB/fields")).json()["story_points"] is not None
    events = (await client.get(f"{workspace}/audit")).json()["items"]
    mapped = [e["details"] for e in events if e["action"] == "jira.fields_mapped"]
    assert mapped[-1] == {
        "site": "Acme",
        "cloud_id": ACME,
        "project": "API",
        "fields": {"acceptance_criteria": FAKE_AC_FIELD},
    }

    await client.delete(f"{workspace}/connections/jira")
    await connect(client, workspace)
    assert (await client.get(f"{workspace}/jira")).json()["sites"][0]["projects"] == []
