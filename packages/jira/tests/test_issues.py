import json
from collections.abc import Callable
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from pydantic import SecretStr

from agentic_jira import (
    AtlassianApp,
    AtlassianAppConfig,
    FakeAtlassian,
    JiraApiError,
    JiraBadRequestError,
    JiraNotFoundError,
    JiraRateLimitedError,
    JiraUnauthorizedError,
    Transition,
)

CONFIG = AtlassianAppConfig(
    client_id="client-1",
    client_secret=SecretStr("client-secret-0001"),
    redirect_uri="https://api.example.test/jira/callback",
)
TOKEN = SecretStr("access-token-0001")
SITE = "https://api.atlassian.com/ex/jira/cloud-1/rest/api/3"

Handler = Callable[[httpx2.Request], httpx2.Response]


def app(handler: Handler, waits: list[float] | None = None) -> AtlassianApp:
    async def sleep(seconds: float) -> None:
        if waits is not None:
            waits.append(seconds)

    return AtlassianApp(CONFIG, transport=httpx2.MockTransport(handler), sleep=sleep)


def query(request: httpx2.Request) -> dict[str, list[str]]:
    return parse_qs(urlsplit(str(request.url)).query)


ISSUE = {
    "id": "10042",
    "key": "API-12",
    "fields": {
        "summary": "Rate limit",
        "status": {"name": "To Do"},
        "issuetype": {"name": "Story"},
        "priority": {"name": "High"},
        "labels": ["backend"],
        "components": [{"name": "gateway"}],
        "assignee": None,
        "reporter": {"displayName": "Ada Example", "emailAddress": "ada@example.test"},
        "created": "2026-11-01T09:00:00.000+0000",
        "updated": "2026-11-02T09:00:00.000+0000",
        "project": {"key": "API"},
        "description": {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Do it."}]}],
        },
    },
}
COMMENTS = {
    "total": 7,
    "comments": [
        {
            "id": "2",
            "author": {"displayName": "Bo"},
            "created": "2026-11-03",
            "body": {
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "newer"}]}],
            },
        },
        {"id": "1", "author": {"displayName": "Ada"}, "created": "2026-11-02", "body": None},
    ],
}


async def test_an_issue_is_read_with_its_latest_comments_oldest_first() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(
            200, json=COMMENTS if request.url.path.endswith("/comment") else ISSUE
        )

    issue = await app(handler).get_issue(TOKEN, "cloud-1", "API-12")

    assert [str(r.url).split("?")[0] for r in seen] == [
        f"{SITE}/issue/API-12",
        f"{SITE}/issue/API-12/comment",
    ]
    assert seen[0].headers["Authorization"] == "Bearer access-token-0001"
    assert "description" in query(seen[0])["fields"][0]
    assert query(seen[1]) == {"orderBy": ["-created"], "maxResults": ["20"]}
    assert issue.key == "API-12"
    assert issue.project_key == "API"
    assert (issue.status, issue.type, issue.priority) == ("To Do", "Story", "High")
    assert issue.labels == ("backend",)
    assert issue.components == ("gateway",)
    assert issue.assignee is None
    assert issue.reporter == "Ada Example"
    assert issue.description == "Do it."
    assert [(c.author, c.body) for c in issue.comments] == [("Ada", ""), ("Bo", "newer")]
    assert issue.comment_count == 7


async def test_an_issue_key_is_quoted_in_the_path() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(404, json={})

    with pytest.raises(JiraNotFoundError):
        await app(handler).get_issue(TOKEN, "cloud-1", "../../myself")

    assert seen[0].url.raw_path.startswith(b"/ex/jira/cloud-1/rest/api/3/issue/..%2F..%2Fmyself")


async def test_a_search_sends_the_query_as_given_and_reads_its_page() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(
            200, json={"issues": [ISSUE], "nextPageToken": "next-1", "isLast": False}
        )

    page = await app(handler).search(TOKEN, "cloud-1", 'project in ("API")', limit=5)

    assert str(seen[0].url).split("?")[0] == f"{SITE}/search/jql"
    assert query(seen[0])["jql"] == ['project in ("API")']
    assert query(seen[0])["maxResults"] == ["5"]
    assert [i.key for i in page.issues] == ["API-12"]
    assert page.issues[0].project_key == "API"
    assert page.next_page_token == "next-1"


async def test_a_last_search_page_has_no_next_token() -> None:
    page = await app(
        lambda _: httpx2.Response(200, json={"issues": [], "isLast": True, "nextPageToken": "x"})
    ).search(TOKEN, "cloud-1", "project = API", limit=5)

    assert page.next_page_token is None


async def test_an_invalid_query_is_a_bad_request() -> None:
    with pytest.raises(JiraBadRequestError):
        await app(lambda _: httpx2.Response(400, json={"errorMessages": ["secret words"]})).search(
            TOKEN, "cloud-1", "nonsense", limit=5
        )


async def test_transitions_are_listed_with_their_target() -> None:
    body = {"transitions": [{"id": "11", "name": "Start", "to": {"name": "In Progress"}}]}

    found = await app(lambda _: httpx2.Response(200, json=body)).transitions(
        TOKEN, "cloud-1", "API-12"
    )

    assert found == [Transition("11", "Start", "In Progress")]


async def test_a_comment_is_posted_as_adf() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(201, json={"id": "900"})

    comment_id = await app(handler).add_comment(TOKEN, "cloud-1", "API-12", "Hello **there**")

    assert comment_id == "900"
    assert seen[0].method == "POST"
    assert str(seen[0].url) == f"{SITE}/issue/API-12/comment"
    body = json.loads(seen[0].content)
    assert body["body"]["type"] == "doc"
    assert body["body"]["content"][0]["content"][1] == {
        "type": "text",
        "text": "there",
        "marks": [{"type": "strong"}],
    }


async def test_a_transition_is_posted_by_id() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(204)

    await app(handler).transition(TOKEN, "cloud-1", "API-12", "31")

    assert str(seen[0].url) == f"{SITE}/issue/API-12/transitions"
    assert json.loads(seen[0].content) == {"transition": {"id": "31"}}


async def test_a_rate_limit_is_waited_out_once() -> None:
    answers = iter([httpx2.Response(429, headers={"Retry-After": "2"}), httpx2.Response(204)])
    waits: list[float] = []

    await app(lambda _: next(answers), waits).transition(TOKEN, "cloud-1", "API-12", "31")

    assert waits == [2.0]


async def test_a_second_rate_limit_or_a_long_wait_gives_up() -> None:
    waits: list[float] = []
    with pytest.raises(JiraRateLimitedError):
        await app(lambda _: httpx2.Response(429, headers={"Retry-After": "1"}), waits).transition(
            TOKEN, "cloud-1", "API-12", "31"
        )
    assert waits == [1.0]

    with pytest.raises(JiraRateLimitedError):
        await app(lambda _: httpx2.Response(429, headers={"Retry-After": "60"}), waits).transition(
            TOKEN, "cloud-1", "API-12", "31"
        )
    assert waits == [1.0]


async def test_errors_carry_no_token_or_body() -> None:
    for status, kind in ((401, JiraUnauthorizedError), (500, JiraApiError), (403, JiraApiError)):
        with pytest.raises(kind) as caught:
            await app(
                lambda _, s=status: httpx2.Response(s, json={"errorMessages": ["leaky body"]})
            ).get_issue(TOKEN, "cloud-1", "API-12")
        assert "leaky" not in str(caught.value)
        assert TOKEN.get_secret_value() not in str(caught.value)


# --- the fake ------------------------------------------------------------------------------


async def fake_token(fake: FakeAtlassian) -> SecretStr:
    return (await fake.exchange("fake-code")).access_token


async def test_the_fake_reads_moves_and_posts() -> None:
    fake = FakeAtlassian("http://api.test")
    token = await fake_token(fake)

    moved = await fake.get_issue(token, "fake-cloud-acme", "DOCS-9")
    assert (moved.key, moved.project_key) == ("OPS-2", "OPS")

    await fake.add_comment(token, "fake-cloud-acme", "API-1", "Looked at it.")
    issue = await fake.get_issue(token, "fake-cloud-acme", "API-1")
    assert issue.comments[-1].body == "Looked at it."
    assert [p.key for p in fake.posted] == ["API-1"]

    assert [t.name for t in await fake.transitions(token, "fake-cloud-acme", "API-1")] == [
        "Start progress",
        "Done",
    ]
    await fake.transition(token, "fake-cloud-acme", "API-1", "11")
    assert (await fake.get_issue(token, "fake-cloud-acme", "API-1")).status == "In Progress"
    with pytest.raises(JiraBadRequestError):
        await fake.transition(token, "fake-cloud-acme", "API-1", "41")
    with pytest.raises(JiraNotFoundError):
        await fake.get_issue(token, "fake-cloud-acme", "API-999")


async def test_the_fake_search_keeps_to_its_project_clause_unless_it_leaks() -> None:
    fake = FakeAtlassian("http://api.test")
    token = await fake_token(fake)

    page = await fake.search(token, "fake-cloud-acme", 'project in ("API") AND (x)', limit=10)
    assert {i.project_key for i in page.issues} == {"API"}

    fake.leak_search = True
    page = await fake.search(token, "fake-cloud-acme", 'project in ("API") AND (x)', limit=10)
    assert {i.project_key for i in page.issues} == {"API", "DOCS", "OPS"}
