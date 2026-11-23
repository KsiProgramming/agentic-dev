/** What approving does (13.8): the plan of each outward write a gate guards, worked out by the
 * write's own tool without doing it (`gate_waiting.plans`, `GET /runs/{id}/gate` `plans`), and
 * how each write went against its plan (`write_checked`). Comment and pull request text is data
 * written by agents, Jira and people: text or sanitised Markdown, never markup. */

export type PlanAction = "open_pr" | "push_to_pr" | "create_repo" | "comment" | "transition";
export type PlanTargetKind = "repo" | "issue" | "pull_request";

/** What a write acts on: a repo (`org/repo`), an issue (its key) or a pull request. */
export interface PlanTarget {
  kind: PlanTargetKind;
  label: string;
  /** Where a person can see it; only an https address is kept, so it is safe to link. */
  url: string | null;
}

/** A part of the write the platform fills in only after the approval, from its own results. */
export interface PlanPending {
  kind: "links" | "review_notes";
  text: string;
}

export interface WritePlan {
  /** The tool node the plan is for. */
  nodeId: string | null;
  tool: string;
  action: PlanAction;
  /** One line the platform writes ("Move KAN-5 from In Progress to Done"). */
  summary: string;
  target: PlanTarget;
  /** The values a result is compared with: the transition's statuses, the branches, the repo. */
  fields: Record<string, unknown>;
  /** The Markdown to show (a comment, a pull request's body); data. */
  body: string | null;
  pending: PlanPending[];
  /** Why the write would fail now: a fixed code and text. */
  error: { code: string; message: string } | null;
}

const ACTIONS: readonly PlanAction[] = [
  "open_pr",
  "push_to_pr",
  "create_repo",
  "comment",
  "transition",
];
const TARGETS: readonly PlanTargetKind[] = ["repo", "issue", "pull_request"];

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

const text = (value: unknown): string | null => (typeof value === "string" ? value : null);

/** `value` when it is an https address, else null: a plan's URL comes from a tool's answer about
 * Jira or GitHub, and a `javascript:` or `http:` address is never offered as a link. */
export function httpsUrl(value: unknown): string | null {
  const raw = text(value);
  if (raw === null) return null;
  try {
    return new URL(raw).protocol === "https:" ? raw : null;
  } catch {
    return null;
  }
}

function parsePlan(value: unknown): WritePlan[] {
  const entry = record(value);
  const target = record(entry?.target);
  const tool = text(entry?.tool);
  const summary = text(entry?.summary);
  const action = ACTIONS.find((a) => a === entry?.action);
  const kind = TARGETS.find((k) => k === target?.kind);
  const label = text(target?.label);
  if (!entry || !tool || summary === null || !action || !kind || label === null) return [];
  const error = record(entry.error);
  const pending = Array.isArray(entry.pending) ? entry.pending : [];
  return [
    {
      nodeId: text(entry.node_id),
      tool,
      action,
      summary,
      target: { kind, label, url: httpsUrl(target?.url) },
      fields: record(entry.fields) ?? {},
      body: text(entry.body),
      pending: pending.flatMap((p): PlanPending[] => {
        const part = record(p);
        const kind = part?.kind === "links" || part?.kind === "review_notes" ? part.kind : null;
        const line = text(part?.text);
        return kind && line !== null ? [{ kind, text: line }] : [];
      }),
      error:
        error && text(error.code) && text(error.message) !== null
          ? { code: text(error.code)!, message: text(error.message)! }
          : null,
    },
  ];
}

/** The plans in `value` (a gate's `plans`), leaving out any that is not one. */
export function parsePlans(value: unknown): WritePlan[] {
  return Array.isArray(value) ? value.flatMap(parsePlan) : [];
}

/** A transition's statuses, from its plan's fields: null for any other plan or one that moves
 * nothing (the issue already has the status). */
export function transitionOf(plan: WritePlan): { from: string; to: string } | null {
  if (plan.action !== "transition" || plan.fields.changed === false) return null;
  const from = text(plan.fields.from_status);
  const to = text(plan.fields.to_status);
  return from && to ? { from, to } : null;
}

/** One value a write's result had, against what its plan said. Shown as text. */
export interface WriteDifference {
  field: string;
  planned: string;
  actual: string;
}

/** How a write went against its plan (`write_checked`): `as_planned`; `differs`, flagged after the
 * write; or `stale`, refused because what it was planned against changed. */
export interface WriteCheck {
  /** The gate whose plan the write was checked against. */
  gate: string | null;
  outcome: "as_planned" | "differs" | "stale";
  differences: WriteDifference[];
}

/** A value as the console shows it: a string as it is, anything else as compact JSON. */
function shown(value: unknown): string {
  if (value === null || value === undefined) return "none";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

export function parseWriteCheck(value: unknown): WriteCheck | null {
  const entry = record(value);
  const outcome = entry?.outcome;
  if (!entry || (outcome !== "as_planned" && outcome !== "differs" && outcome !== "stale")) {
    return null;
  }
  const differences = Array.isArray(entry.differences) ? entry.differences : [];
  return {
    gate: text(entry.gate),
    outcome,
    differences: differences.flatMap((d): WriteDifference[] => {
      const diff = record(d);
      const field = text(diff?.field);
      return field ? [{ field, planned: shown(diff?.planned), actual: shown(diff?.actual) }] : [];
    }),
  };
}
