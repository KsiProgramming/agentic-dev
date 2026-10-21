import pytest

from agentic_runtime import ClaudeRuntime
from agentic_runtime.fake import FakeRuntime
from agentic_worker.main import ConfigError, WorkerSettings, build_runtime

KEY = "sk-ant-test-0000-do-not-log"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings come only from each test, not from the developer's shell or `.env`."""
    for name in ("AGENTIC_RUNTIME", "ANTHROPIC_API_KEY", "CLAUDE_MODEL", "RUNTIME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(WorkerSettings.model_config, "env_file", None)


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
