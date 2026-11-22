"""A run on a person's Copilot (8.2): which runtime it gets, and every way its token can fail
before an agent runs."""

import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.spec import parse_spec
from agentic_github import FakeGithubUserAuth
from agentic_runtime import AgentRequest, ClaudeRuntime, CopilotRuntime, Failed, Message
from agentic_runtime.fake import FakeRuntime
from agentic_runtime.testing import MockClaude
from agentic_secrets import KEY_BYTES, LocalKeyProvider
from agentic_store import (
    StoredRun,
    Workspace,
    mark_github_user_needs_attention,
    put_github_user_connection,
)
from agentic_worker.copilot import _Watching, token_loader  # pyright: ignore[reportPrivateUsage]
from agentic_worker.errors import RunSetupError
from agentic_worker.main import WorkerSettings, build_github_user, run_runtimes

NO_DB: async_sessionmaker[AsyncSession] = async_sessionmaker()
SPEC = parse_spec(
    json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "engine/tests/fixtures/specs/valid/single-agent.json"
        ).read_text(encoding="utf-8")
    )
)
TOKEN = "gho_worker_token_0001"


def a_copilot_run(workspace_id: UUID | None = None, connection_id: UUID | None = None) -> StoredRun:
    kwargs: dict[str, object] = {
        "copilot_connection_id": connection_id or uuid4(),
        "copilot_login": "ada",
    }
    if workspace_id is not None:
        kwargs["workspace_id"] = workspace_id
    return StoredRun(id=uuid4(), status="queued", spec=SPEC, input="", **kwargs)  # pyright: ignore[reportArgumentType]


@pytest.fixture
def keys() -> LocalKeyProvider:
    return LocalKeyProvider(os.urandom(KEY_BYTES))


async def test_a_run_with_no_connection_stays_on_claude_whatever_copilot_is_set_up(
    keys: LocalKeyProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def load(*_args: object) -> SecretStr | None:
        return SecretStr("sk-ant-test-0000")

    async def prices(*_args: object) -> object:
        from agentic_runtime import DEFAULT_PRICES

        return DEFAULT_PRICES

    monkeypatch.setattr("agentic_worker.main.load_secret", load)
    monkeypatch.setattr("agentic_worker.main.workspace_price_table", prices)
    mock = MockClaude([])
    runtimes = run_runtimes(
        WorkerSettings(agentic_runtime="claude"),  # pyright: ignore[reportCallIssue]
        NO_DB,
        keys,
        lambda k: mock.make_client(k.get_secret_value()),
        FakeGithubUserAuth(""),
    )

    run = StoredRun(id=uuid4(), status="queued", spec=SPEC, input="")
    async with runtimes(run, None) as runtime:
        assert isinstance(runtime, ClaudeRuntime)


async def test_on_the_fake_stack_a_copilot_run_reads_its_token_then_runs_fake_agents(
    keys: LocalKeyProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[StoredRun] = []

    def loader(sessions: object, master: object, auth: object):
        async def load(run: StoredRun) -> SecretStr:
            seen.append(run)
            return SecretStr(TOKEN)

        return load

    monkeypatch.setattr("agentic_worker.main.token_loader", loader)
    runtimes = run_runtimes(WorkerSettings(), NO_DB, keys, github_user=FakeGithubUserAuth(""))

    run = a_copilot_run()
    async with runtimes(run, None) as runtime:
        assert isinstance(runtime, FakeRuntime)
    assert seen == [run]


async def test_with_a_real_runtime_a_copilot_run_gets_the_copilot_runtime(
    keys: LocalKeyProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    def loader(sessions: object, master: object, auth: object):
        async def load(run: StoredRun) -> SecretStr:
            return SecretStr(TOKEN)

        return load

    monkeypatch.setattr("agentic_worker.main.token_loader", loader)
    runtimes = run_runtimes(
        WorkerSettings(agentic_runtime="claude", copilot_model="gpt-5"),  # pyright: ignore[reportCallIssue]
        NO_DB,
        keys,
        github_user=FakeGithubUserAuth(""),
    )

    async with runtimes(a_copilot_run(), None) as runtime:
        # Watched, so a token GitHub refuses mid-run marks its connection.
        assert isinstance(runtime, _Watching)
        assert isinstance(runtime._inner, CopilotRuntime)  # pyright: ignore[reportPrivateUsage]


async def test_a_copilot_run_with_no_master_key_fails_with_its_code() -> None:
    runtimes = run_runtimes(WorkerSettings(), NO_DB, None)

    with pytest.raises(RunSetupError, match="copilot_not_configured"):
        async with runtimes(a_copilot_run(), None):
            pass


def test_the_fake_user_oauth_app_is_built_with_the_fake_github_and_never_in_production() -> None:
    fake = WorkerSettings(agentic_github="fake")  # pyright: ignore[reportCallIssue]
    assert isinstance(build_github_user(fake), FakeGithubUserAuth)
    assert build_github_user(WorkerSettings()) is None


# --- the token loader, against a real database ---


async def workspace_with_connection(
    sessions: async_sessionmaker[AsyncSession], keys: LocalKeyProvider, auth: FakeGithubUserAuth
) -> tuple[UUID, UUID]:
    workspace_id = uuid4()
    async with sessions.begin() as session:
        session.add(Workspace(id=workspace_id, name=f"ws-{workspace_id.hex[:6]}"))
    grant = await auth.exchange("fake-user-code-ada")
    user = await auth.user(grant.access_token)
    info = await put_github_user_connection(
        sessions,
        keys,
        workspace_id,
        github_user_id=user.id,
        login=user.login,
        scopes=None,
        secret=grant.to_secret(),
    )
    return workspace_id, info.id


@pytest.mark.integration
async def test_the_loader_reads_the_token_of_the_runs_own_connection(
    sessions: async_sessionmaker[AsyncSession], keys: LocalKeyProvider
) -> None:
    auth = FakeGithubUserAuth("")
    workspace_id, connection_id = await workspace_with_connection(sessions, keys, auth)

    token = await token_loader(sessions, keys, auth)(a_copilot_run(workspace_id, connection_id))

    assert token == auth.issued[0].access_token


@pytest.mark.integration
async def test_the_loader_never_reads_another_workspaces_connection(
    sessions: async_sessionmaker[AsyncSession], keys: LocalKeyProvider
) -> None:
    auth = FakeGithubUserAuth("")
    _, theirs = await workspace_with_connection(sessions, keys, auth)
    mine, _ = await workspace_with_connection(sessions, keys, auth)

    with pytest.raises(RunSetupError, match="copilot_not_connected"):
        await token_loader(sessions, keys, auth)(a_copilot_run(mine, theirs))


@pytest.mark.integration
async def test_every_way_the_token_can_fail_is_a_fixed_code_without_the_token(
    sessions: async_sessionmaker[AsyncSession], keys: LocalKeyProvider
) -> None:
    auth = FakeGithubUserAuth("", expires_in_s=60)
    workspace_id, connection_id = await workspace_with_connection(sessions, keys, auth)
    load = token_loader(sessions, keys, auth)
    run = a_copilot_run(workspace_id, connection_id)

    auth.unavailable = True
    with pytest.raises(RunSetupError, match="copilot_unavailable"):
        await load(run)
    auth.unavailable = False

    auth.refuse_refresh = True
    with pytest.raises(RunSetupError, match="copilot_needs_attention") as refused:
        await load(run)
    assert "invalid_grant" in str(refused.value)
    auth.refuse_refresh = False
    # the refusal marked it, so it stays refused until its person connects again
    with pytest.raises(RunSetupError, match="copilot_needs_attention"):
        await load(run)

    other_keys = LocalKeyProvider(os.urandom(KEY_BYTES))
    with pytest.raises(RunSetupError, match=r"(copilot_not_connected|copilot_needs_attention)"):
        await token_loader(sessions, other_keys, auth)(run)

    with pytest.raises(RunSetupError, match="copilot_not_configured"):
        await token_loader(sessions, keys, None)(run)

    for failure in (str(refused.value),):
        assert "gho_" not in failure
        assert "ghr_" not in failure


@pytest.mark.integration
async def test_a_connection_marked_by_hand_is_refused_the_same_way(
    sessions: async_sessionmaker[AsyncSession], keys: LocalKeyProvider
) -> None:
    auth = FakeGithubUserAuth("")
    workspace_id, connection_id = await workspace_with_connection(sessions, keys, auth)
    await mark_github_user_needs_attention(sessions, workspace_id, connection_id, "unauthorized")

    with pytest.raises(RunSetupError, match=r"copilot_needs_attention.*unauthorized"):
        await token_loader(sessions, keys, auth)(a_copilot_run(workspace_id, connection_id))


class _Scripted:
    """A runtime whose one run emits the given events."""

    def __init__(self, *events: object) -> None:
        self._events = events

    def start(self, request: AgentRequest) -> "_Scripted":
        return self

    def cancel(self) -> None: ...

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for event in self._events:
            yield event


async def _collect(runtime: _Watching) -> list[object]:
    request = AgentRequest(node_id="n", role="r", instructions="i")
    return [event async for event in runtime.start(request)]


async def test_a_token_refused_mid_run_marks_the_connection_and_changes_no_event() -> None:
    refused: list[StoredRun] = []

    async def on_refused(run: StoredRun) -> None:
        refused.append(run)

    run = a_copilot_run()
    failed = Failed(error="copilot_needs_attention: GitHub refused the person's token")
    inner = _Scripted(Message(text="partial"), failed)

    events = await _collect(_Watching(inner, run, on_refused))  # pyright: ignore[reportArgumentType]

    assert events == [Message(text="partial"), failed]
    assert refused == [run]


async def test_other_failures_and_clean_runs_leave_the_connection_alone() -> None:
    refused: list[StoredRun] = []

    async def on_refused(run: StoredRun) -> None:
        refused.append(run)

    for events in (
        (Failed(error="copilot_rate_limited: try again later", retryable=True),),
        (Failed(error="Copilot error 500: boom"),),
        (Message(text="fine"),),
    ):
        await _collect(_Watching(_Scripted(*events), a_copilot_run(), on_refused))  # pyright: ignore[reportArgumentType]

    assert refused == []
