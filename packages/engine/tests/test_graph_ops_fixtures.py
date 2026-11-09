"""The graph-op cases the web's `applyOps` also runs (`schemas/fixtures/graph-ops.json`): the
engine must make of each what the fixture says, so the builder's preview (5.2) matches what the
server stores."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter

from agentic_engine.spec import GraphOp, OpError, apply_ops

FIXTURE = Path(__file__).resolve().parents[3] / "schemas" / "fixtures" / "graph-ops.json"
DOC: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
OPS: TypeAdapter[list[GraphOp]] = TypeAdapter(list[GraphOp])


@pytest.mark.parametrize("case", DOC["cases"], ids=[c["name"] for c in DOC["cases"]])
def test_the_engine_applies_each_shared_case_as_the_fixture_says(case: dict[str, Any]) -> None:
    ops = OPS.validate_python(case["ops"])
    spec = case.get("spec", DOC["spec"])
    if "result" in case:
        assert apply_ops(spec, ops) == case["result"]
        return
    with pytest.raises(OpError) as exc:
        apply_ops(spec, ops)
    error = exc.value
    assert {"code": error.code, "op_index": error.op_index, "node_id": error.node_id} == case[
        "error"
    ]
