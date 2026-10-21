import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.spec import parse_spec
from agentic_runtime import ClaudeRuntime
from agentic_runtime.fake import FakeRuntime
from agentic_runtime.testing import MockClaude
from agentic_sandbox import FakeSandboxManager
from agentic_secrets import KEY_BYTES, LocalKeyProvider
from agentic_store import StoredRun
from agentic_worker.main import (
    ConfigError,
    RunSetupError,
    WorkerSettings,
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


async def test_agentic_runtime_claude_selects_the_claude_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTIC_RUNTIME", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    monkeypatch.setenv("CLAUDE_MODEL", "claude-haiku-5-5")
    settings = WorkerSettings()
    mock = MockClaude([])

    async with run_runtimes(
        settings, NO_DB, None, lambda k: mock.make_client(k.get_secret_value())
    )(a_run(), None) as runtime:
        assert isinstance(runtime, ClaudeRuntime)

    assert settings.runtime == "claude"
    assert settings.claude_model == "claude-haiku-5-5"
    assert [c.api_key for c in mock.clients[1:]] == [KEY]
    assert mock.clients[1].is_closed()


def test_the_runtime_can_be_set_by_field_name() -> None:
    settings = WorkerSettings.model_validate({"runtime": "claude", "anthropic_api_key": KEY})
    assert settings.runtime == "claude"


@pytest.mark.parametrize("key", [None, ""])
def test_claude_without_any_key_source_fails_fast(key: str | None) -> None:
    settings = WorkerSettings.model_validate({"runtime": "claude", "anthropic_api_key": key})
    with pytest.raises(ConfigError, match="needs MASTER_KEY_FILE") as caught:
        run_runtimes(settings, NO_DB, None)
    assert "sk-ant" not in str(caught.value)


async def test_with_no_stored_and_no_env_key_the_run_cannot_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A master key alone is enough to start; a run whose workspace has no key then fails."""
    settings = WorkerSettings.model_validate({"runtime": "claude"})
    keys = LocalKeyProvider(os.urandom(KEY_BYTES))

    async def no_secret(*_args: object) -> SecretStr | None:
        return None

    monkeypatch.setattr("agentic_worker.main.load_secret", no_secret)
    with pytest.raises(RunSetupError, match="workspace has no Claude connection"):
        async with run_runtimes(settings, NO_DB, keys)(a_run(), None):
            pass


def test_a_bad_master_key_file_fails_fast(tmp_path: Path) -> None:
    bad = tmp_path / "master.key"
    bad.write_bytes(b"short")
    with pytest.raises(ConfigError, match="must hold 32 bytes"):
        build_keys(WorkerSettings.model_validate({"master_key_file": bad}))
    assert build_keys(WorkerSettings()) is None


def test_the_key_is_hidden_in_the_settings_repr() -> None:
    settings = WorkerSettings.model_validate({"runtime": "claude", "anthropic_api_key": KEY})
    assert KEY not in repr(settings)
    assert KEY not in str(settings.model_dump())


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
