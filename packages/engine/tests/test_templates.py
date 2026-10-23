"""Templates build specs that validate, for every option; bad options are refused."""

from typing import Any

import pytest
from pydantic import JsonValue, ValidationError

from agentic_engine.spec import AgentNode, GateNode, MapNode, SequenceNode, ToolNode, iter_nodes
from agentic_engine.templates import TEMPLATES, DocsParams, build_docs_spec, get_template
from agentic_engine.templates.docs import MAX_MODULES


def _ids(params: DocsParams) -> list[str]:
    root = build_docs_spec(params).root
    assert isinstance(root, SequenceNode)
    return [step.id for step in root.steps]


def _steps(params: DocsParams) -> dict[str, Any]:
    return {node.id: node for _, node in iter_nodes(build_docs_spec(params).root)}


def test_the_docs_template_is_registered() -> None:
    template = get_template("generate-docs")

    assert template is not None
    assert [t.id for t in TEMPLATES] == ["generate-docs"]
    assert set(template.parameters_schema()["properties"]) == {
        "output_dir",
        "include",
        "extra_instructions",
    }
    assert get_template("missing") is None


def test_default_options_build_the_docs_flow() -> None:
    steps = _steps(DocsParams())

    assert _ids(DocsParams()) == [
        "list_modules", "document", "combine", "writer", "approve", "publish",
    ]  # fmt: skip
    assert steps["list_modules"] == ToolNode(
        type="tool", id="list_modules", tool="repo.list_modules", args={"limit": MAX_MODULES}
    )
    assert isinstance(steps["document"], MapNode)
    assert steps["document"].over == "results.list_modules.data.modules"
    body = steps["document_module"]
    assert isinstance(body, AgentNode)
    assert set(body.tools) == {"repo.list_files", "repo.read_file", "repo.search"}
    assert "`docs/README.md`" in steps["writer"].instructions
    assert "<user-preferences>" not in steps["writer"].instructions


def test_options_reach_the_spec() -> None:
    params = DocsParams(
        output_dir="documentation/modules/",
        include=["packages/*"],
        extra_instructions="  Write for new contributors.  ",
    )
    steps = _steps(params)

    assert steps["list_modules"].args == {"limit": MAX_MODULES, "include": ["packages/*"]}
    writer = steps["writer"].instructions
    assert "`documentation/modules/README.md`" in writer
    assert "Only write files under `documentation/modules/`" in writer
    for node in (steps["writer"], steps["document_module"]):
        assert node.instructions.endswith(
            "<user-preferences>\nWrite for new contributors.\n</user-preferences>"
        )
    assert "packages/*" in steps["publish"].args["body"]


def test_the_gate_always_comes_before_the_pull_request() -> None:
    ids = _ids(DocsParams())

    assert isinstance(_steps(DocsParams())["approve"], GateNode)
    assert ids.index("writer") < ids.index("approve") < ids.index("publish")
    assert _steps(DocsParams())["publish"].args["from_node"] == "writer"


@pytest.mark.parametrize(
    "parameters",
    [
        {"output_dir": "../outside"},
        {"output_dir": "docs/../../x"},
        {"output_dir": "/etc"},
        {"output_dir": r"C:\docs"},
        {"output_dir": ".git/hooks"},
        {"output_dir": "./docs"},
        {"output_dir": ""},
        {"include": [""]},
        {"include": ["x"] * 21},
        {"extra_instructions": "x" * 2001},
        {"unknown": True},
    ],
)
def test_bad_options_are_refused(parameters: dict[str, JsonValue]) -> None:
    template = get_template("generate-docs")
    assert template is not None

    with pytest.raises(ValidationError):
        template.build_spec(parameters)


def test_blank_extra_instructions_are_unset() -> None:
    assert DocsParams(extra_instructions="   ").extra_instructions is None
