import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import type { WorkflowSpec } from "../graph/spec-graph";
import type { RunEvent } from "../types";

/**
 * The AC-2 run the engine records (`schemas/fixtures/ac2-run.json`, written by
 * `packages/engine/tests/test_ac2_fixture.py`, 6.8): the "Plan, build and review" template. A
 * parallel `explore` of two analysts, a loop `review_loop` around the orchestrator `implement`
 * (an `engineer` worker that writes), a `synthesizer` and a `reviewer`, the gate `approve_pr`
 * and `publish`. Pass 1 plans form and api and the reviewer asks for changes; pass 2 plans tests
 * and the reviewer approves; the gate is approved and one pull request opened. One second per
 * event. For tests only.
 */
export const ac2Run = JSON.parse(
  readFileSync(resolve(__dirname, "../../../../schemas/fixtures/ac2-run.json"), "utf8"),
) as { spec: WorkflowSpec; events: RunEvent[] };
