"""Phase 1.1 demo: start a run whose agent lists the files of a repo cloned into its sandbox, and
print its events as they stream. Exits non-zero unless the run completes with a `tool_result`
that lists `expect`.

Stdlib only, so it runs anywhere Python 3.12 does (CI runs it against the compose stack):

    python scripts/sandbox_demo.py --api http://localhost:8000 --repo /samples/agentic-dev.git
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


def start_run(api: str, repo: str) -> str:
    body = json.dumps({"workflow": json.loads(SPEC.read_text("utf-8")), "repo": {"url": repo}})
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
    parser = argparse.ArgumentParser(description="Run the phase 1.1 sandbox demo.")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--repo", default="/samples/agentic-dev.git")
    parser.add_argument("--expect", default="pyproject.toml", help="a file the listing must hold")
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()

    run_id = start_run(args.api, args.repo)
    print(f"run {run_id}")
    events = stream_events(args.api, run_id, args.timeout)

    results = [e["payload"] for e in events if e["type"] == "tool_result"]
    listed = [line for r in results for line in str(r["output"]).splitlines()]
    if not events or events[-1]["type"] != "run_completed":
        print("FAIL: the run did not complete", file=sys.stderr)
        return 1
    if args.expect not in listed:
        print(f"FAIL: {args.expect} is not in the listed files", file=sys.stderr)
        return 1
    print(
        f"OK: the agent listed {len(listed)} entries of the cloned repo, {args.expect} among them"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
