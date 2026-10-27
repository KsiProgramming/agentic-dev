import {
  BanIcon,
  CircleCheckIcon,
  CircleXIcon,
  CoinsIcon,
  FlagIcon,
  FolderPlusIcon,
  GaugeIcon,
  PlayIcon,
  PlugIcon,
  RotateCcwIcon,
  UnplugIcon,
  type LucideIcon,
} from "lucide-react";

import { shortId } from "@/components/display/short-id";
import { formatPrice, formatUsd } from "@/runs/cost";

import type { components } from "@/api/schema";
import { repoLabel } from "@/runs/summaries";

/** One entry of `GET /workspaces/{id}/audit`. */
export type AuditEvent = components["schemas"]["AuditEventOut"];
export type AuditPage = components["schemas"]["AuditPage"];
export type AuditAction = AuditEvent["action"];

/** What the filter groups actions by. */
export type AuditCategory = "runs" | "approvals" | "settings";

interface ActionInfo {
  label: string;
  icon: LucideIcon;
  category: AuditCategory;
}

const ACTIONS: Record<AuditAction, ActionInfo> = {
  "run.created": { label: "Run started", icon: PlayIcon, category: "runs" },
  "run.rerun": { label: "Run rerun", icon: RotateCcwIcon, category: "runs" },
  "run.cancel_requested": { label: "Cancel requested", icon: BanIcon, category: "runs" },
  "run.ended": { label: "Run ended", icon: FlagIcon, category: "runs" },
  "repo.created": { label: "Repo created", icon: FolderPlusIcon, category: "runs" },
  "gate.approved": { label: "Gate approved", icon: CircleCheckIcon, category: "approvals" },
  "gate.rejected": { label: "Gate rejected", icon: CircleXIcon, category: "approvals" },
  "connection.added": { label: "Connection added", icon: PlugIcon, category: "settings" },
  "connection.removed": { label: "Connection removed", icon: UnplugIcon, category: "settings" },
  "policy.updated": { label: "Run limits changed", icon: GaugeIcon, category: "settings" },
  "pricing.updated": { label: "Prices changed", icon: CoinsIcon, category: "settings" },
};

export const AUDIT_CATEGORIES: readonly { id: AuditCategory; label: string }[] = [
  { id: "runs", label: "Runs" },
  { id: "approvals", label: "Approvals" },
  { id: "settings", label: "Settings" },
];

/** The actions of a filter category, as `GET /workspaces/{id}/audit` takes them. */
export function actionsOf(category: AuditCategory): AuditAction[] {
  return (Object.keys(ACTIONS) as AuditAction[]).filter((a) => ACTIONS[a].category === category);
}

/** An action's label and icon; an action this page does not know yet shows its name. */
export function actionInfo(action: string): { label: string; icon: LucideIcon | null } {
  const info = (ACTIONS as Record<string, ActionInfo | undefined>)[action];
  return info ?? { label: action, icon: null };
}

// `details` is data written by the API, read defensively: a field of the wrong type is absent.
type Details = AuditEvent["details"];

function text(details: Details, key: string): string | null {
  const value = details[key];
  return typeof value === "string" && value !== "" ? value : null;
}

function count(details: Details, key: string): number {
  const value = details[key];
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function strings(details: Details, key: string): string[] {
  const value = details[key];
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

function record(details: Details, key: string): Details {
  const value = details[key];
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Details)
    : {};
}

const PROVIDERS: Record<string, string> = { claude: "Claude", github: "GitHub" };

const LIMITS: [key: string, label: string][] = [
  ["agents_alive", "agents alive"],
  ["agents_spawned", "agents spawned"],
  ["max_depth", "nesting depth"],
  ["loop_iterations", "loop iterations"],
  ["wall_time_s", "wall time (s)"],
  ["budget_usd", "budget"],
];

const END_STATUS: Record<string, string> = {
  completed: "Succeeded",
  failed: "Failed",
  cancelled: "Cancelled",
};

function usd(amount: string | null): string | null {
  if (amount === null) return null;
  const n = Number(amount);
  return Number.isFinite(n) ? formatPrice(n) : null;
}

function limit(key: string, value: Details[string] | undefined): string {
  if (value === null || value === undefined) return key === "budget_usd" ? "none" : "default";
  if (key === "budget_usd") return usd(String(value)) ?? String(value);
  return String(value);
}

function plural(n: number, one: string): string {
  return `${n} ${one}${n === 1 ? "" : "s"}`;
}

function join(...parts: (string | null | false)[]): string {
  return parts.filter(Boolean).join(" · ");
}

/** One line saying what an entry did, as plain text (never HTML). */
export function describe(event: AuditEvent): string {
  const d = event.details;
  switch (event.action) {
    case "run.created":
    case "run.rerun": {
      const of = event.action === "run.rerun" ? text(d, "rerun_of") : null;
      const template = text(d, "template_id");
      const repo = text(d, "repo_url");
      const budget = usd(text(d, "budget_usd"));
      return join(
        [
          of ? `Rerun of ${shortId(of)}` : template ? `Started ${template}` : "Started a workflow",
          repo ? `on ${repoLabel(repo)}` : null,
        ]
          .filter(Boolean)
          .join(" "),
        budget && `budget ${budget}`,
      );
    }
    case "run.cancel_requested": {
      const status = text(d, "status");
      return status ? `Asked to cancel while ${status}` : "Asked to cancel";
    }
    case "run.ended": {
      const status = text(d, "status");
      const spent = Number(text(d, "estimated_usd") ?? Number.NaN);
      const cost = Number.isFinite(spent) && spent > 0 ? formatUsd(spent) : null;
      return join(
        status ? (END_STATUS[status] ?? status) : "Ended",
        status === "failed" && text(d, "failure_reason"),
        cost && `${d.cost_complete === false ? "≥ " : ""}${cost}`,
        text(d, "pr_url"),
      );
    }
    case "repo.created": {
      const name = text(d, "full_name");
      const visibility = d.private === true ? "private " : d.private === false ? "public " : "";
      return `Created the ${visibility}repo ${name ?? "of the run"}`;
    }
    case "gate.approved":
    case "gate.rejected": {
      const edited = count(d, "edited_files");
      const comment = text(d, "comment");
      return join(
        `${event.action === "gate.approved" ? "Approved" : "Rejected"} ${event.node_id ?? "a gate"}` +
          (edited > 0 ? ` with edits to ${plural(edited, "file")}` : ""),
        comment && `“${comment}”`,
      );
    }
    case "connection.added":
    case "connection.removed": {
      const provider = text(d, "provider");
      const name = (provider && PROVIDERS[provider]) ?? provider ?? "a connection";
      const hint = text(d, "key_hint");
      const account = text(d, "account_login");
      const what = hint ? `${name} key ····${hint}` : account ? `${name} (${account})` : name;
      if (event.action === "connection.removed") return `Removed ${what}`;
      return `${d.replaced === true ? "Replaced" : "Added"} ${what}`;
    }
    case "policy.updated": {
      const before = record(d, "before");
      const after = record(d, "after");
      const changes = LIMITS.filter(([key]) => (before[key] ?? null) !== (after[key] ?? null)).map(
        ([key, label]) => `${label} ${limit(key, before[key])} → ${limit(key, after[key])}`,
      );
      return changes.length > 0 ? changes.join(", ") : "Run limits saved";
    }
    case "pricing.updated": {
      const groups: [string, string[]][] = [
        ["added", strings(d, "added")],
        ["changed", strings(d, "changed")],
        ["removed", strings(d, "removed")],
      ];
      const parts = groups.filter(([, models]) => models.length > 0);
      return parts.length > 0
        ? parts.map(([verb, models]) => `${verb} ${models.join(", ")}`).join("; ")
        : "Prices saved";
    }
    default:
      return actionInfo(event.action).label;
  }
}
