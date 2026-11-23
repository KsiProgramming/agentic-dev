"""The `jira` MCP server (7.2): reads scoped to the picked projects, gated writes, fixed errors."""

import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from mcp import Client
from pydantic import SecretStr

from agentic_jira import FAKE_AC_FIELD, FAKE_POINTS_FIELD, FakeAtlassian, JiraUnauthorizedError
from agentic_runtime.plans import COMPARED, WritePlan, compare
from agentic_store import (
    JiraConnectionInfo,
    JiraNeedsAttentionError,
    JiraProjectRef,
    JiraSiteInfo,
)
from agentic_tools.jira import (
    JIRA_READ_TOOL_NAMES,
    JIRA_WRITE_TOOL_NAMES,
    IssueReadError,
    balanced,
    build_jira_server,
    open_jira_tools,
    read_issue,
)

RUN = UUID("12345678-0000-0000-0000-000000000000")
ACME = JiraSiteInfo(
    cloud_id="fake-cloud-acme",
    url="https://acme.atlassian.net",
    name="Acme",
    enabled=True,
    projects=(
        JiraProjectRef("10001", "API", "Public API"),
        JiraProjectRef("10002", "DOCS", "Documentation"),
    ),
)
LABS = JiraSiteInfo(
    cloud_id="fake-cloud-labs",
    url="https://acme-labs.atlassian.net",
    name="Acme Labs",
    enabled=False,
    projects=(JiraProjectRef("20001", "LAB", "Experiments"),),
)


class Access:
    """A workspace's Jira over `FakeAtlassian`, with the allowlist the store would answer."""

    def __init__(self, *sites: JiraSiteInfo, needs_attention: str | None = None) -> None:
        self.platform = FakeAtlassian("http://api.test")
        self.info: JiraConnectionInfo | None = JiraConnectionInfo(
            id=uuid4(),
            workspace_id=uuid4(),
            account="Ada Example",
            scopes=(),
            needs_attention=needs_attention,
            sites=sites or (ACME, LABS),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.tokens_used: list[str] = []
        self.moves: list[tuple[str, str, str]] = []
        self.mappings: dict[str, dict[str, dict[str, str]]] = {}
        """Field mappings by site, then project key, then role (7.4)."""

    async def connection(self) -> JiraConnectionInfo | None:
        return self.info

    async def allowed(self, cloud_id: str, project_key: str) -> bool:
        if self.info is None or self.info.needs_attention:
            return False
        return any(
            site.cloud_id == cloud_id
            and site.enabled
            and any(p.key == project_key.upper() for p in site.projects)
            for site in self.info.sites
        )

    async def moving(self, cloud_id: str, key: str, status: str, run_id: UUID) -> None:
        self.moves.append((cloud_id, key, status))

    async def field_mappings(self, cloud_id: str) -> Mapping[str, Mapping[str, str]]:
        return self.mappings.get(cloud_id, {})

    async def call[T](self, request: Callable[[SecretStr], Awaitable[T]]) -> T:
        if self.info is not None and self.info.needs_attention:
            raise JiraNeedsAttentionError(self.info.needs_attention)
        grant = await self.platform.exchange("fake-code")
        self.tokens_used.append(grant.access_token.get_secret_value())
        try:
            return await request(grant.access_token)
        except JiraUnauthorizedError:
            raise JiraNeedsAttentionError("unauthorized") from None


async def call(access: Access, tool: str, **args: Any) -> Any:
    server = build_jira_server(access, run_id=RUN, run_url="https://app.test/runs/x")
    async with Client(server) as client:
        result = await client.call_tool(tool, args)
    text = "\n".join(c.text for c in result.content if c.type == "text")
    for token in access.tokens_used:
        assert token not in text
    if result.is_error:
        return "error: " + text
    assert json.loads(text) == result.structured_content
    return result.structured_content


async def test_the_server_offers_exactly_the_jira_tools() -> None:
    async with open_jira_tools(Access(), run_id=RUN) as tools:
        names = {d.name for d in tools.definitions()}

    assert names == JIRA_READ_TOOL_NAMES | JIRA_WRITE_TOOL_NAMES
    assert {"jira.getIssue", "jira.search", "jira.listTransitions"} == JIRA_READ_TOOL_NAMES
    assert {"jira.comment", "jira.transition"} == JIRA_WRITE_TOOL_NAMES


async def test_an_issue_is_read_as_markdown_with_its_comments() -> None:
    issue = await call(Access(), "getIssue", issue="api-1", description="Read it")

    assert issue["key"] == "API-1"
    assert issue["url"] == "https://acme.atlassian.net/browse/API-1"
    assert issue["site"] == "acme.atlassian.net"
    assert issue["project"] == "API"
    assert issue["status"] == "To Do"
    assert "## Acceptance criteria" in issue["description"]
    assert issue["description_truncated"] is False
    assert [c["body"] for c in issue["comments"]] == ["Per API key?"]
    assert issue["comment_count"] == 1


async def test_long_text_is_cut() -> None:
    access = Access()
    issue = access.platform.issues["fake-cloud-acme"]["API-2"]
    access.platform.issues["fake-cloud-acme"]["API-2"] = replace(issue, description="x" * 40_000)

    found = await call(access, "getIssue", issue="API-2")

    assert len(found["description"]) == 32_000
    assert found["description_truncated"] is True


@pytest.mark.parametrize(
    ("issue", "why"),
    [
        ("OPS-1", "project OPS"),  # never picked
        ("DOCS-9", "project OPS"),  # moved from a picked project to OPS
        ("LAB-1", "is not a Jira site"),  # its site is off
    ],
)
async def test_a_project_not_picked_is_refused(issue: str, why: str) -> None:
    site = "acme-labs.atlassian.net" if issue.startswith("LAB") else None
    answer = await call(Access(), "getIssue", issue=issue, **({"site": site} if site else {}))

    assert answer.startswith("error: ")
    assert why in answer
    if issue == "DOCS-9":
        assert "project_not_allowed" in answer


async def test_an_off_list_key_is_refused_before_jira_is_called() -> None:
    access = Access()
    answer = await call(access, "getIssue", issue="OPS-1")

    assert "project_not_allowed" in answer
    assert access.tokens_used == []


async def test_bad_keys_and_missing_issues() -> None:
    assert "issue_invalid" in await call(Access(), "getIssue", issue="../myself")
    assert "issue_not_found" in await call(Access(), "getIssue", issue="API-999")


async def test_sites_are_chosen_or_named() -> None:
    both = Access(ACME, replace(LABS, enabled=True))
    assert "site_required" in await call(both, "getIssue", issue="API-1")
    assert (await call(both, "getIssue", issue="API-1", site="acme.atlassian.net"))["key"] == (
        "API-1"
    )
    assert (await call(both, "getIssue", issue="LAB-1", site="fake-cloud-labs"))["key"] == "LAB-1"
    assert "site_unknown" in await call(both, "getIssue", issue="API-1", site="evil.example")
    assert "site_unknown" in await call(Access(replace(ACME, enabled=False)), "search")


async def test_a_connection_that_is_missing_or_needs_attention_is_refused() -> None:
    gone = Access()
    gone.info = None
    assert "jira_not_connected" in await call(gone, "getIssue", issue="API-1")

    marked = Access(needs_attention="invalid_grant")
    assert "needs_attention" in await call(marked, "getIssue", issue="API-1")


async def test_a_search_is_limited_to_the_picked_projects() -> None:
    access = Access()
    found = await call(
        access, "search", jql='status = "To Do" OR project = OPS', order_by="updated DESC"
    )

    assert found["jql"] == (
        'project in ("API", "DOCS") AND (status = "To Do" OR project = OPS) ORDER BY updated DESC'
    )
    assert {i["project"] for i in found["issues"]} <= {"API", "DOCS"}
    assert found["issues"][0]["url"].startswith("https://acme.atlassian.net/browse/")


async def test_search_results_are_filtered_even_when_jira_returns_more() -> None:
    access = Access()
    access.platform.leak_search = True

    found = await call(access, "search", jql="")

    assert {i["project"] for i in found["issues"]} == {"API", "DOCS"}


@pytest.mark.parametrize(
    "jql",
    [
        "x) OR (project = OPS",
        'summary ~ "open',
        "project = API ORDER BY key",
        "a)",
    ],
)
async def test_a_query_that_could_escape_its_scope_is_refused(jql: str) -> None:
    access = Access()
    answer = await call(access, "search", jql=jql)

    assert "invalid_jql" in answer
    assert access.platform.searches == []


async def test_an_invalid_query_and_order_are_reported() -> None:
    assert "invalid_jql" in await call(Access(), "search", jql="!!")
    assert "invalid_jql" in await call(Access(), "search", order_by="key; DROP")


def test_balanced_ignores_brackets_in_strings() -> None:
    assert balanced('summary ~ "a ) b" AND (x = 1)')
    assert balanced(r'summary ~ "say \"hi\" )"')
    assert not balanced("(a")
    assert not balanced(")(")


async def test_transitions_are_listed() -> None:
    found = await call(Access(), "listTransitions", issue="API-1")

    assert found["status"] == "To Do"
    assert [t["name"] for t in found["transitions"]] == ["Start progress", "Done"]


async def test_a_comment_is_posted_with_the_run_link_once() -> None:
    access = Access()

    posted = await call(access, "comment", issue="API-1", body="The limit is **per key**.")
    again = await call(access, "comment", issue="API-1", body="The limit is **per key**.")

    assert posted["created"] is True
    assert posted["url"].startswith("https://acme.atlassian.net/browse/API-1?focusedCommentId=")
    assert again == posted | {"created": False}
    assert [p.body for p in access.platform.posted] == [
        "The limit is **per key**.\n\n_Posted by agentic-dev run [12345678](https://app.test/runs/x)_"
    ]


async def test_a_comment_on_a_project_not_picked_is_not_posted() -> None:
    access = Access()

    assert "project_not_allowed" in await call(access, "comment", issue="DOCS-9", body="hi")
    assert access.platform.posted == []


async def test_a_transition_moves_the_issue_by_name_id_or_status() -> None:
    access = Access()

    moved = await call(access, "transition", issue="API-1", to="start progress")
    assert moved == {
        "key": "API-1",
        "from_status": "To Do",
        "to_status": "In Progress",
        "changed": True,
    }
    assert (await call(access, "transition", issue="API-1", to="Done"))["to_status"] == "Done"
    assert (await call(access, "transition", issue="API-1", to="done"))["changed"] is False
    assert [m.transition_id for m in access.platform.moved] == ["11", "31"]
    # Each move is recorded before it is made (7.3); "already Done" moves nothing.
    assert access.moves == [
        ("fake-cloud-acme", "API-1", "In Progress"),
        ("fake-cloud-acme", "API-1", "Done"),
    ]


async def test_a_transition_the_workflow_does_not_offer_is_refused() -> None:
    answer = await call(Access(), "transition", issue="API-1", to="Reopen")

    assert "transition_unavailable" in answer
    assert "Start progress, Done" in answer


async def test_unknown_arguments_are_refused() -> None:
    assert (await call(Access(), "getIssue", issue="API-1", jql="x")).startswith("error: ")


async def test_rate_limits_and_outages_are_fixed_errors() -> None:
    access = Access()
    access.platform.unavailable = True

    assert "jira_unavailable" in await call(access, "getIssue", issue="API-1")


AC_TEXT_FIELD = "customfield_10101"
MAPPED = {"acceptance_criteria": FAKE_AC_FIELD, "story_points": FAKE_POINTS_FIELD}
API_AC = "- A client over 100 requests a minute **gets 429.**\n- The limit is per API key."


async def test_an_issue_returns_its_projects_mapped_fields() -> None:
    access = Access()
    access.mappings = {"fake-cloud-acme": {"API": MAPPED}}

    issue = await call(access, "getIssue", issue="API-1")

    assert issue["mapped"] == {
        "acceptance_criteria": API_AC,
        "acceptance_criteria_truncated": False,
        "story_points": 5.0,
    }
    assert issue["components"] == ["gateway"]


async def test_an_unmapped_project_or_an_empty_field_reads_as_null() -> None:
    access = Access()
    unmapped = await call(access, "getIssue", issue="API-1")
    access.mappings = {"fake-cloud-acme": {"API": {"acceptance_criteria": AC_TEXT_FIELD}}}
    empty = await call(access, "getIssue", issue="API-1")
    access.mappings = {"fake-cloud-acme": {"API": {"story_points": "customfield_gone"}}}
    gone = await call(access, "getIssue", issue="API-1")

    nothing = {"acceptance_criteria": None, "acceptance_criteria_truncated": False}
    assert (
        unmapped["mapped"] == empty["mapped"] == gone["mapped"] == nothing | {"story_points": None}
    )


async def test_a_moved_issue_reads_its_new_projects_mapping() -> None:
    ops = JiraProjectRef("10003", "OPS", "Operations")
    access = Access(replace(ACME, projects=(*ACME.projects, ops)))
    access.mappings = {
        "fake-cloud-acme": {
            "DOCS": {"acceptance_criteria": FAKE_AC_FIELD},
            "OPS": {"acceptance_criteria": AC_TEXT_FIELD, "story_points": FAKE_POINTS_FIELD},
        }
    }

    issue = await call(access, "getIssue", issue="DOCS-9")

    assert (issue["key"], issue["project"]) == ("OPS-2", "OPS")
    assert issue["mapped"]["acceptance_criteria"] == "The old server answers 410."
    assert issue["mapped"]["story_points"] == 2.0


async def test_long_acceptance_criteria_are_cut() -> None:
    access = Access()
    access.mappings = {"fake-cloud-acme": {"API": {"acceptance_criteria": AC_TEXT_FIELD}}}
    api1 = access.platform.issues["fake-cloud-acme"]["API-1"]
    access.platform.issues["fake-cloud-acme"]["API-1"] = replace(
        api1, extra={AC_TEXT_FIELD: "x" * 40_000}
    )

    mapped = (await call(access, "getIssue", issue="API-1"))["mapped"]

    assert len(mapped["acceptance_criteria"]) == 32_000
    assert mapped["acceptance_criteria_truncated"] is True


async def test_the_platform_reads_an_issue_as_the_tool_does(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    access = Access()
    access.mappings = {"fake-cloud-acme": {"API": MAPPED}}

    read = await read_issue(access, "API-1")
    tool = await call(access, "getIssue", issue="API-1")

    assert read.model_dump(mode="json") == tool
    assert "100 requests" not in caplog.text, "field content is never logged"


async def test_read_issue_fails_with_the_tools_codes() -> None:
    access = Access()

    with pytest.raises(IssueReadError, match=r"^project_not_allowed: "):
        await read_issue(access, "OPS-1")
    with pytest.raises(IssueReadError, match=r"^issue_not_found: "):
        await read_issue(access, "API-404")
    access.info = None
    with pytest.raises(IssueReadError, match=r"^jira_not_connected: "):
        await read_issue(access, "API-1")


# --- plan mode (13.8) --------------------------------------------------------------------


def plan_of(answer: object) -> WritePlan:
    assert isinstance(answer, dict), answer
    return WritePlan.model_validate(answer)


async def test_a_comment_plan_matches_what_the_real_call_posts() -> None:
    access = Access()

    plan = plan_of(await call(access, "comment", issue="API-1", body="Done **now**.", plan=True))
    assert access.platform.posted == []
    posted = await call(access, "comment", issue="API-1", body="Done **now**.")

    assert plan.action == "comment"
    assert plan.target.label == "API-1"
    assert plan.target.url == "https://acme.atlassian.net/browse/API-1"
    assert plan.body == posted["text"]
    assert plan.body is not None
    assert plan.body.endswith("_Posted by agentic-dev run [12345678](https://app.test/runs/x)_")
    assert compare(plan, posted) == []


async def test_a_comment_plan_says_when_the_run_posted_it_already() -> None:
    access = Access()
    await call(access, "comment", issue="API-1", body="Same.")

    plan = plan_of(await call(access, "comment", issue="API-1", body="Same.", plan=True))

    assert plan.fields["created"] is False
    assert "already" in plan.summary
    assert len(access.platform.posted) == 1


async def test_a_comment_refuses_when_the_issue_is_in_another_project_now() -> None:
    access = Access()

    answer = await call(access, "comment", issue="API-1", body="hi", expect={"project": "DOCS"})

    assert "plan_stale: " in answer
    assert access.platform.posted == []


async def test_a_transition_plan_matches_the_move() -> None:
    access = Access()

    plan = plan_of(await call(access, "transition", issue="API-1", to="Done", plan=True))
    assert access.platform.moved == []
    assert access.moves == []
    moved = await call(access, "transition", issue="API-1", to="Done", expect=plan.expect)

    assert plan.summary == "Move API-1 from To Do to Done"
    assert plan.fields["from_status"] == "To Do"
    assert plan.expect == {"status": "To Do", "transition_id": "31"}
    assert plan.error is None
    assert compare(plan, moved) == []


async def test_a_transition_that_is_not_offered_is_a_plan_with_the_error() -> None:
    plan = plan_of(await call(Access(), "transition", issue="API-1", to="Reopen", plan=True))

    assert plan.error is not None
    assert plan.error.code == "transition_unavailable"
    assert "Start progress, Done" in plan.error.message
    assert plan.fields["offered"] == ["Start progress", "Done"]


async def test_a_transition_to_the_status_it_has_is_a_no_change_plan() -> None:
    access = Access()
    await call(access, "transition", issue="API-1", to="Done")

    plan = plan_of(await call(access, "transition", issue="API-1", to="done", plan=True))

    assert plan.error is None
    assert plan.fields["changed"] is False
    assert "no change" in plan.summary


async def test_a_transition_refuses_when_the_status_changed() -> None:
    access = Access()
    plan = plan_of(await call(access, "transition", issue="API-1", to="Done", plan=True))
    await call(access, "transition", issue="API-1", to="Start progress")

    answer = await call(access, "transition", issue="API-1", to="Done", expect=plan.expect)

    assert "plan_stale: " in answer
    assert "In Progress" in answer
    assert [m.transition_id for m in access.platform.moved] == ["11"]


async def test_a_transition_refuses_when_the_move_is_no_longer_offered() -> None:
    access = Access()

    answer = await call(
        access,
        "transition",
        issue="API-1",
        to="Done",
        expect={"status": "To Do", "transition_id": "99"},
    )

    assert "plan_stale: " in answer
    assert access.platform.moved == []


async def test_the_manifests_do_not_show_plan_or_expect() -> None:
    async with open_jira_tools(Access(), run_id=RUN) as tools:
        for definition in tools.definitions():
            schema = definition.input_schema
            shown = cast(dict[str, Any], schema.get("properties", {}))
            required = cast(list[str], schema.get("required", []))
            assert "plan" not in shown, definition.name
            assert "expect" not in shown, definition.name
            assert "plan" not in required, definition.name


async def test_a_read_tool_refuses_plan_and_expect() -> None:
    assert (await call(Access(), "getIssue", issue="API-1", plan=True)).startswith("error: ")
    assert (await call(Access(), "getIssue", issue="API-1", expect={})).startswith("error: ")


def test_every_action_has_compared_fields() -> None:
    assert set(COMPARED) == {"open_pr", "push_to_pr", "create_repo", "comment", "transition"}
