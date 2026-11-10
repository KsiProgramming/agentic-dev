import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import type { WorkflowSpec } from "../graph/spec-graph";
import type { RunEvent } from "../types";

/**
 * The looped orchestrator run the engine records (`schemas/fixtures/orchestrator-loop-run.json`,
 * written by `packages/engine/tests/test_orchestrator_loop_fixture.py`, 6.9): a loop `review`
 * around the orchestrator `fix` (a `fixer` worker that writes) and a `reviewer`. Iteration 1 plans
 * a and b, merged; the reviewer asks for changes. Iteration 2 plans c on top of them, merged with
 * a and b; the reviewer approves. One second per event. For tests only.
 */
export const orchestratorLoopRun = JSON.parse(
  readFileSync(
    resolve(__dirname, "../../../../schemas/fixtures/orchestrator-loop-run.json"),
    "utf8",
  ),
) as { spec: WorkflowSpec; events: RunEvent[] };
