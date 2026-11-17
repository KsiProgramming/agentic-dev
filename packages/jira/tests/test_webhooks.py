"""Webhook deliveries (7.3): the JWT check and the trigger's reading of a payload, on deliveries
recorded from a real Jira Cloud site (anonymised: `tests/fixtures/webhooks`)."""

import base64
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2
import jwt
import pytest
from pydantic import SecretStr

from agentic_jira import (
    DELIVERY_HEADER,
    FAKE_CLIENT_ID,
    FAKE_CLIENT_SECRET,
    WEBHOOK_LIMIT,
    AtlassianApp,
    AtlassianAppConfig,
    FakeAtlassian,
    JiraApiError,
    JiraDeliveryError,
    JiraWebhookError,
    parse_event,
    project_filter,
    sign_delivery,
    verify_delivery,
)

FIXTURES = Path(__file__).parent / "fixtures" / "webhooks"
CLOUD = "00000000-0000-0000-0000-0000000c10d0"
TOKEN = SecretStr("access-token-0001")
CLIENT_SECRET = "client-secret-0001-long-enough-for-hs256"
OTHER_SECRET = "someone-else-0001-long-enough-for-hs256"
CONFIG = AtlassianAppConfig(
    client_id="client-1",
    client_secret=SecretStr(CLIENT_SECRET),
    redirect_uri="https://api.example.test/jira/callback",
)

Handler = Callable[[httpx2.Request], httpx2.Response]


def fixture(name: str) -> tuple[dict[str, str], bytes]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return data["headers"], json.dumps(data["body"]).encode()


def verify(authorization: str | None) -> str:
    claims = verify_delivery(
        authorization, client_id=FAKE_CLIENT_ID, client_secret=FAKE_CLIENT_SECRET
    )
    return claims.cloud_id


# --- the JWT ---------------------------------------------------------------------------------


def test_a_delivery_signed_with_the_client_secret_is_accepted() -> None:
    claims = verify_delivery(
        f"Bearer {sign_delivery(CLOUD)}",
        client_id=FAKE_CLIENT_ID,
        client_secret=FAKE_CLIENT_SECRET,
    )
    assert claims.cloud_id == CLOUD
    assert claims.account_id == "fake-account-1"


@pytest.mark.parametrize(
    ("authorization", "reason"),
    [
        (None, "missing"),
        ("", "missing"),
        ("Basic abc", "malformed"),
        ("Bearer ", "malformed"),
        ("Bearer not-a-jwt", "malformed"),
    ],
)
def test_a_missing_or_malformed_header_is_refused(authorization: str | None, reason: str) -> None:
    with pytest.raises(JiraDeliveryError) as refused:
        verify(authorization)
    assert refused.value.reason == reason


def test_another_secret_is_refused() -> None:
    with pytest.raises(JiraDeliveryError) as refused:
        verify(f"Bearer {sign_delivery(CLOUD, secret=OTHER_SECRET)}")
    assert refused.value.reason == "signature"


def test_another_issuer_is_refused() -> None:
    with pytest.raises(JiraDeliveryError) as refused:
        verify(f"Bearer {sign_delivery(CLOUD, issuer='another-app')}")
    assert refused.value.reason == "issuer"


def test_an_expired_delivery_is_refused_past_the_leeway() -> None:
    verify(f"Bearer {sign_delivery(CLOUD, expires_in_s=-10)}")  # within 30 s of leeway
    with pytest.raises(JiraDeliveryError) as refused:
        verify(f"Bearer {sign_delivery(CLOUD, expires_in_s=-120)}")
    assert refused.value.reason == "expired"


def test_only_hs256_is_accepted() -> None:
    """A token cannot pick its algorithm: HS512 with the right secret, and `none`, fail."""

    def part(value: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    claims = {"iss": FAKE_CLIENT_ID, "iat": 0, "exp": 4_000_000_000, "context": {"cloudId": CLOUD}}
    unsigned = f"{part({'alg': 'none', 'typ': 'JWT'})}.{part(claims)}."
    for token in (sign_delivery(CLOUD, algorithm="HS512"), unsigned):
        with pytest.raises(JiraDeliveryError):
            verify(f"Bearer {token}")


def test_a_delivery_with_no_site_is_refused() -> None:
    now = int(datetime.now(UTC).timestamp())
    token = jwt.encode(
        {"iss": FAKE_CLIENT_ID, "iat": now, "exp": now + 900},
        FAKE_CLIENT_SECRET,
        algorithm="HS256",
    )
    with pytest.raises(JiraDeliveryError) as refused:
        verify(f"Bearer {token}")
    assert refused.value.reason == "site"


def test_an_empty_client_secret_accepts_nothing() -> None:
    token = sign_delivery(CLOUD, secret="x" * 32)
    with pytest.raises(JiraDeliveryError) as refused:
        verify_delivery(f"Bearer {token}", client_id=FAKE_CLIENT_ID, client_secret="")
    assert refused.value.reason == "signature"


def test_the_refusal_never_holds_the_token() -> None:
    token = sign_delivery(CLOUD, secret=OTHER_SECRET)
    with pytest.raises(JiraDeliveryError) as refused:
        verify(f"Bearer {token}")
    assert token not in str(refused.value)


# --- the payload -----------------------------------------------------------------------------


def test_a_status_move_names_the_status() -> None:
    event = parse_event(*fixture("status_move"))
    assert (event.event, event.issue_key, event.issue_id, event.project_key) == (
        "jira:issue_updated",
        "KAN-2",
        "10008",
        "KAN",
    )
    assert event.status_to == "In Progress"
    assert event.labels_added == ()
    assert event.webhook_ids == (1, 2, 3)
    assert event.delivery_id == "4724237463476992743"
    assert event.account_id == "557058:00000000-0000-0000-0000-00000000c0de"


def test_a_label_added_is_the_label_new_in_the_list() -> None:
    event = parse_event(*fixture("label_added"))  # "agent" -> "agent ready"
    assert event.labels_added == ("ready",)
    assert event.status_to is None


def test_a_label_removed_adds_nothing() -> None:
    event = parse_event(*fixture("label_removed"))  # "agent ready" -> "ready"
    assert event.labels_added == ()


def test_a_new_issue_brings_its_labels_and_no_status_move() -> None:
    event = parse_event(*fixture("created_with_label"))
    assert event.created
    assert event.labels_added == ("agent",)
    assert event.status_to is None  # its first status ("To Do") is not a move


def test_an_edit_of_other_fields_moves_nothing() -> None:
    event = parse_event(*fixture("summary_edit"))
    assert (event.status_to, event.labels_added) == (None, ())


def test_the_issue_text_is_never_read() -> None:
    """The fixtures' summary is an injection attempt; nothing of it reaches the event."""
    for name in ("status_move", "label_added", "created_with_label", "summary_edit"):
        event = parse_event(*fixture(name))
        assert "Ignore previous instructions" not in repr(event)
        assert "data only" not in repr(event)


def test_the_delivery_id_header_is_found_whatever_its_case() -> None:
    headers, body = fixture("status_move")
    lowered = {key.lower(): value for key, value in headers.items()}
    assert parse_event(lowered, body).delivery_id == headers[DELIVERY_HEADER]


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        b"{}",
        json.dumps({"webhookEvent": "jira:issue_updated"}).encode(),
        json.dumps({"webhookEvent": "jira:issue_updated", "issue": {"id": "1"}}).encode(),
    ],
)
def test_a_payload_that_is_not_an_issue_event_is_refused(body: bytes) -> None:
    with pytest.raises(JiraDeliveryError) as refused:
        parse_event({DELIVERY_HEADER: "1"}, body)
    assert refused.value.reason == "payload"


def test_a_delivery_with_no_id_is_refused() -> None:
    _, body = fixture("status_move")
    with pytest.raises(JiraDeliveryError):
        parse_event({}, body)


# --- the client ------------------------------------------------------------------------------


def app(handler: Handler) -> AtlassianApp:
    return AtlassianApp(CONFIG, transport=httpx2.MockTransport(handler))


def recording(status: int, body: object | None) -> tuple[Handler, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if body is None:
            return httpx2.Response(status)
        return httpx2.Response(status, json=body)

    return handler, seen


def test_the_project_filter_is_sorted_and_quoted() -> None:
    assert project_filter(["OPS", "API", "OPS"]) == 'project in ("API", "OPS")'


async def test_register_asks_for_issue_events_on_status_and_labels() -> None:
    handler, seen = recording(200, {"webhookRegistrationResult": [{"createdWebhookId": 7}]})
    webhook_id = await app(handler).register_webhook(
        TOKEN, CLOUD, "https://agentic.example.test/jira/webhooks", ["KAN"]
    )
    assert webhook_id == 7
    request = seen[0]
    assert (request.method, str(request.url)) == (
        "POST",
        f"https://api.atlassian.com/ex/jira/{CLOUD}/rest/api/3/webhook",
    )
    assert json.loads(request.content) == {
        "url": "https://agentic.example.test/jira/webhooks",
        "webhooks": [
            {
                "events": ["jira:issue_created", "jira:issue_updated"],
                "jqlFilter": 'project in ("KAN")',
                "fieldIdsFilter": ["status", "labels"],
            }
        ],
    }


@pytest.mark.parametrize(
    ("errors", "kind"),
    [
        (
            [
                "Only a single URL per user is allowed to be registered via REST API. The "
                "currently used URL: https://elsewhere.example.test/hook"
            ],
            "url_conflict",
        ),
        (["Maximum number of webhooks exceeded"], "limit"),
        (["The clause watchCount is unsupported"], "refused"),
    ],
)
async def test_a_refused_registration_is_a_fixed_kind(errors: list[str], kind: str) -> None:
    handler, _ = recording(200, {"webhookRegistrationResult": [{"errors": errors}]})
    with pytest.raises(JiraWebhookError) as refused:
        await app(handler).register_webhook(TOKEN, CLOUD, "https://x.test/jira/webhooks", ["A"])
    assert refused.value.kind == kind
    assert "elsewhere" not in str(refused.value)  # Jira's words are dropped


async def test_list_reads_every_page() -> None:
    pages = [
        {
            "startAt": 0,
            "isLast": False,
            "values": [
                {
                    "id": 1,
                    "url": "https://x.test/jira/webhooks",
                    "jqlFilter": 'project in ("KAN")',
                    "expirationDate": "2026-12-17T11:36:25.653+0100",
                }
            ],
        },
        {"startAt": 1, "isLast": True, "values": [{"id": 2, "url": "u", "jqlFilter": "j"}]},
    ]
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=pages[len(seen) - 1])

    webhooks = await app(handler).list_webhooks(TOKEN, CLOUD)
    assert [w.id for w in webhooks] == [1, 2]
    assert webhooks[0].expires_at == datetime(2026, 12, 17, 10, 36, 25, 653000, tzinfo=UTC)
    assert webhooks[1].expires_at is None
    assert [r.url.params["startAt"] for r in seen] == ["0", "1"]


async def test_refresh_returns_the_new_expiry() -> None:
    handler, seen = recording(200, {"expirationDate": "2026-12-17T11:39:06.628+0100"})
    expires = await app(handler).refresh_webhooks(TOKEN, CLOUD, [1, 4])
    assert expires == datetime(2026, 12, 17, 10, 39, 6, 628000, tzinfo=UTC)
    assert (seen[0].method, seen[0].url.path) == (
        "PUT",
        f"/ex/jira/{CLOUD}/rest/api/3/webhook/refresh",
    )
    assert json.loads(seen[0].content) == {"webhookIds": [1, 4]}


async def test_delete_accepts_jiras_empty_202() -> None:
    handler, seen = recording(202, None)
    await app(handler).delete_webhooks(TOKEN, CLOUD, [2, 3])
    assert seen[0].method == "DELETE"
    assert json.loads(seen[0].content) == {"webhookIds": [2, 3]}


async def test_statuses_are_each_named_once_in_jiras_order() -> None:
    body = [
        {"name": "Epic", "statuses": [{"name": "To Do"}, {"name": "Done"}]},
        {"name": "Task", "statuses": [{"name": "To Do"}, {"name": "In Progress"}]},
    ]
    handler, seen = recording(200, body)
    assert await app(handler).project_statuses(TOKEN, CLOUD, "KAN") == [
        "To Do",
        "Done",
        "In Progress",
    ]
    assert seen[0].url.path == f"/ex/jira/{CLOUD}/rest/api/3/project/KAN/statuses"


async def test_statuses_refuse_an_unexpected_body() -> None:
    handler, _ = recording(200, {"oops": 1})
    with pytest.raises(JiraApiError):
        await app(handler).project_statuses(TOKEN, CLOUD, "KAN")


def test_the_app_verifies_with_its_own_credentials() -> None:
    token = sign_delivery(CLOUD, secret=CLIENT_SECRET, issuer="client-1")
    assert app(lambda _: httpx2.Response(500)).verify_delivery(f"Bearer {token}").cloud_id == CLOUD


# --- the fake --------------------------------------------------------------------------------


async def fake_token(fake: FakeAtlassian) -> SecretStr:
    return (await fake.exchange("fake-code")).access_token


async def test_the_fake_keeps_one_url_per_account_and_a_limit_per_site() -> None:
    fake = FakeAtlassian("")
    token = await fake_token(fake)
    url = "https://x.test/jira/webhooks"
    for _ in range(WEBHOOK_LIMIT):
        await fake.register_webhook(token, "fake-cloud-acme", url, ["API"])
    with pytest.raises(JiraWebhookError) as limit:
        await fake.register_webhook(token, "fake-cloud-acme", url, ["API"])
    assert limit.value.kind == "limit"
    with pytest.raises(JiraWebhookError) as conflict:
        await fake.register_webhook(token, "fake-cloud-labs", "https://y.test/hook", ["LAB"])
    assert conflict.value.kind == "url_conflict"


async def test_the_fake_signs_deliveries_it_can_verify() -> None:
    fake = FakeAtlassian("")
    token = await fake_token(fake)
    webhook_id = await fake.register_webhook(
        token, "fake-cloud-acme", "https://x.test/jira/webhooks", ["API"]
    )
    delivery = fake.delivery("fake-cloud-acme", "API-1", status_to="In Progress")
    assert fake.verify_delivery(delivery.headers["Authorization"]).cloud_id == "fake-cloud-acme"
    event = parse_event(delivery.headers, delivery.body)
    assert (event.issue_key, event.status_to, event.webhook_ids) == (
        "API-1",
        "In Progress",
        (webhook_id,),
    )


async def test_the_fake_refreshes_unknown_ids_without_error() -> None:
    fake = FakeAtlassian("")
    token = await fake_token(fake)
    assert await fake.refresh_webhooks(token, "fake-cloud-acme", [999]) is not None
    assert await fake.list_webhooks(token, "fake-cloud-acme") == []
