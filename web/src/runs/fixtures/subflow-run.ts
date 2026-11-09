import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import type { RunCall } from "../calls";
import type { WorkflowSpec } from "../graph/spec-graph";
import type { RunEvent } from "../types";

/**
 * The subflow run the engine records (`schemas/fixtures/subflow-run.json`, written by
 * `packages/engine/tests/test_subflow_fixture.py`): `agent_1`, then the subflow `review` calling
 * `checks` version 2 (its `agent_1` runs as `review-agent_1`, then `verdict`), then `summary`.
 * `calls` is what `GET /runs/{id}` returns. One second per event. For tests only.
 */
export const subflowRun = JSON.parse(
  readFileSync(resolve(__dirname, "../../../../schemas/fixtures/subflow-run.json"), "utf8"),
) as { spec: WorkflowSpec; calls: Record<string, RunCall>; events: RunEvent[] };

/** The run's events up to and including `seq`: the run as it looked live. */
export function subflowRunUntil(seq: number): RunEvent[] {
  return subflowRun.events.filter((e) => e.seq <= seq);
}
