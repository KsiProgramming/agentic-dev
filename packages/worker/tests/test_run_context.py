"""What every agent of a run is told about it (`run_context`): the repository it works on and,
from 6.8, the request the person who started it typed (the run's input), so an agent whose input
is only the work before it still knows what the run is for."""

import json
from pathlib import Path
from uuid import uuid4

from agentic_engine.spec import parse_spec
from agentic_sandbox import RepoSource
from agentic_store import StoredRun
from agentic_worker.main import run_context

SPEC = parse_spec(
    json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "engine/tests/fixtures/specs/valid/single-agent.json"
        ).read_text(encoding="utf-8")
    )
)
REPO = RepoSource(url="https://github.com/acme/shop")


def stored(input: str, repo: RepoSource | None = REPO) -> StoredRun:
    return StoredRun(id=uuid4(), status="running", spec=SPEC, input=input, repo=repo)


def test_agents_are_told_the_repo_and_the_request() -> None:
    context = run_context(stored("Add rate limiting."))

    assert context is not None
    assert (context.repo, context.request) == ("acme/shop", "Add rate limiting.")
    assert "<request>\nAdd rate limiting.\n</request>" in context.text()


def test_an_empty_input_is_no_request() -> None:
    context = run_context(stored("   "))

    assert context is not None and context.request is None


def test_a_run_with_no_repo_still_tells_its_request() -> None:
    context = run_context(stored("Summarise this.", repo=None))

    assert context is not None and context.repo is None
    assert context.request == "Summarise this."
    assert run_context(stored("", repo=None)) is None
