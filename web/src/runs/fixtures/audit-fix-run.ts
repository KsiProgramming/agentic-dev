import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import type { WorkflowSpec } from "../graph/spec-graph";
import type { RunEvent } from "../types";

/**
 * The audit-and-fix run the engine records (`schemas/fixtures/audit-fix-run.json`, written by
 * `packages/engine/tests/test_audit_fix_fixture.py`, 6.7): an audit with `fix` on pauses at the
 * selection gate `select_fixes` on findings b (critical), c (high) and a (low), b and c checked;
 * b and a are chosen; the orchestrator `fix` fixes them in two tasks; the run pauses at
 * `approve_pr`, then opens the pull request. `waiting` is how many events it had at its first
 * pause, and `artifacts["findings.json"]` the artifact the checklist reads. For tests only.
 */
export const auditFixRun = JSON.parse(
  readFileSync(resolve(__dirname, "../../../../schemas/fixtures/audit-fix-run.json"), "utf8"),
) as {
  spec: WorkflowSpec;
  waiting: number;
  artifacts: { "findings.json": unknown };
  events: RunEvent[];
};

/** The run's events at its first pause, at the selection gate. */
export const auditFixWaiting: RunEvent[] = auditFixRun.events.slice(0, auditFixRun.waiting);
