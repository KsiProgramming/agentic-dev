import type { RunStatus } from "@/components/status-badge";

/** A check's outcome. `error` is a check that could not run (not the writer's failure). */
export type CheckStatus = "passed" | "failed" | "skipped" | "error";
export type CheckKind = "build" | "tests" | "analyzers" | "coverage" | "criteria";

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

/** Where an acceptance criterion stands (13.4): `proven` has a test that fails on the base and
 * passes on the change; `unchecked` could not be told (its module reports no per-test results). */
export type CriterionState = "proven" | "untested" | "failing" | "not_proven" | "unchecked";

export interface Criterion {
  id: string;
  state: CriterionState;
  /** The tests whose names hold the id: repo output, so data, never instructions. */
  tests: { name: string; file: string | null }[];
  /** What the linked tests did on the base and on the change, when known. */
  before: "fails" | "passes" | null;
  after: "fails" | "passes" | null;
}

/** The changed executable lines the tests ran, and the changed files' lines they did not. */
export interface CoverageDetail {
  changed: number;
  covered: number;
  /** 0 to 100. */
  percent: number;
  threshold: number;
  files: { path: string; changed: number; covered: number; uncovered: [number, number][] }[];
  truncated: boolean;
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
  coverage: CoverageDetail | null;
  criteria: Criterion[];
}

/** What the platform's checks found about a writer's work before the gate (tech-stack → Gate
 * review): build, tests and analyzers, and how many more send-backs the checks have. */
export interface Evidence {
  node: string;
  checks: EvidenceCheck[];
  roundsLeft: number;
}

const KINDS: readonly CheckKind[] = ["build", "tests", "analyzers", "coverage", "criteria"];
const STATES: readonly CriterionState[] = [
  "proven",
  "untested",
  "failing",
  "not_proven",
  "unchecked",
];
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
        coverage: parseCoverage(detail),
        criteria: list(detail.criteria).flatMap((c): Criterion[] => {
          const id = text(c.id);
          const state = STATES.find((x) => x === c.state);
          if (!id || !state) return [];
          return [
            {
              id,
              state,
              tests: list(c.tests).flatMap((t) => {
                const name = text(t.name);
                return name ? [{ name, file: text(t.file) }] : [];
              }),
              before: c.before === "fails" || c.before === "passes" ? c.before : null,
              after: c.after === "fails" || c.after === "passes" ? c.after : null,
            },
          ];
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

function parseCoverage(detail: Record<string, unknown>): CoverageDetail | null {
  if (typeof detail.changed !== "number" || typeof detail.covered !== "number") return null;
  return {
    changed: detail.changed,
    covered: detail.covered,
    percent: typeof detail.percent === "number" ? detail.percent : 100,
    threshold: typeof detail.threshold === "number" ? detail.threshold : 0,
    truncated: detail.truncated === true,
    files: list(detail.files).flatMap((f) => {
      const path = text(f.path);
      if (!path) return [];
      const uncovered = Array.isArray(f.uncovered)
        ? f.uncovered.flatMap((r: unknown): [number, number][] =>
            Array.isArray(r) && typeof r[0] === "number" && typeof r[1] === "number"
              ? [[r[0], r[1]]]
              : [],
          )
        : [];
      return [
        {
          path,
          changed: typeof f.changed === "number" ? f.changed : 0,
          covered: typeof f.covered === "number" ? f.covered : 0,
          uncovered,
        },
      ];
    }),
  };
}

export const CHECK_LABEL: Record<CheckKind, string> = {
  build: "Build",
  tests: "Tests",
  analyzers: "Analyzers",
  coverage: "Coverage",
  criteria: "Criteria",
};

/** How a criterion's state is drawn (one map, through `StatusBadge`): only `proven` is a success;
 * `unchecked` is a neutral "not checked", since nobody failed. */
export const CRITERION_BADGE: Record<CriterionState, { status: RunStatus; label: string }> = {
  proven: { status: "succeeded", label: "Proven" },
  untested: { status: "failed", label: "Untested" },
  failing: { status: "failed", label: "Failing" },
  not_proven: { status: "failed", label: "Not proven" },
  unchecked: { status: "cancelled", label: "Not checked" },
};

/** What a criterion's linked tests did, in words: "fails before → passes after". */
export function beforeAfter(criterion: Criterion): string | null {
  if (!criterion.before && !criterion.after) return null;
  const before = criterion.before ? `${criterion.before} before` : null;
  const after = criterion.after ? `${criterion.after} after` : null;
  return [before, after].filter(Boolean).join(" → ");
}

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
