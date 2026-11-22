"""The personal-connection OAuth client (8.2) on a mock transport, and its fake: no network."""

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx2
import pytest
from pydantic import SecretStr

from agentic_github import (
    FakeGithubUserAuth,
    GithubApiError,
    GithubUser,
    GithubUserAuthError,
    GithubUserOAuth,
    GithubUserOAuthConfig,
    GithubUserUnauthorizedError,
    UserGrant,
)

SECRET = "client-secret-0123456789"
CONFIG = GithubUserOAuthConfig(
    client_id="Iv1.abc",
    client_secret=SecretStr(SECRET),
    redirect_uri="https://api.test/github-user/callback",
    scopes=("read:user",),
)


def client(transport: httpx2.MockTransport | None = None) -> GithubUserOAuth:
    return GithubUserOAuth(
        CONFIG, transport=transport or httpx2.MockTransport(lambda r: httpx2.Response(500))
    )


def form(request: httpx2.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


def test_the_authorize_url_carries_the_state_and_the_scopes() -> None:
    url = urlparse(client().authorize_url("state-1"))
    query = {k: v[0] for k, v in parse_qs(url.query).items()}

    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://github.com/login/oauth/authorize"
    assert query == {
        "client_id": "Iv1.abc",
        "redirect_uri": CONFIG.redirect_uri,
        "state": "state-1",
        "scope": "read:user",
    }
    assert SECRET not in url.query


async def test_exchange_sends_the_code_and_reads_a_non_expiring_token() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(
            200, json={"access_token": "gho_abc", "scope": "read:user,user:email"}
        )

    grant = await client(httpx2.MockTransport(handler)).exchange("the-code")

    assert form(seen[0]) == {
        "client_id": "Iv1.abc",
        "client_secret": SECRET,
        "code": "the-code",
        "redirect_uri": CONFIG.redirect_uri,
    }
    assert seen[0].headers["accept"] == "application/json"
    assert grant.access_token.get_secret_value() == "gho_abc"
    assert (grant.refresh_token, grant.expires_at) == (None, None)
    assert grant.scopes == ("read:user", "user:email")


async def test_exchange_reads_an_expiring_token_with_a_refresh_token() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200, json={"access_token": "ghu_abc", "refresh_token": "ghr_abc", "expires_in": 28800}
        )

    grant = await client(httpx2.MockTransport(handler)).exchange("c")

    assert grant.refresh_token == SecretStr("ghr_abc")
    assert grant.expires_at is not None
    left = grant.expires_at - datetime.now(UTC)
    assert timedelta(hours=7, minutes=59) < left <= timedelta(hours=8)


async def test_a_refused_code_is_a_fixed_reason_even_though_github_answers_200() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200, json={"error": "bad_verification_code", "error_description": "the-code is bad"}
        )

    with pytest.raises(GithubUserAuthError) as raised:
        await client(httpx2.MockTransport(handler)).exchange("the-code")

    assert raised.value.reason == "exchange"
    assert "the-code" not in str(raised.value)


async def test_refresh_sends_the_refresh_token_and_a_refused_one_is_invalid_grant() -> None:
    seen: list[dict[str, str]] = []
    answers = iter(
        [
            httpx2.Response(
                200, json={"access_token": "ghu_2", "refresh_token": "ghr_2", "expires_in": 28800}
            ),
            httpx2.Response(200, json={"error": "bad_refresh_token"}),
        ]
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(form(request))
        return next(answers)

    app = client(httpx2.MockTransport(handler))
    grant = await app.refresh(SecretStr("ghr_1"))
    with pytest.raises(GithubUserAuthError) as raised:
        await app.refresh(SecretStr("ghr_2"))

    assert seen[0]["grant_type"] == "refresh_token"
    assert seen[0]["refresh_token"] == "ghr_1"
    assert grant.refresh_token == SecretStr("ghr_2")
    assert raised.value.reason == "invalid_grant"


async def test_user_reads_the_id_and_login_and_a_refused_token_is_unauthorized() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.headers["authorization"] != "Bearer gho_good":
            return httpx2.Response(401, json={"message": "Bad credentials"})
        return httpx2.Response(200, json={"id": 42, "login": "ada"})

    app = client(httpx2.MockTransport(handler))

    assert await app.user(SecretStr("gho_good")) == GithubUser(id=42, login="ada")
    with pytest.raises(GithubUserUnauthorizedError):
        await app.user(SecretStr("gho_bad"))


async def test_errors_never_carry_the_token_or_the_secret() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("boom gho_leaky")

    app = client(httpx2.MockTransport(handler))

    with pytest.raises(GithubApiError) as raised:
        await app.user(SecretStr("gho_leaky"))
    assert "gho_leaky" not in str(raised.value)
    with pytest.raises(GithubApiError) as raised:
        await app.exchange("c")
    assert SECRET not in str(raised.value)


async def test_github_unavailable_is_an_api_error_not_a_refusal() -> None:
    app = client(httpx2.MockTransport(lambda _: httpx2.Response(503)))

    with pytest.raises(GithubApiError, match="503"):
        await app.exchange("c")


def test_a_grant_round_trips_through_its_secret_and_hides_its_tokens() -> None:
    expires = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
    grant = UserGrant(SecretStr("ghu_a"), SecretStr("ghr_a"), expires, ("read:user",))

    assert UserGrant.from_secret(grant.to_secret()) == grant
    assert "ghu_a" not in repr(grant)
    assert "ghr_a" not in repr(grant)
    bare = UserGrant(SecretStr("gho_a"))
    assert UserGrant.from_secret(bare.to_secret()) == bare
    json.loads(bare.to_secret().get_secret_value())  # one JSON document


def fake_code(fake: FakeGithubUserAuth) -> str:
    return parse_qs(urlparse(fake.authorize_url("s")).query)["code"][0]


async def test_the_fake_runs_the_whole_flow_as_a_chosen_person() -> None:
    fake = FakeGithubUserAuth("http://api.test", login="grace")
    callback = urlparse(fake.authorize_url("s1"))
    query = {k: v[0] for k, v in parse_qs(callback.query).items()}

    grant = await fake.exchange(query["code"])
    user = await fake.user(grant.access_token)

    assert (callback.path, query["state"]) == ("/github-user/callback", "s1")
    assert user == GithubUser(id=1002, login="grace")
    assert grant.refresh_token is None
    with pytest.raises(GithubUserAuthError):
        await fake.exchange("not-a-code")


async def test_the_fake_issues_expiring_grants_and_can_refuse() -> None:
    fake = FakeGithubUserAuth("http://api.test", expires_in_s=3600)
    grant = await fake.exchange(fake_code(fake))
    assert grant.refresh_token is not None
    assert grant.expires_at is not None

    fresh = await fake.refresh(grant.refresh_token)
    assert fresh.access_token != grant.access_token
    assert fake.refreshes == 1

    fake.refuse_refresh = True
    with pytest.raises(GithubUserAuthError):
        await fake.refresh(grant.refresh_token)
    fake.unauthorized = True
    with pytest.raises(GithubUserUnauthorizedError):
        await fake.user(grant.access_token)
