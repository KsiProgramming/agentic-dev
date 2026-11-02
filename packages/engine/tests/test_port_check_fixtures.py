"""The port checks the builder's mirror also runs (`schemas/fixtures/port-checks.json`): the
engine must find `port_mismatch` on exactly the nodes the fixture names, so the canvas blocks the
connections the server would report (5.6)."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter

from agentic_engine.spec.models import Node, port_issues

FIXTURE = Path(__file__).resolve().parents[3] / "schemas" / "fixtures" / "port-checks.json"
DOC: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
# The spec model refuses a spec with a port mismatch; its nodes are parsed on their own.
NODE: TypeAdapter[Node] = TypeAdapter(Node)


@pytest.mark.parametrize("case", DOC["cases"], ids=[c["name"] for c in DOC["cases"]])
def test_the_engine_finds_each_shared_case_mismatches(case: dict[str, Any]) -> None:
    root = NODE.validate_python(case["spec"]["root"])
    found = [i.node_id for i in port_issues(root) if i.code == "port_mismatch"]
    assert found == case["mismatches"]
