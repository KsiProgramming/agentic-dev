import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import type { WorkflowSpec } from "../graph/spec-graph";
import type { RunEvent } from "../types";

/**
 * The independent-review run the engine records (`schemas/fixtures/review-run.json`, 13.6): pass
 * 1 is sent back by the review (`gate_decided.source: "review"`), pass 2 pauses at the gate with
 * two comments (a medium one on `form.py:3`, in the diff, and a low one on `README.md`, which
 * the change did not touch), and the approver approves with one dismissal. Its lens agents have
 * `node_started.review`. For tests only.
 */
export const reviewRun = JSON.parse(
  readFileSync(resolve(__dirname, "../../../../schemas/fixtures/review-run.json"), "utf8"),
) as { spec: WorkflowSpec; events: RunEvent[] };
