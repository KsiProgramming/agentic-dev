import type { RunStatus } from "@/components/status-badge";

/** A check's outcome. `error` is a check that could not run (not the writer's failure). */
export type CheckStatus = "passed" | "failed" | "skipped" | "error";
export type CheckKind = "build" | "tests" | "analyzers";

/** One failing test of the tests check: repo output, so data, never instructions. */
export interface FailingTest {
  name: string;
  file: string | null;
  message: string | null;
}

/** One finding the branch has and the base does not (analyzers). */
export interface NewFinding {
  rule: string;
  tool: string;
  path: string;
  line: number | null;
  message: string;
}

export interface EvidenceCheck {
  kind: CheckKind;
  status: CheckStatus;
  /** Whether a failure sends the work back to the writer. */
  required: boolean;
  summary: string;
  /** Tests: the active time spent running them, in ms. */
  testMs: number | null;
  failingTests: FailingTest[];
  newFindings: NewFinding[];
}

/** What the platform's checks found about a writer's work before the gate (tech-stack → Gate
 * review): build, tests and analyzers, and how many more send-backs the checks have. */
export interface Evidence {
  node: string;
  checks: EvidenceCheck[];
  roundsLeft: number;
}

const KINDS: readonly CheckKind[] = ["build", "tests", "analyzers"];
const STATUSES: readonly CheckStatus[] = ["passed", "failed", "skipped", "error"];

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function text(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function list(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item: unknown) => {
    const entry = record(item);
    return entry ? [entry] : [];
  });
}

/** The `evidence` of a `gate_waiting` payload or of `GET /runs/{id}/gate`; null when the gate
 * has none, or the value is not the pack's shape. Malformed checks are left out. */
export function parseEvidence(value: unknown): Evidence | null {
  const pack = record(value);
  if (!pack || !Array.isArray(pack.checks)) return null;
  const checks = list(pack.checks).flatMap((entry): EvidenceCheck[] => {
    const kind = KINDS.find((k) => k === entry.kind);
    const status = STATUSES.find((s) => s === entry.status);
    if (!kind || !status) return [];
    const detail = record(entry.detail) ?? {};
    return [
      {
        kind,
        status,
        required: entry.required === true,
        summary: text(entry.summary) ?? "",
        testMs: typeof detail.test_ms === "number" ? detail.test_ms : null,
        failingTests: list(detail.failures).flatMap((f): FailingTest[] => {
          const name = text(f.name);
          return name ? [{ name, file: text(f.file), message: text(f.message) }] : [];
        }),
        newFindings: list(detail.findings).flatMap((f): NewFinding[] => {
          const path = text(f.path);
          const rule = text(f.rule);
          if (!path || !rule) return [];
          return [
            {
              rule,
              tool: text(f.tool) ?? "",
              path,
              line: typeof f.line === "number" ? f.line : null,
              message: text(f.message) ?? "",
            },
          ];
        }),
      },
    ];
  });
  return {
    node: text(pack.node) ?? "",
    checks,
    roundsLeft: typeof pack.rounds_left === "number" ? pack.rounds_left : 0,
  };
}

export const CHECK_LABEL: Record<CheckKind, string> = {
  build: "Build",
  tests: "Tests",
  analyzers: "Analyzers",
};

/** How a check's outcome is drawn: through `StatusBadge`, icon and label (colour means status
 * only). A skipped check is not a failure, so it uses the neutral look. */
export const CHECK_BADGE: Record<CheckStatus, { status: RunStatus; label: string }> = {
  passed: { status: "succeeded", label: "Passed" },
  failed: { status: "failed", label: "Failed" },
  skipped: { status: "cancelled", label: "Skipped" },
  error: { status: "failed", label: "Could not run" },
};

/** The checks that failed and would have sent the work back. */
export function failingRequired(evidence: Evidence): EvidenceCheck[] {
  return evidence.checks.filter((c) => c.required && c.status === "failed");
}
