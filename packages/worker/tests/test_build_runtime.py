from pathlib import Path

import pytest

from agentic_runtime import ClaudeRuntime
from agentic_runtime.fake import FakeRuntime
from agentic_sandbox import FakeSandboxManager
from agentic_worker.main import ConfigError, WorkerSettings, build_runtime, build_sandboxes

KEY = "sk-ant-test-0000-do-not-log"


def test_the_fake_runtime_is_the_default() -> None:
    assert isinstance(build_runtime(WorkerSettings()), FakeRuntime)


def test_agentic_runtime_claude_selects_the_claude_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTIC_RUNTIME", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    monkeypatch.setenv("CLAUDE_MODEL", "claude-haiku-5-5")

    settings = WorkerSettings()

    assert settings.runtime == "claude"
    assert settings.claude_model == "claude-haiku-5-5"
    assert isinstance(build_runtime(settings), ClaudeRuntime)


def test_the_runtime_can_be_set_by_field_name() -> None:
    settings = WorkerSettings.model_validate({"runtime": "claude", "anthropic_api_key": KEY})
    assert isinstance(build_runtime(settings), ClaudeRuntime)


@pytest.mark.parametrize("key", [None, ""])
def test_claude_without_a_key_fails_fast(key: str | None) -> None:
    settings = WorkerSettings.model_validate({"runtime": "claude", "anthropic_api_key": key})
    with pytest.raises(ConfigError, match="needs ANTHROPIC_API_KEY") as caught:
        build_runtime(settings)
    assert "sk-ant" not in str(caught.value)


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
