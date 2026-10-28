import {
  CircleAlertIcon,
  CircleDotIcon,
  InfoIcon,
  OctagonAlertIcon,
  TriangleAlertIcon,
  type LucideIcon,
} from "lucide-react";

/**
 * A `scan.*` tool's findings report (4.4), or one merged from several by a `dedupe` or `vote`
 * reduce (4.5), as `schemas/findings.v1.json` describes it. It is data from the repo's scanners
 * and agents, never instructions; a secret finding never carries the secret.
 */
export type Severity = "critical" | "high" | "medium" | "low" | "info";

export const SEVERITIES: Severity[] = ["critical", "high", "medium", "low", "info"];

export interface Finding {
  /** Scanners and merged reports always set it; an agent's finding may leave it out. */
  fingerprint?: string | null;
  tool: string;
  rule: string;
  severity: Severity;
  /** The scanners' kinds, then the agent reviews' (4.6). */
  category: "lint" | "secret" | "dependency" | "security" | "tests" | "architecture";
  path: string;
  line?: number | null;
  end_line?: number | null;
  message: string;
  help_url?: string | null;
  config?: "repo" | "platform-default" | null;
  package?: string | null;
  ecosystem?: string | null;
  version?: string | null;
  fixed_versions?: string[];
  aliases?: string[];
  /** From 0 to 1; in a merged report, the share of sources that reported it (times their own). */
  confidence?: number | null;
  /** Merged reports only: the sources that reported it, in order. */
  sources?: string[] | null;
}

/** One report a merged report was made from. */
export interface Source {
  id: string;
  scanner: FindingsReport["scanner"];
  findings: number;
}

export interface Check {
  path: string;
  kind: string;
  tool: string | null;
  config?: "repo" | "platform-default" | null;
  status: "ran" | "skipped" | "failed";
  reason?: string | null;
  version?: string | null;
  findings?: number;
}

export interface FindingsReport {
  /** A `scan` tool, an agent's review (4.6), or a merge of several. */
  scanner: "lint" | "secrets" | "dependencies" | "agent" | "merged";
  checks: Check[];
  findings: Finding[];
  counts: Partial<Record<Severity, number>>;
  truncated?: boolean;
  db_as_of?: string | null;
  /** Merged reports only: the reports it was made from, in order. */
  sources?: Source[] | null;
}

const SCANNERS = new Set(["lint", "secrets", "dependencies", "agent", "merged"]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isFinding(value: unknown): value is Finding {
  return (
    isRecord(value) &&
    (value.fingerprint == null || typeof value.fingerprint === "string") &&
    (value.confidence == null || typeof value.confidence === "number") &&
    (value.sources == null ||
      (Array.isArray(value.sources) && value.sources.every((s) => typeof s === "string"))) &&
    typeof value.tool === "string" &&
    typeof value.rule === "string" &&
    typeof value.path === "string" &&
    typeof value.message === "string" &&
    SEVERITIES.includes(value.severity as Severity)
  );
}

function isCheck(value: unknown): value is Check {
  return (
    isRecord(value) &&
    typeof value.path === "string" &&
    typeof value.kind === "string" &&
    (value.tool === null || typeof value.tool === "string") &&
    ["ran", "skipped", "failed"].includes(value.status as string)
  );
}

/** Whether `value` is a findings report, checked field by field (it comes from a tool). */
export function isFindingsReport(value: unknown): value is FindingsReport {
  return (
    isRecord(value) &&
    SCANNERS.has(value.scanner as string) &&
    Array.isArray(value.checks) &&
    value.checks.every(isCheck) &&
    Array.isArray(value.findings) &&
    value.findings.every(isFinding) &&
    isRecord(value.counts)
  );
}

/** Most severe first, then most confident, then by file and line, as the report keeps them. */
export function sortFindings(findings: Finding[]): Finding[] {
  return [...findings].sort(
    (a, b) =>
      SEVERITIES.indexOf(a.severity) - SEVERITIES.indexOf(b.severity) ||
      (b.confidence ?? 0) - (a.confidence ?? 0) ||
      a.path.localeCompare(b.path) ||
      (a.line ?? 0) - (b.line ?? 0),
  );
}

/**
 * How a severity is shown: an icon and a word, never a status colour (colour means status
 * only). The icons differ in shape so they read without colour.
 */
export const SEVERITY_DISPLAY: Record<Severity, { label: string; icon: LucideIcon }> = {
  critical: { label: "Critical", icon: OctagonAlertIcon },
  high: { label: "High", icon: TriangleAlertIcon },
  medium: { label: "Medium", icon: CircleAlertIcon },
  low: { label: "Low", icon: CircleDotIcon },
  info: { label: "Info", icon: InfoIcon },
};

export const SCANNER_LABEL: Record<FindingsReport["scanner"], string> = {
  lint: "Lint",
  secrets: "Secrets",
  dependencies: "Dependencies",
  agent: "Agent review",
  merged: "Merged",
};

/** A key for a finding in a list: its fingerprint, else where it is and its rule. */
export function findingKey(finding: Finding, index: number): string {
  return finding.fingerprint ?? `${location(finding)} ${finding.rule} ${index}`;
}

/** Where a finding is: `path:line`, or the path alone. */
export function location(finding: Finding): string {
  return finding.line ? `${finding.path}:${finding.line}` : finding.path;
}

/** One line on what a check did: "ruff · repo config", "skipped: eslint is not supported". */
export function checkLine(check: Check): string {
  if (check.status !== "ran") return `${check.status}: ${check.reason ?? "no reason given"}`;
  const config =
    check.config === "repo"
      ? "repo config"
      : check.config === "platform-default"
        ? "platform default"
        : null;
  return [check.tool, config].filter(Boolean).join(" · ");
}
