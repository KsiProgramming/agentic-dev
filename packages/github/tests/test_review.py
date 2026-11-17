"""The webhook side of 7.6: the signature, the command, what a delivery is read for, and the
review a follow-up reads (who counts, since when)."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from agentic_github import (
    FakeReviews,
    GithubDeliveryError,
    command_pattern,
    parse_review_event,
    sign,
    verify_signature,
)
from agentic_github.review import read_review

SECRET = "s3cret"
REPO = "acme/hello"


def test_the_signature_is_the_hmac_of_the_raw_body() -> None:
    body = b'{"action":"created"}'
    assert verify_signature(SECRET, body, sign(SECRET, body))
    assert verify_signature(SECRET, body, sign(SECRET, body).upper().replace("SHA256", "sha256"))
    assert not verify_signature(SECRET, body + b" ", sign(SECRET, body))
    assert not verify_signature("other", body, sign(SECRET, body))
    assert not verify_signature(SECRET, body, None)
    assert not verify_signature("", body, sign("", body))  # no secret verifies nothing


@pytest.mark.parametrize(
    ("text", "matches"),
    [
        ("@agentic-dev fix this", True),
        ("Thanks! @Agentic-Dev   Fix This please", True),
        ("@agentic-dev\nfix this", True),
        ("@agentic-dev fix that", False),
        ("@agentic-devs fix this", False),
        ("me@agentic-dev fix this", False),
        ("agentic-dev fix this", False),
    ],
)
def test_the_command_names_the_app(text: str, matches: bool) -> None:
    assert (command_pattern("agentic-dev").search(text) is not None) is matches


def payload(**changes: Any) -> bytes:
    data: dict[str, Any] = {
        "action": "created",
        "issue": {"number": 4, "pull_request": {}, "title": "Issue text never read"},
        "comment": {
            "id": 11,
            "body": "@agentic-dev fix this, the secret plan",
            "html_url": "https://github.com/acme/hello/pull/4#issuecomment-11",
        },
        "repository": {"full_name": REPO},
        "installation": {"id": 9},
        "sender": {"login": "alice", "id": 3, "type": "User"},
        **changes,
    }
    return json.dumps(data).encode()


def test_a_comment_event_is_read_for_references_only() -> None:
    event = parse_review_event("issue_comment", "d-1", payload(), "agentic-dev")

    assert event is not None
    assert event.command and not event.from_bot
    assert (event.installation_id, event.full_name, event.pr_number) == (9, REPO, 4)
    assert (event.kind, event.comment_id, event.sender_login) == ("issue_comment", 11, "alice")
    assert event.pr_url == "https://github.com/acme/hello/pull/4"
    assert "secret plan" not in repr(event)


def test_events_and_actions_that_cannot_ask_are_none() -> None:
    assert parse_review_event("push", "d", payload(), "agentic-dev") is None
    assert parse_review_event("issue_comment", "d", payload(action="edited"), "agentic-dev") is None
    on_issue = payload(issue={"number": 4})
    assert parse_review_event("issue_comment", "d", on_issue, "agentic-dev") is None


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        payload(repository={"full_name": "../etc"}),
        payload(installation={}),
        payload(sender={"login": "-bad", "id": 3}),
    ],
)
def test_a_comment_event_that_cannot_be_read_is_refused(body: bytes) -> None:
    with pytest.raises(GithubDeliveryError):
        parse_review_event("issue_comment", "d", body, "agentic-dev")


async def test_the_review_is_the_writers_comments_since_the_push() -> None:
    github = FakeReviews()
    github.permissions.update({"alice": "write", "bob": "admin", "eve": "read"})
    pushed = datetime(2026, 11, 17, 12, tzinfo=UTC)
    before = github.add_item(REPO, 4, "issue_comment", "bob", "old", created_at=pushed)
    trigger = github.add_item(
        REPO, 4, "issue_comment", "alice", "@agentic-dev fix this", created_at=pushed
    )
    inline = github.add_item(
        REPO,
        4,
        "review_comment",
        "bob",
        "Rename this.",
        created_at=pushed + timedelta(minutes=1),
        path="app.py",
        line=3,
        diff_hunk="@@ -1 +1 @@\n-a\n+b",
    )
    github.add_item(REPO, 4, "issue_comment", "eve", "drive-by", created_at=pushed + timedelta(1))
    github.add_item(
        REPO, 4, "issue_comment", "ci[bot]", "build ok", author_type="Bot", created_at=pushed
    )
    github.add_item(REPO, 4, "review", "bob", "  ", created_at=pushed + timedelta(minutes=2))

    read = await read_review(
        github, 9, REPO, 4, after=pushed, trigger_kind="issue_comment", trigger_id=trigger.id
    )

    assert read.trigger == trigger  # kept, though it is not after the push
    assert read.items == [inline]
    assert before not in read.items


async def test_a_deleted_trigger_is_none() -> None:
    read = await read_review(
        FakeReviews(), 9, REPO, 4, after=None, trigger_kind="issue_comment", trigger_id=1
    )
    assert read.trigger is None and read.items == []
