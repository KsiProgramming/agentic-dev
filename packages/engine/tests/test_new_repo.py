"""`wrap_with_create_repo`: a workflow run on a repo it creates first (phase 1.12)."""

import pytest
from pydantic import ValidationError

from agentic_engine.policy import PLATFORM_POLICY
from agentic_engine.spec import (
    GateNode,
    SequenceNode,
    ToolNode,
    parse_spec,
    validate_workflow,
)
from agentic_engine.templates import DocsParams, NewRepo, build_docs_spec, wrap_with_create_repo
from agentic_engine.templates.new_repo import create_prompt


def test_the_docs_workflow_gets_a_gate_and_the_create_step_first() -> None:
    docs = build_docs_spec(DocsParams())
    repo = NewRepo(name="docs-new", gitignore="Python", license="mit", description="Docs")

    wrapped = wrap_with_create_repo(docs, repo, "acme")

    assert isinstance(wrapped.root, SequenceNode) and isinstance(docs.root, SequenceNode)
    assert wrapped.root.id == docs.root.id
    gate, create, *rest = wrapped.root.steps
    assert isinstance(gate, GateNode) and gate.title == "Create the repo acme/docs-new?"
    assert isinstance(create, ToolNode)
    assert (create.tool, create.args) == (
        "github.createRepo",
        {
            "name": "docs-new",
            "private": True,
            "description": "Docs",
            "gitignore": "Python",
            "license": "mit",
        },
    )
    assert rest == docs.root.steps
    assert (wrapped.id, wrapped.name) == (docs.id, docs.name)
    raw = wrapped.model_dump(mode="json", by_alias=True)
    assert (
        validate_workflow(raw, policy=PLATFORM_POLICY, priced=lambda _: True, default_model="m")
        == []
    )


def test_a_root_that_is_not_a_sequence_becomes_a_step() -> None:
    single = parse_spec(
        {
            "spec_version": "0",
            "id": "one",
            "name": "One",
            "root": {"type": "tool", "id": "main", "tool": "repo.list_files", "args": {}},
        }
    )

    wrapped = wrap_with_create_repo(single, NewRepo(name="x"), "acme")

    assert isinstance(wrapped.root, SequenceNode)
    assert wrapped.root.id == "workflow"
    assert [s.id for s in wrapped.root.steps] == ["approve_repo", "create_repo", "main"]


def test_the_prompt_says_what_is_created() -> None:
    assert create_prompt(NewRepo(name="x", private=False), "acme") == (
        "Creates the public repo acme/x on GitHub, with a first commit holding a README. "
        "The workflow then runs on it."
    )
    full = NewRepo(name="x", gitignore="Node", license="apache-2.0")
    assert "a README, a Node .gitignore and the Apache 2.0 license" in create_prompt(full, "acme")


@pytest.mark.parametrize(
    "fields",
    [
        {"name": ""},
        {"name": "a/b"},
        {"name": ".."},
        {"name": "x" * 101},
        {"name": "x", "gitignore": "Cobol"},
        {"name": "x", "license": "gpl-3.0"},
        {"name": "x", "owner": "evil"},
        {"name": "x", "description": "d" * 351},
    ],
)
def test_bad_new_repos_are_refused(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        NewRepo.model_validate(fields)


def test_a_new_repo_is_private_by_default() -> None:
    assert NewRepo(name="x").private is True
