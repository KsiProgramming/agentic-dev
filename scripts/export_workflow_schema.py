"""Write the workflow spec's JSON Schema to schemas/workflow-spec.v0.json, and the scan tools'
findings report (4.4) to schemas/findings.v1.json, and the graph operations (5.1) to
schemas/graph-ops.v1.json; and the node manifests (5.3) to schemas/fixtures/node-types.json, which
the web's palette tests read as `GET /node-types` answers."""

import json
from pathlib import Path

from pydantic import BaseModel

from agentic_engine.nodes import NODE_MANIFESTS
from agentic_engine.spec import GraphOps, WorkflowSpec
from agentic_runtime.findings import FindingsReport

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
SCHEMA_BASE = "https://github.com/KsiProgramming/agentic-dev/schemas"
OUTPUTS: dict[str, tuple[type[BaseModel], str]] = {
    "workflow-spec.v0.json": (WorkflowSpec, "Workflow spec v0"),
    "findings.v1.json": (FindingsReport, "Findings report v1"),
    "graph-ops.v1.json": (GraphOps, "Graph operations v1"),
}


def build(
    model: type[BaseModel] = WorkflowSpec, name: str = "workflow-spec.v0.json"
) -> dict[str, object]:
    schema = model.model_json_schema()
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{SCHEMA_BASE}/{name}",
        **schema,
        "title": OUTPUTS[name][1],
    }


def node_types() -> str:
    manifests = [m.model_dump(mode="json") for m in NODE_MANIFESTS]
    return json.dumps(manifests, indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    SCHEMAS.mkdir(exist_ok=True)
    for name, (model, _) in OUTPUTS.items():
        out = SCHEMAS / name
        text = json.dumps(build(model, name), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        out.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {out}")
    out = SCHEMAS / "fixtures" / "node-types.json"
    out.write_text(node_types(), encoding="utf-8", newline="\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
