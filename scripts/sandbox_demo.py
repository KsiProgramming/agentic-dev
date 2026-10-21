"""Sandbox demo: start a run on a repo cloned into its sandbox and print its events as they
stream. Exits non-zero unless the run completes, every `tool_result` succeeded, and the tool
results hold each `--expect` text.

The default spec is phase 1.1's: one agent lists the repo's files. Phase 1.2's `ask-repo.json`
has the agent list, read and search the repo through the `repo` MCP server. Phase 1.6's
`write-file.json` has a writer agent commit NOTES.md on its branch `agent/<run>/writer`, then a
tool node list the shared checkout.

Stdlib only, so it runs anywhere Python 3.12 does (CI runs it against the compose stack):

    python scripts/sandbox_demo.py --api http://localhost:8000 --repo /samples/agentic-dev.git
    python scripts/sandbox_demo.py --spec packages/engine/tests/fixtures/specs/valid/ask-repo.json
    python scripts/sandbox_demo.py \
        --spec packages/engine/tests/fixtures/specs/valid/write-file.json \
        --expect "wrote NOTES.md (" --expect "/writer: NOTES.md"
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

SPEC = (
    Path(__file__).resolve().parents[1]
    / "packages/engine/tests/fixtures/specs/valid/list-repo-files.json"
)


def start_run(api: str, spec: Path, repo: str) -> str:
    body = json.dumps({"workflow": json.loads(spec.read_text("utf-8")), "repo": {"url": repo}})
    request = urllib.request.Request(
        f"{api}/runs", data=body.encode(), headers={"content-type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)["run_id"]


def stream_events(api: str, run_id: str, timeout_s: float) -> list[dict[str, Any]]:
    """Every event of the run, printed as it arrives; the stream ends after the final event."""
    events: list[dict[str, Any]] = []
    with urllib.request.urlopen(f"{api}/runs/{run_id}/events", timeout=timeout_s) as response:
        for raw in response:
            line = raw.decode().rstrip("\n")
            if not line.startswith("data:"):
                continue
            event = json.loads(line.removeprefix("data:"))
            events.append(event)
            summary = json.dumps(event["payload"])
            print(
                f"{event['seq']:>3} {event['type']:<15} {event['node_id'] or '':<10} {summary[:90]}"
            )
    return events


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a sandbox demo against the API.")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--repo", default="/samples/agentic-dev.git")
    parser.add_argument("--spec", type=Path, default=SPEC, help="workflow spec to run")
    parser.add_argument(
        "--expect",
        action="append",
        help="text the tool results must hold; repeatable (default: pyproject.toml)",
    )
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    expected: list[str] = args.expect or ["pyproject.toml"]

    run_id = start_run(args.api, args.spec, args.repo)
    print(f"run {run_id}")
    events = stream_events(args.api, run_id, args.timeout)

    calls = [e["payload"]["name"] for e in events if e["type"] == "tool_call"]
    results = [e["payload"] for e in events if e["type"] == "tool_result"]
    output = "\n".join(str(r["output"]) for r in results)
    if not events or events[-1]["type"] != "run_completed":
        print("FAIL: the run did not complete", file=sys.stderr)
        return 1
    if not results or any(r["is_error"] for r in results):
        print("FAIL: a tool call failed or none was made", file=sys.stderr)
        return 1
    if missing := [text for text in expected if text not in output]:
        print(f"FAIL: the tool results do not hold {missing}", file=sys.stderr)
        return 1
    print(f"OK: the agent called {', '.join(calls)} on the cloned repo; found {expected}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
