"""Write the workflow spec's JSON Schema to schemas/workflow-spec.v0.json."""

import json
from pathlib import Path

from agentic_engine.spec import WorkflowSpec

OUT = Path(__file__).resolve().parents[1] / "schemas" / "workflow-spec.v0.json"
SCHEMA_ID = "https://github.com/KsiProgramming/agentic-dev/schemas/workflow-spec.v0.json"


def build() -> dict[str, object]:
    schema = WorkflowSpec.model_json_schema()
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        **schema,
        "title": "Workflow spec v0",
    }


def main() -> None:
    OUT.parent.mkdir(exist_ok=True)
    text = json.dumps(build(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
