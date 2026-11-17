"""A site's fields and the mapped values of an issue (7.4)."""

from typing import Any

import httpx2
from pydantic import SecretStr

from agentic_jira import (
    FAKE_AC_FIELD,
    FAKE_POINTS_FIELD,
    AtlassianApp,
    AtlassianAppConfig,
    FakeAtlassian,
    JiraField,
    mapped_value,
)

CONFIG = AtlassianAppConfig(
    client_id="client-1",
    client_secret=SecretStr("client-secret-0001"),
    redirect_uri="https://api.example.test/jira/callback",
)
TOKEN = SecretStr("access-token-0001")
SITE = "https://api.atlassian.com/ex/jira/cloud-1/rest/api/3"

# As the real site answered in the 7.4 spike, plus the custom fields the spike's site lacked,
# shaped as Jira documents them (company-managed and team-managed).
FIELDS: list[dict[str, Any]] = [
    {
        "id": "summary",
        "name": "Summary",
        "custom": False,
        "schema": {"type": "string", "system": "summary"},
    },
    {
        "id": "timeestimate",
        "name": "Remaining Estimate",
        "custom": False,
        "schema": {"type": "number", "system": "timeestimate"},
    },
    {
        "id": "customfield_10100",
        "name": "Acceptance criteria",
        "custom": True,
        "schema": {
            "type": "string",
            "custom": "com.atlassian.jira.plugin.system.customfieldtypes:textarea",
            "customId": 10100,
        },
    },
    {
        "id": "customfield_10016",
        "name": "Story point estimate",
        "custom": True,
        "schema": {
            "type": "number",
            "custom": "com.pyxis.greenhopper.jira:jsw-story-points",
            "customId": 10016,
        },
    },
    {
        "id": "customfield_10300",
        "name": "Definition of done",
        "custom": True,
        "schema": {
            "type": "string",
            "custom": "com.atlassian.jira.plugin.system.customfieldtypes:textarea",
        },
        "scope": {"type": "PROJECT", "project": {"id": "10004"}},
    },
    {"id": "", "name": "No id"},
    {"id": "customfield_1", "name": "Rank", "custom": True},
]


def app(handler: Any) -> AtlassianApp:
    return AtlassianApp(CONFIG, transport=httpx2.MockTransport(handler))


async def test_fields_are_read_with_their_type_and_scope() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=FIELDS)

    fields = await app(handler).list_fields(TOKEN, "cloud-1")

    assert str(seen[0].url) == f"{SITE}/field"
    by_id = {f.id: f for f in fields}
    assert "" not in by_id
    assert by_id["customfield_10100"] == JiraField(
        "customfield_10100", "Acceptance criteria", "string", "textarea", True
    )
    assert by_id["customfield_10016"].kind == "jsw-story-points"
    assert by_id["customfield_10300"].project_id == "10004"
    assert by_id["customfield_1"] == JiraField("customfield_1", "Rank", "", "", True)
    assert [f.name for f in fields] == sorted((f.name for f in fields), key=str.lower)


def test_a_field_fits_a_role_by_its_type() -> None:
    paragraph = JiraField("c1", "Acceptance criteria", "string", "textarea", True)
    short = JiraField("c2", "AC", "string", "textfield", True)
    points = JiraField("c3", "Story points", "number", "float", True)
    select = JiraField("c4", "Story points", "option", "select", True)
    color = JiraField("c5", "Issue color", "string", "jsw-issue-color", True)
    system = JiraField("timeestimate", "Remaining Estimate", "number", "", False)
    description = JiraField("description", "Description", "string", "", False)

    assert [f.fits("acceptance_criteria") for f in (paragraph, short, color, description)] == [
        True,
        True,
        False,
        False,
    ]
    assert [f.fits("story_points") for f in (points, select, system, paragraph)] == [
        True,
        False,
        False,
        False,
    ]
    assert paragraph.suggested("acceptance_criteria")
    assert JiraField("c", " Story Point Estimate ", "number", "", True).suggested("story_points")
    assert not short.suggested("acceptance_criteria")
    assert (paragraph.label, short.label, points.label, select.label) == (
        "Paragraph",
        "Short text",
        "Number",
        "Option",
    )


def test_a_team_managed_field_belongs_to_its_project() -> None:
    own = JiraField("c1", "AC", "string", "textarea", True, project_id="10004")
    shared = JiraField("c2", "AC", "string", "textarea", True)

    assert own.in_project("10004") and not own.in_project("10001")
    assert shared.in_project("10001")


def test_mapped_values_are_read_per_role() -> None:
    doc = {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Given a key"}]}],
    }
    assert mapped_value("acceptance_criteria", doc) == "Given a key"
    assert mapped_value("acceptance_criteria", "  plain text  ") == "plain text"
    assert mapped_value("acceptance_criteria", "   ") is None
    assert mapped_value("acceptance_criteria", {"type": "doc", "content": []}) is None
    assert mapped_value("acceptance_criteria", 3) is None
    assert mapped_value("acceptance_criteria", None) is None
    assert mapped_value("story_points", 5) == 5.0
    assert mapped_value("story_points", 0.5) == 0.5
    assert mapped_value("story_points", True) is None
    assert mapped_value("story_points", "5") is None
    assert mapped_value("story_points", None) is None


async def test_an_issue_is_read_with_the_extra_fields_asked_for() -> None:
    seen: list[httpx2.Request] = []
    issue = {
        "id": "1",
        "key": "API-12",
        "fields": {
            "summary": "Rate limit",
            "project": {"key": "API"},
            "customfield_10100": "Given a key",
            "customfield_10016": None,
            "customfield_99": "not asked for",
        },
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if request.url.path.endswith("/comment"):
            return httpx2.Response(200, json={"comments": []})
        return httpx2.Response(200, json=issue)

    found = await app(handler).get_issue(
        TOKEN, "cloud-1", "API-12", extra_fields=("customfield_10100", "customfield_10016")
    )

    asked = seen[0].url.params["fields"].split(",")
    assert asked[-2:] == ["customfield_10016", "customfield_10100"]
    assert "description" in asked
    assert dict(found.extra) == {"customfield_10100": "Given a key"}


async def test_without_extra_fields_an_issue_has_none() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/comment"):
            return httpx2.Response(200, json={"comments": []})
        return httpx2.Response(200, json={"key": "API-1", "fields": {"customfield_10100": "x"}})

    found = await app(handler).get_issue(TOKEN, "cloud-1", "API-1")

    assert dict(found.extra) == {}


async def test_the_fake_lists_fields_and_returns_the_values_asked_for() -> None:
    fake = FakeAtlassian("http://api.test")
    grant = await fake.exchange("fake-code")
    token = grant.access_token

    fields = await fake.list_fields(token, "fake-cloud-acme")
    fitting = [f.id for f in fields if f.fits("acceptance_criteria")]
    issue = await fake.get_issue(
        token, "fake-cloud-acme", "API-1", extra_fields=(FAKE_AC_FIELD, FAKE_POINTS_FIELD)
    )
    bare = await fake.get_issue(token, "fake-cloud-acme", "API-1")

    assert FAKE_AC_FIELD in fitting and "customfield_10201" not in fitting
    assert mapped_value("acceptance_criteria", issue.extra[FAKE_AC_FIELD]) == (
        "- A client over 100 requests a minute **gets 429.**\n- The limit is per API key."
    )
    assert mapped_value("story_points", issue.extra[FAKE_POINTS_FIELD]) == 5.0
    assert issue.components == ("gateway",)
    assert dict(bare.extra) == {}
    assert fake.issue_reads == [("fake-cloud-acme", "API-1"), ("fake-cloud-acme", "API-1")]
