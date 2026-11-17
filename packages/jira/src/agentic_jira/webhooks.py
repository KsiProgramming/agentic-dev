"""Jira Cloud's webhook deliveries (7.3): checking that one comes from Atlassian, and reading the
little of it a trigger needs.

A delivery of a webhook the app registered carries `Authorization: Bearer <JWT>`, signed HS256
with the app's client secret. Its claims are `iss` (the client id), `sub` (the account that
registered the webhook), `context.cloudId` (the site), `iat`, `exp` (15 minutes later) and `jti`;
there is no `aud` and no `qsh` (checked on a real site, 2026-11-17).

`parse_event` reads ids, the project, who made the change and the changelog's status and label
items. The issue's summary, description and comments are never read: they are data for the run
to fetch with `jira.getIssue`, not something a trigger passes on (principle 5)."""

import json
from collections.abc import Mapping
from typing import Any, cast

import jwt

from agentic_jira.errors import JiraDeliveryError
from agentic_jira.models import DeliveryClaims, IssueEvent

ALGORITHM = "HS256"
LEEWAY_S = 30
"""Clock skew allowed on `exp` and `iat`."""
MAX_BODY_BYTES = 1_000_000
DELIVERY_HEADER = "X-Atlassian-Webhook-Identifier"
"""Unique on the site, and the same across Atlassian's retries of one delivery."""

type _Json = dict[str, Any]


def verify_delivery(
    authorization: str | None,
    *,
    client_id: str,
    client_secret: str,
) -> DeliveryClaims:
    """The claims of a delivery's `Authorization` header, once its signature, issuer and expiry
    are checked. Only `HS256` is accepted, so a token cannot choose a weaker algorithm.
    `JiraDeliveryError` otherwise."""
    if not authorization:
        raise JiraDeliveryError("missing")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise JiraDeliveryError("malformed")
    if not client_secret:
        # With no secret, any token signed with an empty key would pass.
        raise JiraDeliveryError("signature")
    try:
        claims: _Json = jwt.decode(
            token.strip(),
            client_secret,
            algorithms=[ALGORITHM],
            issuer=client_id,
            leeway=LEEWAY_S,
            options={"require": ["exp", "iat", "iss"], "verify_aud": False},
        )
    except jwt.ExpiredSignatureError:
        raise JiraDeliveryError("expired") from None
    except jwt.InvalidIssuerError:
        raise JiraDeliveryError("issuer") from None
    except jwt.InvalidSignatureError:
        raise JiraDeliveryError("signature") from None
    except jwt.InvalidTokenError:
        raise JiraDeliveryError("malformed") from None
    context = claims.get("context")
    cloud_id = cast(_Json, context).get("cloudId") if isinstance(context, dict) else None
    if not isinstance(cloud_id, str) or not cloud_id:
        raise JiraDeliveryError("site")
    sub = claims.get("sub")
    return DeliveryClaims(cloud_id=cloud_id, account_id=sub if isinstance(sub, str) else "")


def parse_event(headers: Mapping[str, str], body: bytes) -> IssueEvent:
    """The trigger's view of a verified delivery. `JiraDeliveryError("payload")` when it is not
    an issue event we can read."""
    delivery_id = _header(headers, DELIVERY_HEADER)
    if not delivery_id:
        raise JiraDeliveryError("payload")
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise JiraDeliveryError("payload") from None
    if not isinstance(payload, dict):
        raise JiraDeliveryError("payload")
    data = cast(_Json, payload)
    event = data.get("webhookEvent")
    issue = data.get("issue")
    if not isinstance(event, str) or not isinstance(issue, dict):
        raise JiraDeliveryError("payload")
    issue = cast(_Json, issue)
    fields = issue.get("fields")
    fields = cast(_Json, fields) if isinstance(fields, dict) else {}
    issue_id, key = issue.get("id"), issue.get("key")
    project = fields.get("project")
    project_key = cast(_Json, project).get("key") if isinstance(project, dict) else None
    if not (isinstance(issue_id, str) and isinstance(key, str) and isinstance(project_key, str)):
        raise JiraDeliveryError("payload")
    user = data.get("user")
    account_id = cast(_Json, user).get("accountId") if isinstance(user, dict) else None
    status_to, labels_added = _changes(data.get("changelog"))
    if event == "jira:issue_created":
        # A new issue's changelog does not list its labels; its fields do. Its first status is
        # not a move.
        status_to, labels_added = None, _labels(fields.get("labels"))
    return IssueEvent(
        delivery_id=delivery_id,
        event=event,
        webhook_ids=_ids(data.get("matchedWebhookIds")),
        account_id=account_id if isinstance(account_id, str) else None,
        issue_id=issue_id,
        issue_key=key,
        project_key=project_key,
        status_to=status_to,
        labels_added=labels_added,
    )


def _changes(changelog: object) -> tuple[str | None, tuple[str, ...]]:
    """The status an update moved to and the labels it added. Labels come as space-separated
    lists (`fromString`, `toString`); a label cannot hold a space."""
    if not isinstance(changelog, dict):
        return None, ()
    items = cast(_Json, changelog).get("items")
    if not isinstance(items, list):
        return None, ()
    status_to: str | None = None
    added: list[str] = []
    for raw in cast(list[Any], items):
        if not isinstance(raw, dict):
            continue
        item = cast(_Json, raw)
        field = item.get("fieldId") or item.get("field")
        if field == "status" and isinstance(item.get("toString"), str):
            status_to = str(item["toString"])
        elif field == "labels":
            before = set(_split(item.get("fromString")))
            added.extend(label for label in _split(item.get("toString")) if label not in before)
    return status_to, tuple(dict.fromkeys(added))


def _split(value: object) -> list[str]:
    return value.split() if isinstance(value, str) else []


def _labels(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(label for label in cast(list[Any], value) if isinstance(label, str) and label)


def _ids(value: object) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    items = cast(list[Any], value)
    return tuple(i for i in items if isinstance(i, int) and not isinstance(i, bool))


def _header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value.strip() or None
    return None
