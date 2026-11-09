import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import type { WorkflowSpec } from "../graph/spec-graph";
import type { RunEvent } from "../types";

/**
 * The orchestrator run the engine records (`schemas/fixtures/orchestrator-run.json`, written by
 * `packages/engine/tests/test_orchestrator_fixture.py`): `scan`, then the orchestrator `fix`
 * with a `fixer` worker. Round 1 plans a, b, c and d: b fails, d is dropped, a completes and
 * merges, c completes and conflicts on `src/app.py`. Round 2 plans b2 and c2, which complete and
 * merge. One second per event. For tests only.
 */
export const orchestratorRun = JSON.parse(
  readFileSync(resolve(__dirname, "../../../../schemas/fixtures/orchestrator-run.json"), "utf8"),
) as { spec: WorkflowSpec; events: RunEvent[] };

/** The run's events up to and including `seq`: the run as it looked live. */
export function orchestratorRunUntil(seq: number): RunEvent[] {
  return orchestratorRun.events.filter((e) => e.seq <= seq);
}
