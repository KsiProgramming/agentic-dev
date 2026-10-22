"""Record a docs-like run on the fake runtime to web/src/runs/fixtures/docs-run.json.

The run console's timeline tests replay it: a tool node, a map over three modules whose agents
stream two turns around a tool call, a reduce, a review loop of two iterations and a gate that is
approved. Run with `uv run python scripts/record_console_fixture.py`.
"""

import asyncio
import json
import re
from pathlib import Path
from uuid import UUID

from langgraph.checkpoint.memory import InMemorySaver
from pydantic import JsonValue

from agentic_engine.events import InMemoryEventSink
from agentic_engine.gate import GateDecision
from agentic_engine.graph import checkpoint_serde, resume_workflow, run_workflow
from agentic_engine.spec import parse_spec
from agentic_runtime import Message, TextDelta, Usage
from agentic_runtime.fake import CallTool, FakeRuntime, Script
from agentic_runtime.testing import ScriptedToolExecutor

OUT = Path(__file__).resolve().parents[1] / "web" / "src" / "runs" / "fixtures" / "docs-run.json"
RUN_ID = UUID("00000000-0000-0000-0000-00000000d0c5")

SPEC: dict[str, JsonValue] = {
    "spec_version": "0",
    "id": "generate-docs",
    "name": "Generate docs",
    "root": {
        "type": "sequence",
        "id": "main",
        "steps": [
            {"type": "tool", "id": "list_modules", "tool": "repo.list_modules", "args": {}},
            {
                "type": "map",
                "id": "document",
                "over": '["packages/api", "packages/engine", "web"]',
                "body": {
                    "type": "agent",
                    "id": "module-writer",
                    "role": "Technical writer",
                    "instructions": "Document the module whose path is your input.",
                },
                "max_concurrency": 2,
            },
            {"type": "reduce", "id": "combine", "from": "document", "strategy": "concat"},
            {
                "type": "loop",
                "id": "revise",
                "body": {
                    "type": "agent",
                    "id": "reviewer",
                    "role": "Reviewer",
                    "instructions": "Review the pages.",
                },
                "until": "iteration >= 2",
                "max_iterations": 3,
            },
            {"type": "gate", "id": "approve", "title": "Open the docs PR?"},
        ],
    },
}


def chunks(text: str) -> list[TextDelta]:
    """`text` as the model streams it: a few words per chunk."""
    return [TextDelta(text=c) for c in re.findall(r"(?:\S+\s*){1,3}", text)]


def module_writer(module: str) -> Script:
    plan = f"I will look at the files of `{module}` first."
    page = (
        f"# {module}\n\nThis module holds the **{module.split('/')[-1]}** code.\n\n"
        "- Entry point\n- Tests\n"
    )
    return [
        *chunks(plan),
        CallTool("repo.list_files", {"path": module}),
        *chunks(page),
        Message(text=page),
        Usage(input_tokens=1200, output_tokens=180),
    ]


REVIEW = "The pages are clear. Add a short index.\n\nAPPROVED"
REVIEWER: Script = [
    *chunks(REVIEW),
    Message(text=REVIEW),
    Usage(input_tokens=900, output_tokens=40),
]


async def main() -> None:
    spec = parse_spec(SPEC)
    tools = ScriptedToolExecutor(
        {
            "repo.list_modules": '{"modules": ["packages/api", "packages/engine", "web"]}',
            "repo.list_files": '{"files": ["README.md", "src/", "tests/"]}',
        }
    )
    runtime = FakeRuntime({"reviewer": REVIEWER}, default=module_writer, tools=tools)
    sink = InMemoryEventSink()
    saver = InMemorySaver(serde=checkpoint_serde())
    await run_workflow(spec, runtime, "", run_id=RUN_ID, sink=sink, checkpointer=saver, tools=tools)
    await resume_workflow(
        spec,
        runtime,
        run_id=RUN_ID,
        sink=sink,
        checkpointer=saver,
        next_seq=len(sink.events) + 1,
        attempt=2,
        tools=tools,
        decision=GateDecision(decision="approve"),
    )
    events = [e.model_dump(mode="json") for e in sink.events]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(events, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {len(events)} events to {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
