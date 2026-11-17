"""The GitHub App's webhook deliveries (7.6): checking that one comes from GitHub, and reading the
little of a pull request comment that a follow-up run needs.

A delivery carries `X-Hub-Signature-256: sha256=<hex>`, the HMAC-SHA256 of the raw body keyed with
the App's webhook secret. Nothing in it is read before that checks out.

`parse_review_event` reads three events: `issue_comment` (`created`, on a pull request),
`pull_request_review` (`submitted`) and `pull_request_review_comment` (`created`). It returns ids
and metadata only: the installation, the repo, the pull request, the comment and who wrote it.
The comment's body is read for one thing, whether it is the command `@<app slug> fix this`, and
is never returned (principle 5): the worker reads the review afterwards, once, for the run."""

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from typing import Any, Final, Literal, cast

from agentic_github.errors import GithubDeliveryError

SIGNATURE_HEADER: Final = "X-Hub-Signature-256"
EVENT_HEADER: Final = "X-GitHub-Event"
DELIVERY_HEADER: Final = "X-GitHub-Delivery"
"""A GUID, the same across GitHub's redeliveries of one delivery."""
MAX_BODY_BYTES: Final = 2_000_000
"""GitHub caps payloads at 25 MB; a comment event is far below this."""

REVIEW_EVENTS: Final = {
    "issue_comment": "created",
    "pull_request_review": "submitted",
    "pull_request_review_comment": "created",
}
"""The events (and the one action of each) a follow-up can start from."""

type ReviewKind = Literal["issue_comment", "review", "review_comment"]

_KINDS: Final[dict[str, ReviewKind]] = {
    "issue_comment": "issue_comment",
    "pull_request_review": "review",
    "pull_request_review_comment": "review_comment",
}
_FULL_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(?:\[bot\])?$")
_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62})$")

type _Json = dict[str, Any]


@dataclass(frozen=True)
class ReviewEvent:
    """What a follow-up needs from a pull request comment delivery: references, never text.
    `command` says whether the comment is `@<app slug> fix this`."""

    delivery_id: str
    kind: ReviewKind
    installation_id: int
    full_name: str
    pr_number: int
    # The comment, or the review for `review`; its page on GitHub.
    comment_id: int
    comment_url: str
    sender_login: str
    sender_id: int
    sender_type: str
    command: bool

    @property
    def pr_url(self) -> str:
        return f"https://github.com/{self.full_name}/pull/{self.pr_number}"

    @property
    def from_bot(self) -> bool:
        return self.sender_type == "Bot" or self.sender_login.endswith("[bot]")


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    """Whether `header` (`sha256=<hex>`) is the HMAC-SHA256 of `body` keyed with `secret`,
    compared in constant time. An empty secret verifies nothing."""
    if not secret or not header:
        return False
    scheme, _, digest = header.strip().partition("=")
    if scheme != "sha256" or not digest:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, digest.lower())


def sign(secret: str, body: bytes) -> str:
    """The `X-Hub-Signature-256` value GitHub sends for `body` (for tests and fakes)."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def command_pattern(app_slug: str) -> re.Pattern[str]:
    """`@<app_slug> fix this`, anywhere in a comment, any case, not part of a longer mention."""
    if not _SLUG.match(app_slug.lower()):
        raise ValueError(f"not a GitHub App slug: {app_slug!r}")
    return re.compile(rf"(?<![\w@-])@{re.escape(app_slug)}(?![\w-])\s+fix\s+this\b", re.IGNORECASE)


def parse_review_event(
    event: str | None, delivery_id: str | None, body: bytes, app_slug: str
) -> ReviewEvent | None:
    """The follow-up's view of a verified delivery, or `None` for an event or action it does
    not handle (including a comment on an issue that is not a pull request). Raises
    `GithubDeliveryError("payload")` when a handled event cannot be read."""
    if event not in REVIEW_EVENTS:
        return None
    if not delivery_id or len(delivery_id) > 64:
        raise GithubDeliveryError("payload")
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise GithubDeliveryError("payload") from None
    if not isinstance(payload, dict):
        raise GithubDeliveryError("payload")
    data = cast(_Json, payload)
    if data.get("action") != REVIEW_EVENTS[event]:
        return None
    if event == "issue_comment":
        issue = _object(data.get("issue"))
        if not isinstance(issue.get("pull_request"), dict):
            return None  # a comment on an issue, not on a pull request
        number = issue.get("number")
        comment = _object(data.get("comment"))
    elif event == "pull_request_review":
        number = _object(data.get("pull_request")).get("number")
        comment = _object(data.get("review"))
    else:
        number = _object(data.get("pull_request")).get("number")
        comment = _object(data.get("comment"))
    installation_id = _object(data.get("installation")).get("id")
    full_name = _object(data.get("repository")).get("full_name")
    sender = _object(data.get("sender"))
    login, sender_id = sender.get("login"), sender.get("id")
    comment_id, comment_url = comment.get("id"), comment.get("html_url")
    if not (
        _int(installation_id)
        and _int(number)
        and _int(comment_id)
        and _int(sender_id)
        and isinstance(full_name, str)
        and _FULL_NAME.match(full_name)
        and isinstance(login, str)
        and _LOGIN.match(login)
    ):
        raise GithubDeliveryError("payload")
    body_text = comment.get("body")
    text = body_text if isinstance(body_text, str) else ""
    sender_type = sender.get("type")
    return ReviewEvent(
        delivery_id=delivery_id,
        kind=_KINDS[event],
        installation_id=cast(int, installation_id),
        full_name=full_name,
        pr_number=cast(int, number),
        comment_id=cast(int, comment_id),
        comment_url=_github_url(comment_url),
        sender_login=login,
        sender_id=cast(int, sender_id),
        sender_type=sender_type if isinstance(sender_type, str) else "User",
        command=command_pattern(app_slug).search(text) is not None,
    )


def _object(value: object) -> _Json:
    return cast(_Json, value) if isinstance(value, dict) else {}


def _int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _github_url(value: object) -> str:
    """A link to github.com, else empty: it is shown in the console as a link."""
    if isinstance(value, str) and value.startswith("https://github.com/") and len(value) < 500:
        return value
    return ""
