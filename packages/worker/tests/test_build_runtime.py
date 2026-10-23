import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.spec import parse_spec
from agentic_github import GithubApp
from agentic_github.testing import private_key_pem
from agentic_runtime import DEFAULT_PRICES, ClaudeRuntime, PriceTable
from agentic_runtime.fake import FakeRuntime
from agentic_runtime.testing import MockClaude
from agentic_sandbox import FakeSandboxManager
from agentic_secrets import KEY_BYTES, LocalKeyProvider
from agentic_store import StoredRun
from agentic_worker.main import (
    ConfigError,
    RunSetupError,
    WorkerSettings,
    build_github,
    build_keys,
    build_sandboxes,
    run_runtimes,
)

KEY = "sk-ant-test-0000-do-not-log"
# Never bound: these tests read no stored keys.
NO_DB: async_sessionmaker[AsyncSession] = async_sessionmaker()
SPEC = parse_spec(
    json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "engine/tests/fixtures/specs/valid/single-agent.json"
        ).read_text(encoding="utf-8")
    )
)


def a_run() -> StoredRun:
    return StoredRun(id=uuid4(), status="queued", spec=SPEC, input="")


async def test_the_fake_runtime_is_the_default() -> None:
    async with run_runtimes(WorkerSettings(), NO_DB, None)(a_run(), None) as runtime:
        assert isinstance(runtime, FakeRuntime)


@pytest.fixture
def keys() -> LocalKeyProvider:
    return LocalKeyProvider(os.urandom(KEY_BYTES))


def stored(monkeypatch: pytest.MonkeyPatch, secret: SecretStr | None) -> None:
    """Every workspace's stored Claude key reads as `secret`, and its prices as the list
    prices."""

    async def load(*_args: object) -> SecretStr | None:
        return secret

    async def prices(*_args: object) -> PriceTable:
        return DEFAULT_PRICES

    monkeypatch.setattr("agentic_worker.main.load_secret", load)
    monkeypatch.setattr("agentic_worker.main.workspace_price_table", prices)


async def test_agentic_runtime_claude_runs_on_the_stored_key(
    monkeypatch: pytest.MonkeyPatch, keys: LocalKeyProvider
) -> None:
    monkeypatch.setenv("AGENTIC_RUNTIME", "claude")
    monkeypatch.setenv("CLAUDE_MODEL", "claude-haiku-5-5")
    stored(monkeypatch, SecretStr(KEY))
    settings = WorkerSettings()
    mock = MockClaude([])
    runtimes = run_runtimes(settings, NO_DB, keys, lambda k: mock.make_client(k.get_secret_value()))

    async with runtimes(a_run(), None) as runtime:
        assert isinstance(runtime, ClaudeRuntime)

    assert settings.runtime == "claude"
    assert settings.claude_model == "claude-haiku-5-5"
    assert [c.api_key for c in mock.clients[1:]] == [KEY]
    assert mock.clients[1].is_closed()


def test_the_runtime_can_be_set_by_field_name() -> None:
    assert WorkerSettings.model_validate({"runtime": "claude"}).runtime == "claude"


def test_claude_without_a_master_key_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    # A key left in the environment is no longer read.
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    settings = WorkerSettings.model_validate({"runtime": "claude"})

    with pytest.raises(ConfigError, match="needs MASTER_KEY_FILE") as caught:
        run_runtimes(settings, NO_DB, None)
    assert "sk-ant" not in str(caught.value)
    assert KEY not in repr(settings)


async def test_a_workspace_with_no_stored_key_cannot_start_a_run(
    monkeypatch: pytest.MonkeyPatch, keys: LocalKeyProvider
) -> None:
    stored(monkeypatch, None)
    settings = WorkerSettings.model_validate({"runtime": "claude"})

    with pytest.raises(RunSetupError, match="workspace has no Claude connection"):
        async with run_runtimes(settings, NO_DB, keys)(a_run(), None):
            pass


def test_a_bad_master_key_file_fails_fast(tmp_path: Path) -> None:
    bad = tmp_path / "master.key"
    bad.write_bytes(b"short")
    with pytest.raises(ConfigError, match="must hold 32 bytes"):
        build_keys(WorkerSettings.model_validate({"master_key_file": bad}))
    assert build_keys(WorkerSettings()) is None


def test_the_fake_sandbox_backend_is_the_default() -> None:
    settings = WorkerSettings()

    assert settings.sandbox_backend == "fake"
    assert settings.sandbox_local_root is None
    assert isinstance(build_sandboxes(settings), FakeSandboxManager)


def test_sandbox_settings_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANDBOX_BACKEND", "docker")
    monkeypatch.setenv("SANDBOX_IMAGE", "alpine:3.21")
    monkeypatch.setenv("SANDBOX_LOCAL_ROOT", "/samples")

    settings = WorkerSettings()

    assert (settings.sandbox_backend, settings.sandbox_image) == ("docker", "alpine:3.21")
    assert settings.sandbox_local_root == Path("/samples")


def test_the_docker_backend_without_docker_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKER_HOST", "tcp://127.0.0.1:1")

    with pytest.raises(ConfigError, match="Docker is not reachable"):
        build_sandboxes(WorkerSettings.model_validate({"sandbox_backend": "docker"}))


def test_no_github_app_without_an_id_and_slug() -> None:
    assert build_github(WorkerSettings(github_app_id=None, github_app_slug=None)) is None


def test_the_github_app_needs_its_private_key(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="GITHUB_APP_PRIVATE_KEY_FILE"):
        build_github(WorkerSettings(github_app_id=1, github_app_slug="s"))
    with pytest.raises(ConfigError, match="cannot read"):
        build_github(
            WorkerSettings(
                github_app_id=1, github_app_slug="s", github_app_private_key_file=tmp_path / "x"
            )
        )


def test_the_github_app_is_built_from_settings(tmp_path: Path) -> None:
    pem = tmp_path / "app.pem"
    pem.write_text(private_key_pem(), encoding="ascii")

    app = build_github(
        WorkerSettings(github_app_id=1, github_app_slug="s", github_app_private_key_file=pem)
    )

    assert isinstance(app, GithubApp)
    app.close()


def test_empty_github_settings_mean_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_APP_ID", "")
    monkeypatch.setenv("GITHUB_APP_SLUG", "")

    assert WorkerSettings().github_app_id is None
